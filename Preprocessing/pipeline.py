"""
Audio processing pipeline — three stages with human review between each.

Stages
------
Stage 1  Convert → Enhance → Chunk → Transcribe
         Writes: output_dir/chunks/chunks_review.csv
         Next:   review chunks with review_tool.py, mark each as accepted/rejected

Stage 2  Forced-align → Re-chunk  (accepted chunks only)
         Writes: output_dir/clips/clips_review.csv
         Next:   review clips with review_tool.py, mark each as accepted/rejected

Stage 3  Save final CSV  (accepted clips only)
         Writes: output_dir/transcriptions.csv

Usage
-----
    python pipeline.py 1 output_dir/ input.mp3 [--chunk-duration 240] [--no-enhance]
    python pipeline.py 1 output/hanan/ ../input/hanan.mp4 --start 00:10:57 --end 00:56:10 --no-enhance
    python pipeline.py 2 output_dir/
    python pipeline.py 3 output_dir/
"""

import argparse
import os
import tempfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv(Path(__file__).resolve().parent / ".env")

from utils.audio_converter import convert_audio
from utils.chunker import chunk_audio
from utils.enhancer import enhance_audio, init_enhancer_model
from utils.transcriber import transcribe_and_save, DEFAULT_PROMPT
from utils.forced_aligner import align_and_save
from utils.rechunker import rechunk, save_review_csv, read_accepted, save_final_csv

from normalize_labels import normalize_label


# ── Stage 1 ───────────────────────────────────────────────────────────────────

def run_stage1(
    input_audio: Path,
    output_dir: Path,
    chunk_duration_seconds: int = 240,
    enhance: bool = True,
    api_key: Optional[str] = None,
    prompt: str = DEFAULT_PROMPT,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Path:
    """
    Convert, enhance, chunk, and transcribe an audio file.

    Args:
        input_audio: Path to input audio file (any format)
        output_dir: Root output directory for this session
        chunk_duration_seconds: Duration of each intermediate chunk (default 240 = 4 min)
        enhance: Whether to apply DeepFilterNet + LUFS normalization (default True)
        api_key: OpenAI API key (falls back to OPENAI_API_KEY env var)
        prompt: Transcription prompt
        start: Crop start timestamp, e.g. "1:30:00" or "90" (default: beginning of file)
        end: Crop end timestamp, e.g. "2:00:00" or "120" (default: end of file)

    Returns:
        Path to the written chunks_review.csv
    """
    input_audio = Path(input_audio)
    output_dir  = Path(output_dir)

    if not input_audio.exists():
        raise FileNotFoundError(f"Input file not found: {input_audio}")

    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        crop_info = f"  (crop: {start or 'start'} → {end or 'end'})" if start or end else ""
        print(f"[1/4] Converting to WAV...{crop_info}")
        wav_path = tmp_path / "input.wav"
        convert_audio(
            input_audio, wav_path,
            output_format="wav", sample_rate=16000, mono=True,
            start=start, end=end,
        )
        print(f"      → {wav_path.name}")

        if enhance:
            print("[2/4] Enhancing with DeepFilterNet...")
            model = init_enhancer_model()
            enhanced_path = tmp_path / "enhanced.wav"
            enhance_audio(wav_path, enhanced_path, model=model)
            audio_to_chunk = enhanced_path
            print(f"      → {enhanced_path.name}")
        else:
            print("[2/4] Skipping enhancement (--no-enhance)")
            audio_to_chunk = wav_path

        print(f"[3/4] Chunking into {chunk_duration_seconds}s segments...")
        wav_chunks = chunk_audio(
            audio_to_chunk,
            chunks_dir,
            chunk_duration_seconds=chunk_duration_seconds,
            output_format="wav",
            sample_rate=16000,
            mono=True,
        )
        print(f"      → {len(wav_chunks)} chunks  →  {chunks_dir}")

    print("[4/4] Transcribing chunks...")
    chunk_items: list[tuple[Path, str]] = []
    for wav_chunk in tqdm(wav_chunks, desc="      Transcribing"):
        text, _ = transcribe_and_save(
            wav_chunk,
            output_path=wav_chunk.with_suffix(".txt"),
            prompt=prompt,
            api_key=api_key,
        )
        chunk_items.append((wav_chunk, text))

    csv_path = chunks_dir / "chunks_review.csv"
    save_review_csv(chunk_items, csv_path)

    print(f"\nStage 1 complete. {len(chunk_items)} chunk(s) written to {chunks_dir}")
    print(f"\nNext step: review chunks then run Stage 2")
    print(f"  python review_tool.py --csv \"{csv_path}\" --audio-dir \"{chunks_dir}\" --title \"Chunk Review\"")
    print(f"  python pipeline.py 2 \"{output_dir}\"")

    return csv_path


# ── Stage 2 ───────────────────────────────────────────────────────────────────

def run_stage2(
    output_dir: Path,
    min_clip_duration: float = 10.0,
    max_clip_duration: float = 30.0,
    gap_threshold: float = 0.3,
) -> Path:
    """
    Run forced alignment and re-chunking on accepted chunks from Stage 1.

    Args:
        output_dir: Root output directory (same one passed to Stage 1)
        min_clip_duration: Minimum clip duration in seconds (default 10.0)
        max_clip_duration: Maximum clip duration in seconds (default 30.0)
        gap_threshold: Silence gap in seconds that triggers a cut (default 0.3)

    Returns:
        Path to the written clips_review.csv
    """
    output_dir = Path(output_dir)
    chunks_dir = output_dir / "chunks"
    clips_dir  = output_dir / "clips"

    csv_path = chunks_dir / "chunks_review.csv"
    accepted = read_accepted(csv_path)

    if not accepted:
        raise RuntimeError(
            f"No accepted chunks found in {csv_path}.\n"
            "Open the review tool, mark chunks as accepted, then re-run Stage 2."
        )

    clips_dir.mkdir(parents=True, exist_ok=True)

    print(f"[5/6] Forcing alignment on {len(accepted)} accepted chunk(s)...")
    chunk_alignments: list[tuple[str, list[dict]]] = []
    for filename, transcript in tqdm(accepted, desc="      Aligning"):
        chunk_path = chunks_dir / filename
        words, _ = align_and_save(
            chunk_path,
            text=transcript,
            output_path=chunk_path.with_name(chunk_path.stem + "_alignment.json"),
        )
        chunk_alignments.append((filename, words))

    print("[6/6] Re-chunking at sentence boundaries...")
    all_clips: list[tuple[Path, str, str]] = []
    for chunk_index, (filename, words) in enumerate(tqdm(chunk_alignments, desc="      Re-chunking")):
        # Preserve original chunk number in clip names for traceability
        try:
            original_index = int(Path(filename).stem.split("_")[-1])
        except (ValueError, IndexError):
            original_index = chunk_index

        clips = rechunk(
            chunk_path=chunks_dir / filename,
            alignment_words=words,
            output_dir=clips_dir,
            chunk_index=original_index,
            min_duration=min_clip_duration,
            max_duration=max_clip_duration,
            gap_threshold=gap_threshold,
        )
        all_clips.extend(clips)

    clips_csv = clips_dir / "clips_review.csv"
    save_review_csv(all_clips, clips_csv)

    print(f"\nStage 2 complete. {len(all_clips)} clip(s) written to {clips_dir}")
    print(f"\nNext step: review clips then run Stage 3")
    print(f"  python review_tool.py --csv \"{clips_csv}\" --audio-dir \"{clips_dir}\" --title \"Clip Review\"")
    print(f"  python pipeline.py 3 \"{output_dir}\"")

    return clips_csv


# ── Stage 3 ───────────────────────────────────────────────────────────────────

def run_stage3(output_dir: Path) -> Path:
    """
    Collect accepted clips from Stage 2 and write the final transcriptions CSV.

    Args:
        output_dir: Root output directory (same one passed to Stages 1 and 2)

    Returns:
        Path to the written transcriptions.csv
    """
    output_dir = Path(output_dir)
    clips_csv  = output_dir / "clips" / "clips_review.csv"

    accepted = read_accepted(clips_csv)

    if not accepted:
        raise RuntimeError(
            f"No accepted clips found in {clips_csv}.\n"
            "Open the review tool, mark clips as accepted, then re-run Stage 3."
        )

    normalized: list[tuple[str, str]] = []
    for fn, tx in accepted:
        ntx = normalize_label(tx)
        if ntx != tx:
            print(f"  {fn}:\n    {tx!r}\n    -> {ntx!r}")
        normalized.append((fn, ntx))
    accepted = normalized

    final_csv = output_dir / "transcriptions.csv"
    save_final_csv(accepted, final_csv)

    print(f"\nStage 3 complete. {len(accepted)} clip(s) saved to {final_csv}")
    print("Ready for build_dataset.py")

    return final_csv


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Audio preprocessing pipeline (run stages 1 → 2 → 3 with review in between)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("stage", type=int, choices=[1, 2, 3], help="Pipeline stage to run")
    parser.add_argument("output_dir", type=Path, help="Session output directory")
    parser.add_argument("input_audio", nargs="?", type=Path, help="Input audio file (Stage 1 only)")
    parser.add_argument("--chunk-duration", type=int, default=40, metavar="SECONDS",
                        help="Chunk duration in seconds for Stage 1 (default: 40)")
    parser.add_argument("--no-enhance", action="store_true",
                        help="Skip DeepFilterNet enhancement in Stage 1")
    parser.add_argument("--start", default=None, metavar="TIMESTAMP",
                        help="Crop start time for Stage 1, e.g. '1:30:00' or '5400' (default: beginning)")
    parser.add_argument("--end", default=None, metavar="TIMESTAMP",
                        help="Crop end time for Stage 1, e.g. '2:00:00' or '7200' (default: end of file)")
    parser.add_argument("--api-key", default=None,
                        help="OpenAI API key (default: OPENAI_API_KEY env var)")
    parser.add_argument("--min-clip", type=float, default=5.0, metavar="SECONDS",
                        help="Minimum clip duration for Stage 2 (default: 5.0)")
    parser.add_argument("--max-clip", type=float, default=30.0, metavar="SECONDS",
                        help="Maximum clip duration for Stage 2 (default: 30.0)")
    parser.add_argument("--gap-threshold", type=float, default=1.5, metavar="SECONDS",
                        help="Silence gap that triggers a re-chunk boundary for Stage 2 (default: 0.3)")

    args = parser.parse_args()

    if args.stage == 1:
        if args.input_audio is None:
            parser.error("Stage 1 requires an input_audio argument")
        run_stage1(
            input_audio=args.input_audio,
            output_dir=args.output_dir,
            chunk_duration_seconds=args.chunk_duration,
            enhance=not args.no_enhance,
            api_key=args.api_key or os.getenv("OPENAI_API_KEY"),
            prompt=DEFAULT_PROMPT,
            start=args.start,
            end=args.end,
        )

    elif args.stage == 2:
        run_stage2(
            output_dir=args.output_dir,
            min_clip_duration=args.min_clip,
            max_clip_duration=args.max_clip,
            gap_threshold=args.gap_threshold,
        )

    elif args.stage == 3:
        run_stage3(output_dir=args.output_dir)


if __name__ == "__main__":
    main()
