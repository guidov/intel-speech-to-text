"""Configuration template for the Arch Linux speech-to-text stack.

Copy this file to ``config.py`` and adjust the values for your system.
"""

from pathlib import Path

# Root directory of the project (resolved dynamically in the scripts as well).
PROJECT_ROOT = Path(__file__).resolve().parent

# Linux user that owns the graphical session and should receive typed text.
TARGET_USER = "micha"

# evdev input device path that triggers recording. Use ``sudo evtest`` to find it.
DEVICE_PATH = "/dev/input/event4"

# Key code (from ``evtest``) that triggers recording. Default: Right Ctrl.
TRIGGER_KEYCODE = "KEY_RIGHTCTRL"

# Location where recorded audio is stored temporarily.
AUDIO_FILE = Path("/tmp/recorded_audio.wav")

# Path to the Python interpreter inside your virtual environment.
PYTHON_VENV = PROJECT_ROOT / "venv" / "bin" / "python3"

# Script that performs speech-to-text. Paths can be absolute or relative to PROJECT_ROOT.
SPEECH_TO_TEXT_SCRIPT = PROJECT_ROOT / "speech_to_text.py"

# Audio capture settings for ``arecord``.
SAMPLE_RATE_HZ = 16_000
CHANNELS = 1
SAMPLE_FORMAT = "S16_LE"

# Display / compositor values. Leave WAYLAND_DISPLAY to ``None`` to auto-detect.
DISPLAY = ":0"
WAYLAND_DISPLAY = None  # e.g. "wayland-0" if you want to pin it explicitly.

# Faster-Whisper model selection.
WHISPER_MODEL_SIZE = "small"
WHISPER_COMPUTE_TYPE = "int8"

# Optional log file overrides. Leave as ``None`` to log only to stderr.
KEY_LISTENER_LOG_FILE = Path("/tmp/key_listener.log")
SPEECH_TO_TEXT_LOG_FILE = Path("/tmp/speech_to_text_root.log")

# ydotool socket path. Matches the systemd unit in ``systemd/ydotoold.service``.
YDOTOOL_SOCKET = Path("/run/user/1000/.ydotool_socket")
