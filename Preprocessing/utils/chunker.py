"""
Audio chunking utilities using ffmpeg.
"""

import subprocess
from pathlib import Path
from typing import Literal

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def chunk_audio(
    input_path: Path,
    output_dir: Path,
    chunk_duration_seconds: int = 240,
    output_format: Literal["mp3", "wav"] = "mp3",
    sample_rate: int = 16000,
    mono: bool = True,
    prefix: str = "chunk",
) -> list[Path]:
    """
    Split an audio file into fixed-duration chunks.

    Args:
        input_path: Path to input audio file
        output_dir: Directory to save chunks
        chunk_duration_seconds: Duration of each chunk in seconds (default 240 = 4 minutes)
        output_format: Output format - "mp3" or "wav"
        sample_rate: Output sample rate in Hz (default 16000)
        mono: If True, convert to mono (default True)
        prefix: Prefix for chunk filenames (default "chunk")

    Returns:
        List of paths to the created chunk files, sorted by name

    Raises:
        FileNotFoundError: If input file doesn't exist
        subprocess.CalledProcessError: If ffmpeg fails
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = output_dir / f"{prefix}_%03d.{output_format}"

    cmd = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-f", "segment",
        "-segment_time", str(chunk_duration_seconds),
        "-ar", str(sample_rate),
    ]

    if mono:
        cmd.extend(["-ac", "1"])

    if output_format == "mp3":
        cmd.extend(["-codec:a", "libmp3lame", "-q:a", "2"])
    elif output_format == "wav":
        cmd.extend(["-codec:a", "pcm_s16le"])

    cmd.extend(["-loglevel", "error", str(output_pattern)])

    subprocess.run(cmd, check=True, capture_output=True)

    chunks = sorted(output_dir.glob(f"{prefix}_*.{output_format}"))

    return chunks


def get_audio_duration(input_path: Path) -> float:
    """
    Get the duration of an audio file in seconds.

    Args:
        input_path: Path to audio file

    Returns:
        Duration in seconds

    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If duration cannot be determined
    """
    input_path = Path(input_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    cmd = [
        FFMPEG,
        "-i", str(input_path),
        "-f", "null",
        "-"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    for line in result.stderr.split("\n"):
        if "Duration:" in line:
            time_str = line.split("Duration:")[1].split(",")[0].strip()
            parts = time_str.split(":")
            hours, minutes, seconds = float(parts[0]), float(parts[1]), float(parts[2])
            return hours * 3600 + minutes * 60 + seconds

    raise ValueError(f"Could not determine duration for: {input_path}")
