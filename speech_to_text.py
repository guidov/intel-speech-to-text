#!/usr/bin/env python3
from __future__ import annotations

"""Transcribe recorded audio with Faster Whisper and type it using ydotool."""

import logging
import os
import shutil
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
    import numpy as np
    import soundfile as sf
    from faster_whisper import WhisperModel
except ImportError as exc:  # pragma: no cover - dependency issue
    raise SystemExit(
        "Required Python packages are missing. Install dependencies with pip install -r requirements.txt"
    ) from exc


def setup_logging() -> None:
    """Configure logging to stdout and optional file."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = getattr(config, "SPEECH_TO_TEXT_LOG_FILE", None)
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_path))
        except (OSError, PermissionError):
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=handlers,
    )


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


def load_audio(file_path: Path) -> tuple[np.ndarray, int]:
    """Load audio file into a numpy array."""
    if not file_path.exists():
        logging.error("Audio file not found: %s", file_path)
        raise SystemExit(1)

    audio, samplerate = sf.read(file_path)
    audio = audio.astype("float32")

    if len(audio.shape) > 1 and audio.shape[1] > 1:
        audio = np.mean(audio, axis=1)
        logging.info("Converted stereo audio to mono")

    logging.info("Audio loaded: %s (sample rate %s)", file_path, samplerate)
    return audio, samplerate


def create_model() -> WhisperModel:
    """Instantiate a Faster Whisper model based on the configuration."""
    model_size = getattr(config, "WHISPER_MODEL_SIZE", "small")
    compute_type = getattr(config, "WHISPER_COMPUTE_TYPE", "int8")
    logging.info("Loading Whisper model '%s' (%s)", model_size, compute_type)
    return WhisperModel(model_size, device="cpu", compute_type=compute_type)


def transcribe(audio: np.ndarray, model: WhisperModel):
    """Run transcription and yield recognised text segments."""
    segments, info = model.transcribe(
        audio,
        beam_size=1,
        vad_filter=False,
    )

    logging.info(
        "Detected language: %s (probability %.2f)",
        info.language,
        info.language_probability,
    )

    for segment in segments:
        text = segment.text.strip()
        if text:
            logging.info("Recognised: %s", text)
            yield text


def type_text(text: str, socket_path: Path) -> None:
    """Send text to the active window using ydotool."""
    if shutil.which("ydotool") is None:
        logging.error("ydotool not found. Install the ydotool package.")
        raise SystemExit(1)

    if not socket_path.exists():
        logging.error("ydotool socket missing: %s", socket_path)
        logging.error("Ensure ydotoold.service is running and created the socket.")
        raise SystemExit(1)

    env = os.environ.copy()
    env["YDOTOOL_SOCKET"] = str(socket_path)

    subprocess.run(["ydotool", "type", text + " "], env=env, check=True)
    logging.info("Typed text successfully")


def main() -> None:
    setup_logging()

    if len(sys.argv) < 2:
        print("Usage: speech_to_text.py <audio_file>")
        raise SystemExit(1)

    audio_path = Path(sys.argv[1])
    audio, samplerate = load_audio(audio_path)

    # Ensure the recorded audio uses the expected sample rate.
    target_rate = getattr(config, "SAMPLE_RATE_HZ", samplerate)
    if samplerate != target_rate:
        logging.warning("Audio sample rate %s does not match configured %s", samplerate, target_rate)

    model = create_model()
    socket_path = resolve_socket_path()

    try:
        for text in transcribe(audio, model):
            type_text(text, socket_path)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - ydotool failure
        logging.error("ydotool returned non-zero exit status: %s", exc)
        raise SystemExit(1)

    logging.info("Processing completed")


if __name__ == "__main__":
    main()
