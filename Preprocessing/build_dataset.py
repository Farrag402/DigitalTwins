"""
Build a single VoxCPM 2–style JSONL dataset from all speakers under
Preprocessing/output/.

Each run overwrites Dataset/dataset.jsonl and recreates Dataset/audio/
(copies WAVs as clip_0.wav, clip_1.wav, … globally unique names).

Paths in the manifest are relative to the project root (parent of Preprocessing/).
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import wave
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = ROOT / "Preprocessing" / "output"
DATASET_DIR = ROOT / "Dataset"
AUDIO_DIR = DATASET_DIR / "audio"
OUTPUT_JSONL = DATASET_DIR / "dataset.jsonl"

SEED = 42
# ─────────────────────────────────────────────────────────────────────────────


def get_duration(wav_path: Path) -> float | None:
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return round(wf.getnframes() / wf.getframerate(), 3)
    except Exception:
        return None


def discover_speaker_dirs() -> list[Path]:
    """Immediate subdirs of Preprocessing/output that have transcriptions.csv and clips/."""
    if not OUTPUT_ROOT.is_dir():
        return []

    speakers: list[Path] = []
    for p in sorted(OUTPUT_ROOT.iterdir()):
        if not p.is_dir():
            continue
        has_csv = (p / "transcriptions.csv").is_file()
        has_clips = (p / "clips").is_dir()
        if has_csv and has_clips:
            speakers.append(p)
        elif has_csv or has_clips:
            print(
                f"  [WARN] Skipping {p.name}: need both transcriptions.csv and clips/ subfolder."
            )
    return speakers


def ask_ref_fraction(speaker_name: str) -> float:
    """Prompt until a float in [0, 1] is entered (no default)."""
    while True:
        raw = input(
            f'Enter ref_audio fraction for "{speaker_name}" '
            "(0.0 = none, 1.0 = all) [0.0-1.0]: "
        ).strip()
        try:
            x = float(raw)
        except ValueError:
            print("  Invalid: enter a number between 0.0 and 1.0.")
            continue
        if x < 0.0 or x > 1.0:
            print("  Invalid: must be between 0.0 and 1.0.")
            continue
        return x


def prepare_audio_dir() -> None:
    if AUDIO_DIR.exists():
        shutil.rmtree(AUDIO_DIR)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)


def build() -> None:
    random.seed(SEED)

    speaker_dirs = discover_speaker_dirs()
    if not speaker_dirs:
        raise FileNotFoundError(
            f"No speaker folders with transcriptions.csv + clips/ under {OUTPUT_ROOT}"
        )

    prepare_audio_dir()

    all_rows: list[dict] = []
    skipped_no_wav = 0
    duration_outside_3_30 = 0
    clip_index = 0

    for speaker_dir in speaker_dirs:
        speaker_name = speaker_dir.name
        fraction = ask_ref_fraction(speaker_name)

        if fraction < 0.3 or fraction > 0.5:
            print(
                "  [note] VoxCPM 2 docs recommend ref_audio on about 30–50% of samples "
                "for a good zero-shot vs voice-cloning balance."
            )

        speaker_records: list[dict] = []
        csv_path = speaker_dir / "transcriptions.csv"

        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                filename = row.get("filename", "").strip()
                text = row.get("transcription", "") or ""
                if not filename:
                    continue

                src_wav = speaker_dir / "clips" / filename
                if not src_wav.is_file():
                    skipped_no_wav += 1
                    print(f"  [WARN] WAV not found, skipping: {speaker_name}/clips/{filename}")
                    continue

                dst_wav = AUDIO_DIR / f"clip_{clip_index}.wav"
                shutil.copy2(src_wav, dst_wav)
                clip_index += 1

                rel_audio = str(dst_wav.relative_to(ROOT)).replace("\\", "/")
                record: dict = {"audio": rel_audio, "text": text}

                duration = get_duration(dst_wav)
                if duration is not None:
                    record["duration"] = duration
                    if duration < 3.0 or duration > 30.0:
                        duration_outside_3_30 += 1

                speaker_records.append(record)

        n = len(speaker_records)
        if fraction > 0.0 and n < 2:
            if n == 0:
                print(
                    f'  [WARN] Speaker "{speaker_name}": no clips copied from CSV; '
                    "skipping ref_audio."
                )
            else:
                print(
                    f'  [WARN] Speaker "{speaker_name}": need at least 2 clips to assign ref_audio; '
                    "skipping ref_audio for this speaker."
                )
        elif fraction > 0.0 and n >= 2:
            k = round(n * fraction)
            k = max(0, min(k, n))
            if k > 0:
                audio_paths = [r["audio"] for r in speaker_records]
                ref_indices = random.sample(range(n), k)
                for i in ref_indices:
                    candidates = [p for j, p in enumerate(audio_paths) if j != i]
                    speaker_records[i]["ref_audio"] = random.choice(candidates)

        all_rows.extend(speaker_records)

    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for record in all_rows:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    n_ref = sum(1 for r in all_rows if "ref_audio" in r)
    print(f"\nWrote {len(all_rows)} record(s) → {OUTPUT_JSONL}")
    if all_rows:
        print(f"  {n_ref} sample(s) include ref_audio ({n_ref / len(all_rows):.0%})")
    if skipped_no_wav:
        print(f"  Skipped {skipped_no_wav} row(s) with missing source WAV.")
    if duration_outside_3_30:
        print(
            f"  [note] {duration_outside_3_30} clip(s) have duration outside the 3–30 s "
            "sweet spot suggested in the VoxCPM 2 fine-tuning guide."
        )


if __name__ == "__main__":
    build()
