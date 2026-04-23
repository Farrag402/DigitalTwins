"""
OpenAI ASR transcription utilities.

Supports both the transcription API (gpt-4o-transcribe, gpt-4o-mini-transcribe)
and the chat completions audio API (gpt-4o-audio-preview).
"""

import base64
import os
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

from .audio_converter import get_audio_bytes

DEFAULT_MODEL = "gpt-4o-transcribe"

# Used only by the chat completions path (gpt-4o-audio-preview)
SYSTEM_PROMPT = (
    "You are a verbatim transcription engine. "
    "Your ONLY job is to output the exact words spoken in the audio, word for word. "
    "Do NOT summarize, paraphrase, compress, correct, or translate anything. "
    "Do NOT add any introduction, explanation, heading, or commentary. "
    "Output ONLY the raw spoken text, nothing else."
)

DEFAULT_PROMPT = (
    "The speaker uses Egyptian Arabic dialect mixed with English (code-switching). "
    "Preserve the dialect faithfully — do NOT convert to Modern Standard Arabic. "
    "Keep all English words and phrases exactly as the speaker says them."
    "Do not translate or modify the text in any way. Output the transcription verbatim, exactly as spoken."
)

# Models that use client.audio.transcriptions.create() instead of chat completions
_TRANSCRIPTION_API_MODELS = {"gpt-4o-transcribe", "gpt-4o-mini-transcribe", "gpt-4o-mini-transcribe-2025-12-15"}

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


def _transcribe_via_transcription_api(
    client: OpenAI,
    audio_path: Path,
    prompt: str,
    model: str,
) -> str:
    """Use client.audio.transcriptions.create() for gpt-4o-transcribe family."""
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model=model,
            file=f,
            prompt=prompt,
            response_format="json",
        )
    return response.text.strip()


def _transcribe_via_chat_completions(
    client: OpenAI,
    audio_path: Path,
    prompt: str,
    system_prompt: str,
    model: str,
) -> str:
    """Use client.chat.completions.create() for gpt-4o-audio-preview."""
    wav_bytes = get_audio_bytes(audio_path, output_format="wav", sample_rate=16000, mono=True)
    audio_b64 = base64.b64encode(wav_bytes).decode()

    response = client.chat.completions.create(
        model=model,
        modalities=["text"],
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
                    {"type": "text", "text": prompt},
                ],
            },
        ],
    )
    return response.choices[0].message.content.strip()


def transcribe_audio(
    audio_path: Path,
    prompt: str = DEFAULT_PROMPT,
    system_prompt: str = SYSTEM_PROMPT,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    retries: int = 3,
    delay_between_retries: int = 60,
) -> str:
    """
    Transcribe an audio file using OpenAI's audio model.

    Routes to the transcription API for gpt-4o-transcribe / gpt-4o-mini-transcribe,
    or to chat completions for gpt-4o-audio-preview.

    Args:
        audio_path: Path to input audio file
        prompt: Dialect/style hint passed to the model
        system_prompt: Verbatim-transcription directive (chat completions path only)
        api_key: OpenAI API key (falls back to OPENAI_API_KEY env var)
        model: OpenAI model ID (default gpt-4o-transcribe)
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
    use_transcription_api = model in _TRANSCRIPTION_API_MODELS

    for attempt in range(retries):
        try:
            if use_transcription_api:
                return _transcribe_via_transcription_api(client, audio_path, prompt, model)
            else:
                return _transcribe_via_chat_completions(client, audio_path, prompt, system_prompt, model)

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
