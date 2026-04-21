"""
Audio format conversion utilities using ffmpeg.
"""

import subprocess
from pathlib import Path
from typing import Literal
import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

SUPPORTED_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".flv", ".webm",
    ".m4a", ".mp3", ".ogg", ".flac", ".wav", ".aac"
}


def convert_audio(
    input_path: Path,
    output_path: Path,
    output_format: Literal["mp3", "wav"] = "mp3",
    sample_rate: int = 16000,
    mono: bool = True,
) -> Path:
    """
    Convert any audio/video file to mp3 or wav format.

    Args:
        input_path: Path to input audio/video file
        output_path: Path for output file (extension will be enforced)
        output_format: Target format - "mp3" or "wav"
        sample_rate: Output sample rate in Hz (default 16000)
        mono: If True, convert to mono (default True)

    Returns:
        Path to the converted file

    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If input format is not supported
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

    output_path = output_path.with_suffix(f".{output_format}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-ar", str(sample_rate),
    ]

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
