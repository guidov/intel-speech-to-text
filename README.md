# Offline Speech-to-Text for Arch Linux (Wayland)

> **⚠️ Heads-up**: this project was vibe-coded together with AI helpers (Claude Code and Codex). I am not a Python developer. If you hit issues, please debug with AI or your own expertise, fix them, and send a PR. Treat this repo as a “here’s how it *can* work” manual rather than a guaranteed turnkey solution. It works on my Omarchy (Arch Linux) setup, and I’m sharing the path that got me there.

This project reproduces the hands-free dictation setup used on Arch Linux with a Wayland compositor. A dedicated key listener records audio while you hold a hotkey and forwards the audio to [Faster Whisper](https://github.com/guillaumekln/faster-whisper). Once transcription finishes, the recognised text is typed into the focused window via [`ydotool`](https://github.com/ReimuNotMoe/ydotool).

The repository contains ready-to-use Python scripts, configuration templates, and systemd unit files so you can replicate the complete workflow on your own machine.

---

## Features

- **Hold-to-talk workflow** – press and hold a configurable key (e.g., Right Ctrl) to record; release to transcribe and type the text.
- **Wayland-compatible typing** – uses `ydotool` instead of `xdotool`, so it works on Sway, Hyprland, GNOME, KDE, etc.
- **Offline transcription** – powered by Faster Whisper running locally on CPU (can be upgraded to GPU if desired).
- **Systemd integration** – both the key listener and `ydotoold` daemon are managed as services and start automatically after boot.

---

## Repository Layout

```
.
├── config.example.py        # Template with all tunable settings
├── key_listener.py          # Root hotkey listener (records audio, launches STT)
├── requirements.txt         # Python dependencies
├── speech_to_text.py        # Faster Whisper transcription + ydotool typing
├── systemd/
│   ├── speech-to-text-listener.service  # Service for key_listener.py
│   └── ydotoold.service                  # ydotool daemon with boot sequencing fix
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
4. **Python 3.10+** – required for the virtual environment and Faster Whisper.

> **GPU acceleration (optional):** install CUDA / ROCm drivers and replace the Python dependencies with the GPU build of PyTorch plus `faster-whisper` configured for your accelerator. The README covers CPU-only setup for reliability.

---

## Installation

### 1. Clone the repository

```bash
sudo mkdir -p /opt
sudo chown "$USER" /opt
cd /opt
git clone https://github.com/omarchy/speech-to-text.git
cd speech-to-text
```

Feel free to adjust the target path, but remember to update the systemd unit files accordingly.

### 2. Configure Python environment

```bash
python -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
```

The default `requirements.txt` installs a CPU version of Faster Whisper (`faster-whisper`, `numpy`, `soundfile`, `evdev`).

### 3. Prepare `config.py`

```bash
cp config.example.py config.py
```

Edit `config.py` and review every option:

- `TARGET_USER` – the desktop user that owns the Wayland session (receives typed text).
- `DEVICE_PATH` – the `/dev/input/event*` device that should trigger recording. Use `sudo evtest` to discover the correct device and key codes.
- `TRIGGER_KEYCODE` – the key code reported by `evtest` while you press the hotkey (default: `KEY_RIGHTCTRL`).
- `AUDIO_FILE` – temporary WAV file location (default `/tmp/recorded_audio.wav`).
- `PYTHON_VENV` & `SPEECH_TO_TEXT_SCRIPT` – paths to the interpreter and transcription script. Defaults assume the project lives in `/opt/speech-to-text`.
- `WHISPER_MODEL_SIZE` / `WHISPER_COMPUTE_TYPE` – pick another model (e.g. `tiny`, `medium`) or precision if desired.
- `YDOTOOL_SOCKET` – matches the socket path created by the systemd unit (`/run/user/<uid>/.ydotool_socket`).

### 4. Install systemd units

Copy the service files and adjust them for your UID/GID and project path.

```bash
sudo install -m 0644 systemd/ydotoold.service /etc/systemd/system/ydotoold.service
sudo install -m 0644 systemd/speech-to-text-listener.service /etc/systemd/system/speech-to-text-listener.service
```

Edit `/etc/systemd/system/ydotoold.service`:

- Replace every occurrence of `1000` with your user’s numeric UID and GID (see `id -u`, `id -g`).
- Update the socket path if you changed it in `config.py`.

Edit `/etc/systemd/system/speech-to-text-listener.service`:

- Update `WorkingDirectory` and `ExecStart` so they match the absolute project path and Python interpreter inside your virtual environment.

Reload systemd and enable the services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ydotoold.service
sudo systemctl enable --now speech-to-text-listener.service
```

### 5. Verify services

- Ensure `ydotoold` created the socket:
  ```bash
  ls -l /run/user/<uid>/.ydotool_socket
  ```
- Monitor logs:
  ```bash
  journalctl -u ydotoold.service -b
  journalctl -u speech-to-text-listener.service -b
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
│ speech_to_text.py (root) │
│  • loads Faster Whisper  │
│  • transcribes segments  │
│  • uses ydotool type     │
└────────────┬─────────────┘
             │ text events via ydotool
             ▼
      Active application
```

Key points:

- `key_listener.py` must run as root to read `/dev/input` and to interact with `sudo -u <user> arecord`. The actual audio capture happens as the unprivileged desktop user, so PulseAudio/PipeWire routing behaves normally.
- `speech_to_text.py` runs as root but inherits the user’s runtime environment (`XDG_RUNTIME_DIR`, Wayland display) so `ydotool` can access the compositor socket. The service fixes a boot timing race by ensuring the user runtime directory exists before `ydotoold` starts.

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

- **`Error: [Errno 19] No such device`** – `DEVICE_PATH` in `config.py` is wrong or the device id changes between boots. Re-run `sudo evtest` and update the path.
- **`failed to connect socket '/run/user/1000/.ydotool_socket'`** – `ydotoold` did not start or the runtime directory was re-created after boot. Confirm the service uses the modified unit provided here.
- **`arecord` command fails** – install `alsa-utils` and confirm the microphone works (`arecord -f S16_LE -r 16000 test.wav`).
- **Whisper model loads slowly** – larger models can take several seconds. Consider the `tiny` or `base` model for faster start, or configure GPU acceleration.
- **Typing lag** – `ydotool` sends events sequentially. If performance is an issue, experiment with the `ydotool type --delay` flag by modifying `speech_to_text.py`.

---

## Security Notes

- Both services run as root. Restrict access to the repository directory and review the scripts before installing on production machines.
- `key_listener.py` invokes `sudo -u <TARGET_USER> arecord ...`. Ensure the root account can run `sudo` without prompting (the default for root).
- The scripts type whatever Faster Whisper recognises. Consider adding keyword filtering if you plan to use it in sensitive contexts.

---

## Extending / Customising

- Change the trigger key by editing the `KEY_RIGHTCTRL` check in `key_listener.py` or remap your preferred key/button to Right Ctrl using `input-remapper` or compositor keybinds.
- To support multiple hotkeys or languages, extend `speech_to_text.py` to pick models dynamically or to send the text to other applications (e.g., copy to clipboard instead of typing).
- GPU users can install `torch` + `faster-whisper` with `device="cuda"` in `speech_to_text.py` and adjust `WHISPER_COMPUTE_TYPE` to `float16` for a large speed boost.

---

## License & Credits

Distributed under the MIT License (see `LICENSE`). The original idea and much of the inspiration comes from [CDNsun’s “Speech-to-Text for Ubuntu” article](https://blog.cdnsun.com/speech-to-text-for-ubuntu/); this repository adapts that work for Arch Linux + Wayland with additional boot-order fixes.
