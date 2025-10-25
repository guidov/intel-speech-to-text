#!/usr/bin/env python3
from __future__ import annotations
"""Hotkey listener that records audio and triggers speech-to-text.

Designed for Arch Linux + Wayland setups where the transcription is typed via
``ydotool``. The script must run as root because it reads from ``/dev/input`` and
launches privileged helpers, while the actual audio capture runs as the regular
user owning the graphical session.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
import pwd

try:
    import config  # type: ignore
except ModuleNotFoundError as exc:  # pragma: no cover - configuration error
    raise SystemExit(
        "Missing config.py. Copy config.example.py, adjust it, and try again."
    ) from exc

try:
    from evdev import InputDevice, categorize, ecodes
    from evdev.events import KeyEvent
    import whisper
    import torch
    import intel_extension_for_pytorch as ipex
except ImportError as exc:  # pragma: no cover - dependency issue
    raise SystemExit(
        "Required packages are missing. Install dependencies with pip install -r requirements.txt"
    ) from exc


def setup_logging() -> None:
    """Configure logging to stdout and optional file from the config."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = getattr(config, "KEY_LISTENER_LOG_FILE", None)
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_path))
        except (OSError, PermissionError):
            # Fall back to console-only logging if we cannot create the file.
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=handlers,
    )


def resolve_user(username: str) -> pwd.struct_passwd:
    """Return passwd entry for TARGET_USER, exiting if the user does not exist."""
    try:
        return pwd.getpwnam(username)
    except KeyError as exc:  # pragma: no cover - system configuration error
        logging.error("Configured user %s does not exist", username)
        raise SystemExit(1) from exc


def discover_wayland_display(runtime_dir: Path) -> str:
    """Return the configured Wayland display or try to auto-detect one."""
    configured = getattr(config, "WAYLAND_DISPLAY", None)
    if configured:
        return configured

    for candidate in sorted(runtime_dir.glob("wayland-*")):
        logging.info("Auto-detected Wayland display: %s", candidate.name)
        return candidate.name

    logging.warning("No Wayland display found, falling back to 'wayland-0'")
    return "wayland-0"


def create_whisper_model() -> whisper.Whisper:
    """Load and optimize the Whisper model once at startup."""
    model_size = getattr(config, "WHISPER_MODEL_SIZE", "small")
    device_config = getattr(config, "WHISPER_DEVICE", "auto").lower()
    
    # Determine device based on configuration
    if device_config == "cpu":
        device = "cpu"
        logging.info("CPU device selected via configuration")
    elif device_config == "xpu":
        if torch.xpu.is_available():
            device = "xpu"
            logging.info("XPU device selected via configuration")
        else:
            logging.error("XPU requested but not available!")
            raise SystemExit(1)
    else:  # auto
        if torch.xpu.is_available():
            device = "xpu"
            logging.info("Intel XPU detected and will be used for acceleration")
        else:
            device = "cpu"
            logging.info("No XPU available, using CPU")
    
    logging.info("Loading Whisper model '%s' on device '%s' (this happens once at startup)", model_size, device)
    model = whisper.load_model(model_size, device=device)
    
    # Apply IPEX optimizations for inference on XPU
    if device == "xpu":
        model.eval()  # Set to evaluation mode for inference
        with torch.no_grad():
            model = ipex.optimize(model, dtype=torch.float32)
        logging.info("IPEX optimizations applied to model")
    
    logging.info("Model loaded and ready for transcription")
    return model


def build_environment(info: pwd.struct_passwd) -> dict[str, str]:
    """Construct environment inheriting the user's runtime directories."""
    runtime_dir = Path(f"/run/user/{info.pw_uid}")
    env = os.environ.copy()
    env.update(
        {
            "HOME": info.pw_dir,
            "XDG_CACHE_HOME": str(Path(info.pw_dir) / ".cache"),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "DISPLAY": getattr(config, "DISPLAY", ":0"),
            "WAYLAND_DISPLAY": discover_wayland_display(runtime_dir),
        }
    )
    return env


def find_keyboard_device(trigger_keycode: str = "KEY_RIGHTCTRL") -> str | None:
    """Dynamically find the keyboard device that supports the trigger key."""
    from pathlib import Path
    import evdev
    
    logging.info("Starting keyboard device detection for trigger key: %s", trigger_keycode)
    
    # List all input devices in /dev/input/
    input_dir = Path("/dev/input")
    
    # Get list of event devices
    event_devices = [f for f in input_dir.glob("event*")]
    logging.info("Found %d input event devices to check", len(event_devices))
    
    # Sort by event number to try in order (lower numbers first)
    event_devices.sort(key=lambda x: int(x.name.replace("event", "")))
    
    # First, try to find a device that has the trigger key
    trigger_evcode = evdev.ecodes.ecodes.get(trigger_keycode)
    if trigger_evcode is None:
        logging.warning("Trigger keycode %s not found in evdev codes", trigger_keycode)
        return None
        
    logging.info("Looking for evdev code %d (%s) in available devices", trigger_evcode, trigger_keycode)
    
    for device_path in event_devices:
        try:
            device = evdev.InputDevice(str(device_path))
            logging.debug("Checking device %s: '%s'", device.path, device.name)
            
            # Check if this device supports the trigger key
            # The device.cap contains capability information
            if hasattr(device, 'cap') and evdev.ecodes.EV_KEY in device.cap:
                # Get all key codes this device supports
                keys = device.cap[evdev.ecodes.EV_KEY]
                logging.debug("Device %s supports %d key codes", device.path, len(keys))
                
                if trigger_evcode in keys:
                    logging.info("Found keyboard device with trigger key %s at %s", trigger_keycode, device.path)
                    return str(device.path)
            else:
                logging.debug("Device %s does not support EV_KEY events", device.path)
                
        except (PermissionError, OSError) as e:
            # Skip devices we can't access
            logging.debug("Cannot access device %s: %s", device_path, str(e))
            continue
        except Exception as e:
            # Skip devices that cause other errors
            logging.debug("Error accessing device %s: %s", device_path, str(e))
            continue
    
    logging.info("No device found with trigger key %s, trying to find keyboard by name", trigger_keycode)
    
    # If we can't find by trigger key, try to find a keyboard-like device by name
    for device_path in event_devices:
        try:
            device = evdev.InputDevice(str(device_path))
            # Check if device name contains common keyboard indicators
            device_name_lower = device.name.lower()
            if any(keyword in device_name_lower for keyword in ['keyboard', 'key', 'kbd']):
                logging.info("Found keyboard-like device by name '%s' at %s", device.name, device.path)
                return str(device.path)
            else:
                logging.debug("Device '%s' at %s does not appear to be a keyboard", device.name, device.path)
        except (PermissionError, OSError) as e:
            logging.debug("Cannot access device %s for name check: %s", device_path, str(e))
            continue
        except Exception as e:
            logging.debug("Error accessing device %s for name check: %s", device_path, str(e))
            continue
    
    logging.warning("No keyboard device found with trigger key %s and no keyboard-like names found", trigger_keycode)
    return None


def resolve_socket_path() -> Path:
    """Return path to the ydotool socket used for typing."""
    socket_path = getattr(config, "YDOTOOL_SOCKET", None)
    if socket_path:
        return Path(socket_path)

    try:
        user_info = pwd.getpwnam(config.TARGET_USER)
    except KeyError as exc:  # pragma: no cover - system misconfiguration
        logging.error("Configured user %s does not exist", config.TARGET_USER)
        raise SystemExit(1) from exc
    runtime_dir = Path(f"/run/user/{user_info.pw_uid}")
    return runtime_dir / ".ydotool_socket"


def transcribe_and_type(audio_path: Path, model: whisper.Whisper, socket_path: Path) -> None:
    """Transcribe audio file and type the result using ydotool."""
    import shutil
    
    # Transcribe audio
    logging.info("Transcribing audio...")
    result = model.transcribe(str(audio_path))
    text = result["text"].strip()
    
    if not text:
        logging.info("No text recognized")
        return
    
    logging.info("Recognized: %s", text)
    
    # Type the text
    if shutil.which("ydotool") is None:
        logging.error("ydotool not found. Install the ydotool package.")
        return

    if not socket_path.exists():
        logging.error("ydotool socket missing: %s", socket_path)
        logging.error("Ensure ydotoold.service is running and created the socket.")
        return

    env = os.environ.copy()
    env["YDOTOOL_SOCKET"] = str(socket_path)

    # Get typing delay from config (default 12ms if not specified)
    key_delay = getattr(config, "YDOTOOL_KEY_DELAY", 12)

    try:
        subprocess.run(
            ["ydotool", "type", "--key-delay", str(key_delay), text + " "],
            env=env,
            check=True
        )
        logging.info("Typed text successfully")
    except subprocess.CalledProcessError as exc:
        logging.error("ydotool returned non-zero exit status: %s", exc)


def main() -> None:
    """Listen for the configured key events and orchestrate recording."""
    setup_logging()

    if os.geteuid() != 0:
        logging.error("key_listener.py must be executed as root (use systemd or sudo)")
        raise SystemExit(1)

    user_info = resolve_user(config.TARGET_USER)
    env = build_environment(user_info)

    audio_file = Path(config.AUDIO_FILE)
    audio_file.parent.mkdir(parents=True, exist_ok=True)

    # Load Whisper model once at startup
    whisper_model = create_whisper_model()
    socket_path = resolve_socket_path()

    # Determine device path - prefer dynamic detection over static config
    configured_device_path = str(config.DEVICE_PATH)
    trigger_key = getattr(config, "TRIGGER_KEYCODE", "KEY_RIGHTCTRL")
    
    logging.info("Attempting to detect keyboard device dynamically...")
    # Try dynamic detection first to ensure we have the correct keyboard device
    detected_device = find_keyboard_device(trigger_key)
    if detected_device:
        if detected_device != configured_device_path:
            logging.info("Dynamically detected device %s differs from configured device %s", detected_device, configured_device_path)
        device_path = detected_device
        logging.info("Using dynamically detected device: %s", device_path)
    else:
        logging.info("Dynamic detection failed, falling back to configured device: %s", configured_device_path)
        # If dynamic detection fails, verify the configured device exists and is accessible
        if os.path.exists(configured_device_path):
            device_path = configured_device_path
        else:
            logging.error("Configured device %s does not exist and dynamic detection failed.", configured_device_path)
            raise SystemExit(1)

    try:
        device = InputDevice(device_path)
        logging.info("Successfully opened device %s", device_path)
    except FileNotFoundError as exc:
        logging.error("Input device %s not found. Adjust DEVICE_PATH in config.py", device_path)
        raise SystemExit(1) from exc
    except PermissionError as exc:
        logging.error("Permission denied opening %s. Run as root or adjust ACLs.", device_path)
        raise SystemExit(1) from exc

    logging.info("Listening for %s on %s", trigger_key, device_path)

    recording_process: subprocess.Popen[bytes] | None = None

    try:
        for event in device.read_loop():
            if event.type != ecodes.EV_KEY:
                continue

            key_event = categorize(event)
            if not isinstance(key_event, KeyEvent):
                continue

            # Ignore repeated key events.
            if key_event.keystate == 2:
                continue

            if key_event.keycode != trigger_key:
                continue

            if key_event.keystate == key_event.key_down and recording_process is None:
                logging.info("Starting audio recording")
                try:
                    recording_process = subprocess.Popen(
                        [
                            "sudo",
                            "-u",
                            config.TARGET_USER,
                            "-E",
                            "arecord",
                            "-f",
                            getattr(config, "SAMPLE_FORMAT", "S16_LE"),
                            "-r",
                            str(getattr(config, "SAMPLE_RATE_HZ", 16_000)),
                            "-c",
                            str(getattr(config, "CHANNELS", 1)),
                            str(audio_file),
                        ],
                        env=env,
                    )
                except FileNotFoundError as exc:
                    logging.error("arecord not found. Install alsa-utils.")
                    raise SystemExit(1) from exc
                logging.info("Recording started with PID %s", recording_process.pid)

            elif key_event.keystate == key_event.key_up and recording_process:
                logging.info("Stopping audio recording")
                recording_process.terminate()
                recording_process.wait()
                logging.info("Recording saved to %s", audio_file)

                logging.info("Running speech-to-text")
                try:
                    transcribe_and_type(audio_file, whisper_model, socket_path)
                except Exception as exc:
                    logging.error("Speech-to-text failed: %s", exc)
                finally:
                    recording_process = None

    except KeyboardInterrupt:  # pragma: no cover - manual interrupt
        logging.info("Received Ctrl+C, shutting down")
    except Exception as exc:  # pragma: no cover - catch-all for journald diagnostics
        logging.exception("Unhandled error in key listener: %s", exc)
    finally:
        if recording_process:
            recording_process.terminate()
            recording_process.wait(timeout=1)


if __name__ == "__main__":
    main()
