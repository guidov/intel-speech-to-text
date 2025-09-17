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
except ImportError as exc:  # pragma: no cover - dependency issue
    raise SystemExit(
        "The evdev package is required. Install dependencies with pip install -r requirements.txt"
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


def main() -> None:
    """Listen for the configured key events and orchestrate recording."""
    setup_logging()

    if os.geteuid() != 0:
        logging.error("key_listener.py must be executed as root (use systemd or sudo)")
        raise SystemExit(1)

    user_info = resolve_user(config.TARGET_USER)
    env = build_environment(user_info)

    device_path = str(config.DEVICE_PATH)
    audio_file = Path(config.AUDIO_FILE)
    audio_file.parent.mkdir(parents=True, exist_ok=True)

    python_bin = Path(config.PYTHON_VENV)
    speech_script = Path(config.SPEECH_TO_TEXT_SCRIPT)

    try:
        device = InputDevice(device_path)
    except FileNotFoundError as exc:
        logging.error("Input device %s not found. Adjust DEVICE_PATH in config.py", device_path)
        raise SystemExit(1) from exc
    except PermissionError as exc:
        logging.error("Permission denied opening %s. Run as root or adjust ACLs.", device_path)
        raise SystemExit(1) from exc

    trigger_key = getattr(config, "TRIGGER_KEYCODE", "KEY_RIGHTCTRL")
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
                    subprocess.run(
                        [str(python_bin), str(speech_script), str(audio_file)],
                        env=env,
                        check=True,
                    )
                except subprocess.CalledProcessError as exc:
                    logging.error("Speech-to-text script failed: %s", exc)
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
