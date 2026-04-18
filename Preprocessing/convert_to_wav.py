import subprocess
from pathlib import Path
from tqdm import tqdm
import imageio_ffmpeg

ROOT       = Path(__file__).resolve().parent.parent
INPUT_DIR  = ROOT / "Dataset" / "Unprocessed"
OUTPUT_DIR = ROOT / "Dataset" / "WAV"

SAMPLE_RATE = 16000  # VoxCPM2 AudioVAE encoder input rate (decoder outputs 48kHz at inference)
AUDIO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".flv", ".webm", ".m4a", ".mp3", ".ogg", ".flac"}

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

input_files = sorted(
    p for p in Path(INPUT_DIR).iterdir()
    if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
)

if not input_files:
    raise FileNotFoundError(f"No supported media files found in: {INPUT_DIR}")

print(f"Found {len(input_files)} files. converting to WAV in {OUTPUT_DIR}\n")

errors = []
for path in tqdm(input_files, desc="Converting"):
    out_path = Path(OUTPUT_DIR) / (path.stem + ".wav")

    if out_path.exists():
        continue

    try:
        subprocess.run(
            [
                FFMPEG,
                "-i", str(path),
                "-ar", str(SAMPLE_RATE),
                "-ac", "1",
                "-loglevel", "error",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        errors.append((path.name, e.stderr.decode().strip()))

print(f"\nDone. {len(input_files) - len(errors)}/{len(input_files)} converted successfully.")

if errors:
    print("\nFailed files:")
    for name, msg in errors:
        print(f"  {name}: {msg}")
