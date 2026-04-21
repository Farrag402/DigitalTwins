"""
Audio enhancement utilities using noisereduce and LUFS normalization.

Dependencies:
    pip install noisereduce pyloudnorm soundfile librosa
"""

import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import soundfile as sf
import pyloudnorm as pyln
import noisereduce as nr
import librosa


def _db_to_linear(db: float) -> float:
    """Convert decibels to linear scale."""
    return 10 ** (db / 20)


def init_enhancer_model():
    """
    Initialize the enhancer.

    For noisereduce, no model initialization is needed.
    This function exists for API compatibility with the pipeline.

    Returns:
        None (noisereduce doesn't require pre-loaded models)
    """
    return None


def enhance_audio(
    input_path: Path,
    output_path: Path,
    target_sr: int = 16000,
    target_lufs: float = -23.0,
    peak_ceil_db: float = -1.0,
    model=None,
    prop_decrease: float = 0.8,
    stationary: bool = True,
) -> Path:
    """
    Apply noise reduction and LUFS loudness normalization.

    Uses noisereduce library for spectral gating noise reduction.

    Args:
        input_path: Path to input audio file
        output_path: Path for enhanced output file
        target_sr: Output sample rate in Hz (default 16000)
        target_lufs: Target loudness in LUFS (default -23.0, EBU R128)
        peak_ceil_db: Peak ceiling in dBFS to prevent clipping (default -1.0)
        model: Unused, kept for API compatibility
        prop_decrease: How much to reduce noise (0.0 to 1.0, default 0.8)
        stationary: If True, use stationary noise reduction (default True)

    Returns:
        Path to the enhanced audio file

    Raises:
        FileNotFoundError: If input file doesn't exist
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio, orig_sr = librosa.load(str(input_path), sr=None, mono=True)

    if orig_sr != target_sr:
        audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)

    enhanced = nr.reduce_noise(
        y=audio,
        sr=target_sr,
        prop_decrease=prop_decrease,
        stationary=stationary,
    )

    meter = pyln.Meter(target_sr)
    loudness = meter.integrated_loudness(enhanced)
    if not np.isinf(loudness):
        enhanced = pyln.normalize.loudness(enhanced, loudness, target_lufs)

    peak = np.max(np.abs(enhanced))
    ceiling = _db_to_linear(peak_ceil_db)
    if peak > ceiling:
        enhanced *= ceiling / peak

    sf.write(str(output_path), enhanced, target_sr, subtype="PCM_16")

    return output_path
