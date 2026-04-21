"""
OpenAI ASR transcription utilities.

Expects mp3 input files, converts to wav bytes for the API.
"""

import base64
import os
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

from .audio_converter import get_audio_bytes

DEFAULT_MODEL = "gpt-4o-audio-preview"

DEFAULT_PROMPT = (
    "Transcribe this audio exactly as spoken. "
    "The speaker uses Egyptian Arabic dialect mixed with English (code-switching). "
    "Preserve the dialect faithfully — do NOT convert to Modern Standard Arabic. "
    "Keep any English words or phrases in English as the speaker says them. "
)

_client: Optional[OpenAI] = None


def _get_client(api_key: Optional[str] = None) -> OpenAI:
    """Get or create the OpenAI client."""
    global _client

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError(
            "OpenAI API key not provided. Set OPENAI_API_KEY environment variable "
            "or pass api_key parameter."
        )

    if _client is None or api_key is not None:
        _client = OpenAI(api_key=key)

    return _client


def transcribe_audio(
    audio_path: Path,
    prompt: str = DEFAULT_PROMPT,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    retries: int = 3,
    delay_between_retries: int = 60,
) -> str:
    """
    Transcribe an audio file using OpenAI's audio model.

    Accepts mp3 or other audio formats, converts to wav bytes for the API.

    Args:
        audio_path: Path to input audio file (mp3 recommended)
        prompt: Transcription prompt/instructions
        api_key: OpenAI API key (falls back to OPENAI_API_KEY env var)
        model: OpenAI model ID (default gpt-4o-audio-preview)
        retries: Number of retry attempts on rate limiting
        delay_between_retries: Base delay in seconds between retries (multiplied by attempt)

    Returns:
        Transcribed text

    Raises:
        FileNotFoundError: If audio file doesn't exist
        EnvironmentError: If API key not provided
        Exception: If transcription fails after all retries
    """
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    client = _get_client(api_key)

    wav_bytes = get_audio_bytes(audio_path, output_format="wav", sample_rate=16000, mono=True)
    audio_b64 = base64.b64encode(wav_bytes).decode()

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=model,
                modalities=["text"],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": audio_b64, "format": "wav"},
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            if "429" in str(e) and attempt < retries - 1:
                wait = delay_between_retries * (attempt + 1)
                print(f"  Rate limited — waiting {wait}s before retry {attempt + 1}/{retries - 1}...")
                time.sleep(wait)
            else:
                raise


def transcribe_and_save(
    audio_path: Path,
    output_path: Optional[Path] = None,
    prompt: str = DEFAULT_PROMPT,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
) -> tuple[str, Path]:
    """
    Transcribe an audio file and save the transcription to a text file.

    Args:
        audio_path: Path to input audio file
        output_path: Path for output text file (default: same name as audio with .txt)
        prompt: Transcription prompt/instructions
        api_key: OpenAI API key (falls back to OPENAI_API_KEY env var)
        model: OpenAI model ID

    Returns:
        Tuple of (transcription text, output file path)
    """
    audio_path = Path(audio_path)

    if output_path is None:
        output_path = audio_path.with_suffix(".txt")
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = transcribe_audio(audio_path, prompt=prompt, api_key=api_key, model=model)

    output_path.write_text(text, encoding="utf-8")

    return text, output_path
