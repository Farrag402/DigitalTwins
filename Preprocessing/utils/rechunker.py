"""
Re-chunking utilities.

Given an audio chunk and its word-level alignment (from forced_aligner),
splits the chunk into sentence/phrase-level clips at natural boundaries:
  - Silence gaps between consecutive words exceeding gap_threshold
  - Sentence-ending punctuation attached to a word

Trailing fragments at the end of a chunk that have no natural break point
are discarded.
"""

import csv
import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

SENTENCE_END_CHARS = set(".!?؟،")


def _classify_break(
    word: str, gap_to_next: float, gap_threshold: float
) -> tuple[bool, str]:
    """
    Return (is_break_point, cut_reason_label) for a word.

    cut_reason_label is only meaningful when is_break_point is True.
    """
    stripped = word.rstrip()
    has_punctuation = bool(stripped) and stripped[-1] in SENTENCE_END_CHARS
    has_gap = gap_to_next > gap_threshold

    if has_punctuation and has_gap:
        reason = f"punctuation + silence ({gap_to_next:.2f}s)"
    elif has_punctuation:
        reason = "punctuation"
    elif has_gap:
        reason = f"silence ({gap_to_next:.2f}s)"
    else:
        reason = ""

    return (has_punctuation or has_gap), reason


def rechunk(
    chunk_path: Path,
    alignment_words: list[dict],
    output_dir: Path,
    chunk_index: int,
    min_duration: float = 3.0,
    max_duration: float = 30.0,
    gap_threshold: float = 0.3,
) -> list[tuple[Path, str, str]]:
    """
    Split a chunk into sentence-level clips using word-level alignment.

    Break points are detected at silence gaps (> gap_threshold seconds) and
    sentence-ending punctuation. A segment is finalized only when a break
    point is reached AND the accumulated duration >= min_duration, or when
    max_duration is exceeded (force-break).

    Trailing words at the end of the chunk that do not end on a natural break
    point are discarded.

    Args:
        chunk_path: Path to the chunk audio file
        alignment_words: Word-level alignment from forced_aligner.align_audio()
        output_dir: Directory to save output clips
        chunk_index: Index of this chunk (used for clip naming)
        min_duration: Minimum clip duration in seconds (default 3.0)
        max_duration: Maximum clip duration in seconds (default 30.0)
        gap_threshold: Silence gap in seconds to treat as a break point (default 0.3)

    Returns:
        List of (clip_path, transcript_text, cut_reason) tuples for every finalized clip.
        cut_reason describes what triggered the cut that ended this clip.
    """
    if not alignment_words:
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Each entry: (start, end, words, cut_reason)
    segments: list[tuple[float, float, list[dict], str]] = []
    current_words: list[dict] = []
    current_start: float = alignment_words[0]["start"]

    for i, word in enumerate(alignment_words):
        current_words.append(word)
        current_duration = word["end"] - current_start
        is_last = i == len(alignment_words) - 1

        gap_to_next = alignment_words[i + 1]["start"] - word["end"] if not is_last else 0.0
        break_point, bp_reason = _classify_break(word["word"], gap_to_next, gap_threshold)
        force_break = current_duration >= max_duration

        if force_break or (break_point and current_duration >= min_duration):
            reason = "max duration" if force_break else bp_reason
            segments.append((current_start, word["end"], list(current_words), reason))
            current_words = []
            if not is_last:
                current_start = alignment_words[i + 1]["start"]
        # Trailing words with no natural break are implicitly discarded
        # (current_words is non-empty but never appended to segments)

    results: list[tuple[Path, str, str]] = []
    for clip_idx, (start, end, words, cut_reason) in enumerate(segments):
        clip_name = f"chunk{chunk_index:03d}_clip{clip_idx:02d}.wav"
        clip_path = output_dir / clip_name
        transcript = " ".join(w["word"] for w in words)
        _slice_audio(chunk_path, clip_path, start, end)
        results.append((clip_path, transcript, cut_reason))

    return results


def _slice_audio(input_path: Path, output_path: Path, start: float, end: float) -> None:
    """Slice a time range from an audio file and write as 16 kHz mono WAV."""
    cmd = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-ss", str(start),
        "-to", str(end),
        "-ar", "16000",
        "-ac", "1",
        "-codec:a", "pcm_s16le",
        "-loglevel", "error",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def save_review_csv(
    items: list[tuple[Path, str]] | list[tuple[Path, str, str]],
    csv_path: Path,
) -> None:
    """
    Write review rows to a CSV with an empty status column.

    Accepts either 2-tuples (path, transcript) or 3-tuples
    (path, transcript, cut_reason). When cut_reason is present a
    cut_reason column is added so the review tool can display it.

    Always creates a fresh file. The review tool fills in the status column
    (accepted / rejected) during human review.
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    has_reason = items and len(items[0]) == 3
    fieldnames = ["filename", "transcription", "status"]
    if has_reason:
        fieldnames.append("cut_reason")

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for row in items:
            item_path, transcript = row[0], row[1]
            cut_reason = row[2] if has_reason else ""  # type: ignore[index]
            base = [Path(item_path).name, transcript, ""]
            if has_reason:
                base.append(cut_reason)
            writer.writerow(base)


def read_accepted(csv_path: Path) -> list[tuple[str, str]]:
    """
    Read a review CSV and return (filename, transcription) pairs for rows
    whose status column equals "accepted".

    Args:
        csv_path: Path to a review CSV produced by save_review_csv

    Returns:
        List of (filename, transcription) tuples
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return []

    accepted: list[tuple[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status", "").lower() == "accepted":
                accepted.append((row["filename"], row.get("transcription", "")))
    return accepted


def save_final_csv(items: list[tuple[str, str]], csv_path: Path) -> None:
    """
    Write the final transcriptions CSV (filename + transcription only).

    All rows passed here are assumed to be accepted — the status column is
    omitted so the file matches the format expected by build_dataset.py and
    the review tool's legacy mode.

    Args:
        items: List of (filename, transcription) tuples
        csv_path: Destination path (overwritten if it exists)
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "transcription"])
        for filename, transcript in items:
            writer.writerow([filename, transcript])
