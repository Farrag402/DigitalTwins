import os
import csv
import subprocess
import base64
import time
from pathlib import Path
from tqdm import tqdm
import google.generativeai as genai
import imageio_ffmpeg

# ── CONFIG ───────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
INPUT_DIR  = ROOT / "Dataset" / "Unprocessed"
OUTPUT_CSV = ROOT / "Dataset" / "transcriptions.csv"

MODEL_ID   = "gemini-1.5-flash"

GEMINI_API_KEY = ""

# Customize this to match your speaker's style and topic
PROMPT = (
    "Transcribe this audio exactly as spoken. "
    "The speaker uses Egyptian Arabic dialect mixed with English (code-switching). "
    "Preserve the dialect faithfully — do NOT convert to Modern Standard Arabic. "
    "Keep any English words or phrases in English as the speaker says them. "
    "Output only the transcription text, nothing else."
)

DELAY_BETWEEN_REQUESTS = 4  # seconds — free tier allows 15 RPM

if not GEMINI_API_KEY:
    raise EnvironmentError("Set your Gemini API key in GEMINI_API_KEY env var or paste it directly in the script.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(MODEL_ID)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def get_wav_bytes(path: Path) -> bytes:
    """Convert any audio/video file to 16kHz mono WAV bytes via ffmpeg."""
    result = subprocess.run(
        [
            FFMPEG, "-y",
            "-i", str(path),
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            "-loglevel", "error",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    if not result.stdout:
        raise ValueError(f"ffmpeg produced empty output for: {path.name}")
    return result.stdout


def transcribe(path: Path, retries: int = 3) -> str:
    wav_bytes  = get_wav_bytes(path)
    audio_part = {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(wav_bytes).decode()}}
    for attempt in range(retries):
        try:
            response = model.generate_content([audio_part, PROMPT])
            return response.text.strip()
        except Exception as e:
            if "429" in str(e) and attempt < retries - 1:
                wait = 60 * (attempt + 1)
                tqdm.write(f"  Rate limited — waiting {wait}s before retry {attempt + 1}/{retries - 1}...")
                time.sleep(wait)
            else:
                raise


audio_files = sorted(Path(INPUT_DIR).glob("*.mkv"))

if not audio_files:
    raise FileNotFoundError(f"No MKV files found in: {INPUT_DIR}")

print(f"Model  : {MODEL_ID}")
print(f"Clips  : {len(audio_files)}\n")

rows = []
for path in tqdm(audio_files, desc="Transcribing"):
    try:
        text = transcribe(path)
    except Exception as e:
        text = f"[ERROR: {e}]"

    rows.append({"filename": path.name, "transcription": text})
    tqdm.write(f"  {path.name}\n  → {text}\n")

    time.sleep(DELAY_BETWEEN_REQUESTS)

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["filename", "transcription"])
    writer.writeheader()
    writer.writerows(rows)

print(f"Saved {len(rows)} transcriptions → {OUTPUT_CSV}")
