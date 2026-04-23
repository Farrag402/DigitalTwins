"""
Forced alignment utilities using Qwen3ForcedAligner.

Given an audio file and its transcript, returns word-level timestamps.
"""

import json
from pathlib import Path
from typing import Optional

import torch
from qwen_asr import Qwen3ForcedAligner

DEFAULT_MODEL = "Qwen/Qwen3-ForcedAligner-0.6B"
DEFAULT_LANGUAGE = "Arabic"

_model: Optional[Qwen3ForcedAligner] = None
_model_device: Optional[str] = None


def _load_model(model_name: str = DEFAULT_MODEL, device: Optional[str] = None) -> Qwen3ForcedAligner:
    """Load the aligner model on the given device."""
    if device is None:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    return Qwen3ForcedAligner.from_pretrained(
        model_name,
        dtype=torch.bfloat16,
        device_map=device,
    )


def _get_model(model_name: str = DEFAULT_MODEL) -> Qwen3ForcedAligner:
    """Get or create the aligner model, loading it once and reusing it."""
    global _model, _model_device

    if _model is None:
        _model_device = "cuda:0" if torch.cuda.is_available() else "cpu"
        print(f"  Loading aligner model on {_model_device}...")
        _model = _load_model(model_name, _model_device)

    return _model


def align_audio(
    audio_path: Path,
    text: str,
    language: str = DEFAULT_LANGUAGE,
) -> list[dict]:
    """
    Align a transcript to an audio file and return word-level timestamps.

    Args:
        audio_path: Path to the audio file (WAV recommended)
        text: Transcript text to align
        language: Language of the audio (default "Arabic")

    Returns:
        List of dicts with keys: word, start, end, duration (all times in seconds)

    Raises:
        FileNotFoundError: If the audio file does not exist
    """
    global _model, _model_device

    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    model = _get_model()

    try:
        results = model.align(
            audio=str(audio_path),
            text=text,
            language=language,
        )
    except torch.cuda.OutOfMemoryError:
        print("  CUDA out of memory — reloading model on CPU and retrying...")
        _model = None
        torch.cuda.empty_cache()
        _model_device = "cpu"
        _model = _load_model(device="cpu")
        results = _model.align(
            audio=str(audio_path),
            text=text,
            language=language,
        )

    raw = [
        {"word": item.text, "start": float(item.start_time), "end": float(item.end_time)}
        for item in results[0].items
    ]

    # Forward-fill start timestamps for words the model couldn't align
    # (model context exhaustion causes end <= start for later words).
    # This keeps every word in the transcript while still giving the rechunker
    # usable cut points for the words that were aligned correctly.
    last_valid_end = 0.0
    for w in raw:
        if w["end"] > w["start"]:
            last_valid_end = w["end"]
        else:
            # Collapse to a zero-duration point just after the last valid word
            w["start"] = last_valid_end
            w["end"] = last_valid_end

    words = [
        {
            "word": w["word"],
            "start": round(w["start"], 3),
            "end": round(w["end"], 3),
            "duration": round(w["end"] - w["start"], 3),
        }
        for w in raw
    ]

    return words


def align_and_save(
    audio_path: Path,
    text: str,
    output_path: Optional[Path] = None,
    language: str = DEFAULT_LANGUAGE,
) -> tuple[list[dict], Path]:
    """
    Align a transcript to an audio file and save the result as JSON.

    Useful for caching alignment results so the model doesn't need to re-run
    if the pipeline is interrupted and resumed.

    Args:
        audio_path: Path to the audio file (WAV recommended)
        text: Transcript text to align
        output_path: Path for the output JSON file (default: same name as audio with _alignment.json)
        language: Language of the audio (default "Arabic")

    Returns:
        Tuple of (word list, output file path)
    """
    audio_path = Path(audio_path)

    if output_path is None:
        output_path = audio_path.with_name(audio_path.stem + "_alignment.json")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    words = align_audio(audio_path, text, language=language)

    payload = {
        "source_file": audio_path.name,
        "transcript": text,
        "num_words": len(words),
        "words": words,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return words, output_path
