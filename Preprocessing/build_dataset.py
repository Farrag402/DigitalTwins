import csv
import json
import random
import wave
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent.parent
CSV_PATH     = ROOT / "Dataset" / "transcriptions.csv"
WAV_DIR      = ROOT / "Dataset" / "Denoised"
OUTPUT_JSONL = ROOT / "Dataset" / "dataset.jsonl"

# Paths written into the JSONL are relative to the project root, which is
# where you should launch training from.
RELATIVE_TO = ROOT

# Fraction of samples that will have a ref_audio field (VoxCPM docs recommend
# 30–50% to balance zero-shot and voice-cloning abilities).
REF_AUDIO_FRACTION = 0.40

SEED = 42
# ─────────────────────────────────────────────────────────────────────────────


def get_duration(wav_path: Path) -> float | None:
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return round(wf.getnframes() / wf.getframerate(), 3)
    except Exception:
        return None


def build():
    random.seed(SEED)

    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found: {CSV_PATH}")

    rows = []
    skipped_unreviewed = 0
    skipped_no_wav     = 0

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("reviewed", "").lower() != "true":
                skipped_unreviewed += 1
                continue

            stem     = Path(row["filename"]).stem
            wav_path = WAV_DIR / (stem + ".wav")

            if not wav_path.exists():
                skipped_no_wav += 1
                print(f"  [WARN] WAV not found, skipping: {wav_path.name}")
                continue

            record = {
                "audio": str(wav_path.relative_to(RELATIVE_TO)).replace("\\", "/"),
                "text":  row["transcription"],
            }

            duration = get_duration(wav_path)
            if duration is not None:
                record["duration"] = duration

            rows.append(record)

    # Assign ref_audio to a random subset (REF_AUDIO_FRACTION of samples).
    # Each sample gets a ref pointing to a *different* clip from the same speaker.
    if len(rows) > 1:
        n_ref = round(len(rows) * REF_AUDIO_FRACTION)
        ref_indices = set(random.sample(range(len(rows)), n_ref))
        audio_paths = [r["audio"] for r in rows]
        for i in ref_indices:
            candidates = [p for j, p in enumerate(audio_paths) if j != i]
            rows[i]["ref_audio"] = random.choice(candidates)

    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for record in rows:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    n_ref_written = sum(1 for r in rows if "ref_audio" in r)
    print(f"\nWrote {len(rows)} records → {OUTPUT_JSONL}")
    print(f"  {n_ref_written} samples include ref_audio ({n_ref_written/len(rows):.0%})" if rows else "")
    if skipped_unreviewed:
        print(f"  Skipped {skipped_unreviewed} unreviewed row(s).")
    if skipped_no_wav:
        print(f"  Skipped {skipped_no_wav} row(s) with missing WAV.")


if __name__ == "__main__":
    build()
