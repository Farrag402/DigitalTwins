"""
Audio processing pipeline.

Takes an audio file, enhances it, chunks it into WAV segments,
transcribes each chunk, and saves transcriptions alongside the audio.

Output structure:
    output_dir/
    ├── chunk_000.wav
    ├── chunk_000.txt
    ├── chunk_001.wav
    ├── chunk_001.txt
    └── ...

Usage:
    python pipeline.py input.mp3 output_dir/
    python pipeline.py input.mp3 output_dir/ --chunk-duration 180
    python pipeline.py input.mp3 output_dir/ --no-enhance
"""

import argparse
import tempfile
from pathlib import Path
from typing import Optional
import os
from tqdm import tqdm
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent / ".env")

from utils.audio_converter import convert_audio
from utils.chunker import chunk_audio
from utils.enhancer import enhance_audio, init_enhancer_model
from utils.transcriber import transcribe_and_save, DEFAULT_PROMPT


def process_audio(
    input_audio: Path,
    output_dir: Path,
    chunk_duration_seconds: int = 240,
    enhance: bool = True,
    api_key: Optional[str] = None,
    prompt: str = DEFAULT_PROMPT,
) -> dict[Path, str]:
    """
    Process an audio file through the full pipeline.

    Pipeline steps:
    1. Convert input to WAV (if needed)
    2. Enhance audio with noisereducer (optional)
    3. Chunk into N-minute WAV segments (saved to output_dir)
    4. Transcribe each chunk and save .txt files
    5. forcedaligner chunks
    6. chunk based on words
    7. human in the loop validation

    Args:
        input_audio: Path to input audio file (any format)
        output_dir: Directory to save chunks and transcriptions
        chunk_duration_seconds: Duration of each chunk in seconds (default 240 = 4 minutes)
        enhance: Whether to apply DeepFilterNet enhancement (default True)
        api_key: OpenAI API key (falls back to OPENAI_API_KEY env var)
        prompt: Transcription prompt/instructions

    Returns:
        Dictionary mapping chunk paths to their transcriptions
    """
    input_audio = Path(input_audio)
    output_dir = Path(output_dir)

    if not input_audio.exists():
        raise FileNotFoundError(f"Input file not found: {input_audio}")

    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[Path, str] = {}

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        print(f"[1/4] Converting to WAV...")
        wav_path = temp_path / "input.wav"
        convert_audio(input_audio, wav_path, output_format="wav", sample_rate=16000, mono=True)
        print(f"      → {wav_path.name}")

        if enhance:
            print(f"[2/4] Enhancing with DeepFilterNet...")
            model = init_enhancer_model()
            enhanced_path = temp_path / "enhanced.wav"
            enhance_audio(wav_path, enhanced_path, model=model)
            audio_to_chunk = enhanced_path
            print(f"      → {enhanced_path.name}")
        else:
            print(f"[2/4] Skipping enhancement (--no-enhance)")
            audio_to_chunk = wav_path

        print(f"[3/4] Chunking into {chunk_duration_seconds}s segments...")
        wav_chunks = chunk_audio(
            audio_to_chunk,
            output_dir,
            chunk_duration_seconds=chunk_duration_seconds,
            output_format="wav",
            sample_rate=16000,
            mono=True,
        )
        print(f"      → {len(wav_chunks)} chunks created")

        print(f"[4/4] Transcribing chunks...")
        for wav_chunk in tqdm(wav_chunks, desc="      Transcribing"):
            text, txt_path = transcribe_and_save(
                wav_chunk,
                output_path=wav_chunk.with_suffix(".txt"),
                prompt=prompt,
                api_key=api_key,
            )
            results[wav_chunk] = text

    print(f"\nDone! Output saved to: {output_dir}")
    print(f"  {len(results)} chunk(s) processed")

    return results


def main():
    print(os.environ.get("OPENAI_API_KEY") != None)
    process_audio(
    input_audio=Path("C:/Users/shels/Documents/voice cloning/dl_lec.mp3"),
    output_dir=Path("Alla_output"),
    chunk_duration_seconds= 290,
    enhance=True,
    api_key=os.getenv("OPENAI_API_KEY"),
    prompt=DEFAULT_PROMPT,
    )


if __name__ == "__main__":
    main()
