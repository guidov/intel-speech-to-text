#!/usr/bin/env python3
from __future__ import annotations

"""Transcribe recorded audio with OpenAI Whisper and type it using ydotool."""

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
    import whisper
    import torch
    import intel_extension_for_pytorch as ipex
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


def create_model() -> whisper.Whisper:
    """Instantiate a Whisper model based on the configuration."""
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
    
    logging.info("Loading Whisper model '%s' on device '%s'", model_size, device)
    model = whisper.load_model(model_size, device=device)
    
    # Apply IPEX optimizations for inference on XPU
    if device == "xpu":
        model.eval()  # Set to evaluation mode for inference
        with torch.no_grad():
            model = ipex.optimize(model, dtype=torch.float32)
        logging.info("IPEX optimizations applied to model")
    
    return model


def transcribe(audio_path: Path, model: whisper.Whisper):
    """Run transcription and yield recognised text segments."""
    result = model.transcribe(str(audio_path))
    text = result["text"].strip()
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

    model = create_model()
    socket_path = resolve_socket_path()

    try:
        for text in transcribe(audio_path, model):
            type_text(text, socket_path)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - ydotool failure
        logging.error("ydotool returned non-zero exit status: %s", exc)
        raise SystemExit(1)

    logging.info("Processing completed")


if __name__ == "__main__":
    main()
