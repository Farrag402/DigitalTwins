"""
Audio format conversion utilities using ffmpeg.
"""

import subprocess
from pathlib import Path
from typing import Literal, Optional
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

SUPPORTED_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".flv", ".webm",
    ".m4a", ".mp3", ".ogg", ".flac", ".wav", ".aac"
}


def _timestamp_to_seconds(ts: str) -> float:
    """
    Convert a timestamp string to seconds.

    Accepts:
        "3600"        → 3600.0  (plain seconds)
        "1:00:00"     → 3600.0  (HH:MM:SS)
        "30:00"       → 1800.0  (MM:SS)
        "1:30:00.5"   → 5400.5  (with sub-second)
    """
    parts = ts.strip().split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    raise ValueError(f"Cannot parse timestamp: '{ts}'. Use HH:MM:SS, MM:SS, or plain seconds.")


def convert_audio(
    input_path: Path,
    output_path: Path,
    output_format: Literal["mp3", "wav"] = "mp3",
    sample_rate: int = 16000,
    mono: bool = True,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Path:
    """
    Convert any audio/video file to mp3 or wav format, with optional time cropping.

    Args:
        input_path: Path to input audio/video file
        output_path: Path for output file (extension will be enforced)
        output_format: Target format - "mp3" or "wav"
        sample_rate: Output sample rate in Hz (default 16000)
        mono: If True, convert to mono (default True)
        start: Start timestamp to crop from, e.g. "1:30:00" or "90" (default: beginning)
        end: End timestamp to crop to, e.g. "2:00:00" or "120" (default: end of file)

    Returns:
        Path to the converted file

    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If input format is not supported or timestamps are invalid
        subprocess.CalledProcessError: If ffmpeg conversion fails
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported input format: {input_path.suffix}. "
            f"Supported: {SUPPORTED_EXTENSIONS}"
        )

    if start and end:
        start_secs = _timestamp_to_seconds(start)
        end_secs   = _timestamp_to_seconds(end)
        if end_secs <= start_secs:
            raise ValueError(f"end ({end}) must be after start ({start})")

    output_path = output_path.with_suffix(f".{output_format}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [FFMPEG, "-y"]

    # Place -ss before -i for fast input seeking on long files
    if start:
        cmd.extend(["-ss", start])

    cmd.extend(["-i", str(input_path)])

    # Use -t (duration) rather than -to so it works correctly with input seeking
    if end:
        start_secs = _timestamp_to_seconds(start) if start else 0.0
        end_secs   = _timestamp_to_seconds(end)
        cmd.extend(["-t", str(end_secs - start_secs)])

    cmd.extend(["-ar", str(sample_rate)])

    if mono:
        cmd.extend(["-ac", "1"])

    if output_format == "mp3":
        cmd.extend(["-codec:a", "libmp3lame", "-q:a", "2"])
    elif output_format == "wav":
        cmd.extend(["-f", "wav"])

    cmd.extend(["-loglevel", "error", str(output_path)])

    subprocess.run(cmd, check=True, capture_output=True)

    return output_path


def get_audio_bytes(
    input_path: Path,
    output_format: Literal["mp3", "wav"] = "wav",
    sample_rate: int = 16000,
    mono: bool = True,
) -> bytes:
    """
    Convert any audio/video file to bytes in the specified format.

    Args:
        input_path: Path to input audio/video file
        output_format: Target format - "mp3" or "wav"
        sample_rate: Output sample rate in Hz (default 16000)
        mono: If True, convert to mono (default True)

    Returns:
        Audio data as bytes

    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If ffmpeg produces empty output
    """
    input_path = Path(input_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    cmd = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-ar", str(sample_rate),
    ]

    if mono:
        cmd.extend(["-ac", "1"])

    if output_format == "mp3":
        cmd.extend(["-codec:a", "libmp3lame", "-q:a", "2", "-f", "mp3"])
    elif output_format == "wav":
        cmd.extend(["-f", "wav"])

    cmd.extend(["-loglevel", "error", "pipe:1"])

    result = subprocess.run(cmd, capture_output=True, check=True)

    if not result.stdout:
        raise ValueError(f"ffmpeg produced empty output for: {input_path.name}")

    return result.stdout
