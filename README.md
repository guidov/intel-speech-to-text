# Offline Speech-to-Text for Intel XPU (Wayland)

This is a fork of [omarchy-speech-to-text](https://github.com/michabbb/omarchy-speech-to-text) with Intel XPU optimization

This project reproduces the hands-free dictation setup used on Linux with a Wayland compositor. A dedicated key listener records audio while you hold a hotkey and forwards the audio to OpenAI Whisper installed locally. Once transcription finishes, the recognised text is typed into the focused window via [`ydotool`](https://github.com/ReimuNotMoe/ydotool).

The repository contains ready-to-use Python scripts, configuration templates, and systemd unit files so you can replicate the complete workflow on your own machine.

The nice thing about this framework is that it allows input into any application on the system (because it uses root). While this may have security issues, this would not be possible otherwise.

---

## Features

- **Hold-to-talk workflow** – press and hold a configurable key (e.g., Right Ctrl) to record; release to transcribe and type the text.
- **Wayland-compatible typing** – uses `ydotool` instead of `xdotool`, so it works on Sway, Hyprland, GNOME, KDE, etc.
- **Offline Intel XPU-accelerated transcription** – powered by OpenAI Whisper running locally with Intel Extension for PyTorch (IPEX) optimizations for Intel GPUs.
- **Dynamic keyboard detection** – includes helper script for automatic keyboard device discovery.
- **Systemd integration** – both the key listener and `ydotoold` daemon are managed as services and start automatically after boot.

---

## Repository Layout

```
.
├── config.example.py        # Template with all tunable settings
├── key_listener.py          # Root hotkey listener (records audio, launches STT)
├── detect_keyboard.py       # Helper script for keyboard device detection
├── requirements.txt         # Python dependencies
├── intel-speech-to-text        # Whisper transcription + ydotool typing
├── systemd/
│   ├── intel-speech-to-text.service  # Service for key_listener.py
│   └── ydotoold.service                 # ydotool daemon with boot sequencing fix
└── LICENSE
```

Copy `config.example.py` to `config.py` and adjust it for your environment before starting the services.

---

## Prerequisites (Arch Linux)

1. **Audio & input utilities**
   ```bash
   sudo pacman -S alsa-utils python-evdev
   ```
2. **Wayland automation tools**
   ```bash
   sudo pacman -S ydotool
   ```
   > `ydotool` lives in the `community` repository. If you are using another distribution, install it from your package manager or build from source.
3. **Optional key remapping** – if you plan to trigger dictation with a mouse button or unusual key, install a remapper such as `input-remapper` or Sway/Hyprland keybinds.
4. **Python 3.10+** – required for the virtual environment.

## Prerequisites (Ubuntu)

1. **Audio & input utilities**
   ```bash
   sudo apt update
   sudo apt install alsa-utils python3-evdev
   ```
2. **Wayland automation tools**
   ```bash
   sudo apt install ydotool
   ```
3. **Optional key remapping** – if you plan to trigger dictation with a mouse button or unusual key, install a remapper such as `input-remapper`.
4. **Python 3.10+** – required for the virtual environment.

> **Intel XPU acceleration:** Intel Arc GPUs, integrated graphics (iGPU), and other Intel XPU hardware are supported with Intel Extension for PyTorch (IPEX) for significant performance improvements. The system will automatically detect available Intel XPU hardware at runtime and apply optimizations. You can configure the behavior using the `WHISPER_DEVICE` setting in `config.py`:
> - `auto` (default): automatically detect and use XPU if available, otherwise CPU
> - `cpu`: force CPU usage (may be faster for small models)
> - `xpu`: force Intel XPU usage (will fail if not available)

---

## Installation

### 1. Configure Python environment

```bash
python -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
```

The default `requirements.txt` includes Intel XPU optimizations with Intel Extension for PyTorch (IPEX):
- `torch` - PyTorch with Intel XPU support
- `intel-extension-for-pytorch` - Intel optimizations for PyTorch
- `openai-whisper` - CPU/GPU accelerated Whisper implementation

### 2. Prepare `config.py`

```bash
cp config.example.py config.py
```

Edit `config.py` and review every option:

- `TARGET_USER` – the desktop user that owns the Wayland session (receives typed text).
- `DEVICE_PATH` – the `/dev/input/event*` device that should trigger recording. The application now includes dynamic device detection that will automatically find your keyboard device at runtime if the configured path doesn't exist, but you can still use `sudo evtest` to discover the correct device and key codes.
- `TRIGGER_KEYCODE` – the key code reported by `evtest` while you press the hotkey (default: `KEY_RIGHTCTRL`).
- `AUDIO_FILE` – temporary WAV file location (default `/tmp/recorded_audio.wav`).
- `PYTHON_VENV` & `SPEECH_TO_TEXT_SCRIPT` – paths to the interpreter and transcription script. Defaults assume the project lives in `/opt/speech-to-text`.
- `WHISPER_MODEL_SIZE` / `WHISPER_COMPUTE_TYPE` – pick another model (e.g. `tiny`, `medium`) or precision if desired.
- `WHISPER_DEVICE` – set to `auto`, `cpu`, or `xpu`. When `auto`, will detect and use Intel XPU if available, otherwise CPU. When `xpu`, will force Intel XPU usage (will fail if not available).
- `YDOTOOL_SOCKET` – matches the socket path created by the systemd unit (`/run/user/<uid>/.ydotool_socket`).

For dynamic device detection, you can optionally run the helper script to identify your keyboard:
```bash
sudo python detect_keyboard.py
```
This script will scan for input devices and identify keyboard devices with the trigger key.

### 3. Install systemd units

Copy the service files and adjust them for your UID/GID and project path.

```bash
sudo install -m 0644 systemd/ydotoold.service /etc/systemd/system/ydotoold.service
sudo install -m 0644 systemd/intel-speech-to-text.service /etc/systemd/system/intel-speech-to-text.service
```

Edit `/etc/systemd/system/ydotoold.service`:

- Replace every occurrence of `1000` with your user’s numeric UID and GID (see `id -u`, `id -g`).
- Update the socket path if you changed it in `config.py`.

Edit `/etc/systemd/system/intel-speech-to-text.service`:

- Update `WorkingDirectory` and `ExecStart` so they match the absolute project path and Python interpreter inside your virtual environment.

Reload systemd and enable the services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ydotoold.service
sudo systemctl enable --now intel-speech-to-text.service
```

### 4. Verify services

- Ensure `ydotoold` created the socket:
  ```bash
  ls -l /run/user/<uid>/.ydotool_socket
  ```
- Monitor logs:
  ```bash
  journalctl -u ydotoold.service -b
  journalctl -u intel-speech-to-text.service -b
  ```

The key listener should log that it is watching `KEY_RIGHTCTRL` (or whichever key you configure) and transitions through recording and transcription when you test it.

---

## How It Works

```
┌──────────────────────────┐
│ key_listener.py (root)   │
│  • watches DEVICE_PATH   │
│  • starts/stops arecord  │
│  • calls speech_to_text  │
└────────────┬─────────────┘
             │ WAV file
             ▼
┌──────────────────────────┐
│ intel-speech-to-text (root) │
│  • loads OpenAI Whisper  │
│  • transcribes segments  │
│  • uses ydotool type     │
└────────────┬─────────────┘
             │ text events via ydotool
             ▼
      Active application
```

Key points:

- `key_listener.py` must run as root to read `/dev/input` and to interact with `sudo -u <user> arecord`. The actual audio capture happens as the unprivileged desktop user, so PulseAudio/PipeWire routing behaves normally.
- `intel-speech-to-text` runs as root but inherits the user’s runtime environment (`XDG_RUNTIME_DIR`, Wayland display) so `ydotool` can access the compositor socket. The service fixes a boot timing race by ensuring the user runtime directory exists before `ydotoold` starts.
- **Intel XPU Acceleration**: The system automatically detects available Intel XPU hardware and applies Intel Extension for PyTorch (IPEX) optimizations for maximum transcription speed.
- **Dynamic Keyboard Detection**: The system automatically detects keyboard devices at runtime if the configured path doesn't exist.

---

## Testing Without systemd

You can run everything manually before enabling the units:

```bash
sudo ./venv/bin/python key_listener.py
```

Then hold the configured hotkey. You should see logs similar to:

```
INFO: Starting audio recording
INFO: Recording started with PID ...
INFO: Stopping audio recording
INFO: Running speech-to-text
INFO: Recognised: ...
INFO: Typed text successfully
```

If typing fails, check that `ydotoold` is running and the socket path matches `config.py`.

---

## Troubleshooting

- **`Error: [Errno 19] No such device`** – `DEVICE_PATH` in `config.py` is wrong or the device id changes between boots. The application now includes dynamic device detection that will automatically find your keyboard device at runtime if the configured path doesn't exist. If automatic detection fails, you can manually run `sudo evtest` or use the helper script `python detect_keyboard.py` to find your keyboard device and update the path.
- **`failed to connect socket '/run/user/1000/.ydotool_socket'`** – `ydotoold` did not start or the runtime directory was re-created after boot. Confirm the service uses the modified unit provided here.
- **`arecord` command fails** – install `alsa-utils` and confirm the microphone works (`arecord -f S16_LE -r 16000 test.wav`).
- **Whisper model loads slowly** – larger models can take several seconds. Consider the `tiny` or `base` model for faster start.
- **Typing lag** – `ydotool` sends events sequentially. If performance is an issue, experiment with the `ydotool type --delay` flag by modifying `intel-speech-to-text`.

---

## Model Cache Management

Whisper models are downloaded once and cached locally in `~/.cache/whisper`.
- **Model files**: Each model is a `.pt` file (e.g., `medium.en.pt`, `small.en.pt`)
- **Storage**: Models range from ~73MB (tiny) to ~1.5GB (medium/large)

To free up disk space:
```bash
# List cached models and their sizes
ls -lh ~/.cache/whisper/

# Delete specific model
rm ~/.cache/whisper/medium.en.pt

# Delete all cached models
rm -rf ~/.cache/whisper/
```

Models will be re-downloaded automatically when needed.

---

## Security Notes

- Both services run as root. Restrict access to the repository directory and review the scripts before installing on production machines.
- `key_listener.py` invokes `sudo -u <TARGET_USER> arecord ...`. Ensure the root account can run `sudo` without prompting (the default for root).
- The scripts type whatever Whisper recognises. Consider adding keyword filtering if you plan to use it in sensitive contexts.

---

## License & Credits

Distributed under the MIT License (see `LICENSE`). The original idea and much of the inspiration comes from [CDNsun’s “Speech-to-Text for Ubuntu” article](https://blog.cdnsun.com/speech-to-text-for-ubuntu/); this repository adapts that work for Systemd Linux + Wayland with additional boot-order fixes.
