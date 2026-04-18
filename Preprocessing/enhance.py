"""
Preprocessing/enhance.py

Applies DeepFilterNet speech enhancement + LUFS loudness normalisation
to all WAVs in Dataset/WAV/, in-place.

Install dependencies first:
    pip install deepfilternet pyloudnorm soundfile torchaudio
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from pathlib import Path
from tqdm import tqdm
from df.enhance import enhance, init_df, load_audio

ROOT         = Path(__file__).resolve().parent.parent
WAV_DIR      = ROOT / "Dataset" / "WAV"
OUT_DIR      = ROOT / "Dataset" / "Denoised"

OUT_SR       = 16_000    # VoxCPM2 AudioVAE encoder input rate
TARGET_LUFS  = -23.0     # EBU R128 broadcast target
PEAK_CEIL_DB = -1.0      # dBFS hard ceiling to prevent clipping


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20)


def main():
    model, df_state, _ = init_df()
    df_sr = df_state.sr()  # DF3 operates at 48 kHz internally

    wav_files = sorted(WAV_DIR.glob("*.wav"))
    if not wav_files:
        raise FileNotFoundError(f"No WAV files found in: {WAV_DIR}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Enhancing {len(wav_files)} file(s)  "
          f"[DF internal={df_sr} Hz → saved at {OUT_SR} Hz → {OUT_DIR}]\n")

    for wav_path in tqdm(wav_files, desc="Enhance"):

        # ── 1. Load at DeepFilterNet's native rate (handles upsampling) ──────
        audio, _ = load_audio(str(wav_path), sr=df_sr)   # shape: [1, T]

        # ── 2. Denoise ────────────────────────────────────────────────────────
        enhanced = enhance(model, df_state, audio)        # shape: [1, T]

        # ── 3. Resample back to 16 kHz ────────────────────────────────────────
        if df_sr != OUT_SR:
            import torchaudio
            enhanced = torchaudio.functional.resample(enhanced, df_sr, OUT_SR)

        audio_np = enhanced.squeeze().numpy()             # shape: [T]

        # ── 4. LUFS loudness normalisation ────────────────────────────────────
        meter    = pyln.Meter(OUT_SR)
        loudness = meter.integrated_loudness(audio_np)
        if not np.isinf(loudness):                        # very short clips → -inf
            audio_np = pyln.normalize.loudness(audio_np, loudness, TARGET_LUFS)

        # ── 5. Peak limiting ──────────────────────────────────────────────────
        peak    = np.max(np.abs(audio_np))
        ceiling = db_to_linear(PEAK_CEIL_DB)
        if peak > ceiling:
            audio_np *= ceiling / peak

        # ── 6. Save to Dataset/Denoised/ at 16 kHz, 16-bit PCM ──────────────
        sf.write(str(OUT_DIR / wav_path.name), audio_np, OUT_SR, subtype="PCM_16")

    print("\nDone.")


if __name__ == "__main__":
    main()
