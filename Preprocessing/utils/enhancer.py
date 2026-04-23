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

ROOT         = Path(__file__).resolve().parent.parent.parent
WAV_DIR      = ROOT / "Dataset" / "WAV"
OUT_DIR      = ROOT / "Dataset" / "Denoised"

OUT_SR       = 16_000    # VoxCPM2 AudioVAE encoder input rate
TARGET_LUFS  = -23.0     # EBU R128 broadcast target
PEAK_CEIL_DB = -1.0      # dBFS hard ceiling to prevent clipping


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20)


def init_enhancer_model():
    """Initialise and return the DeepFilterNet model and state.

    Returns:
        tuple: (model, df_state) ready to pass into enhance_audio().
    """
    model, df_state, _ = init_df()
    return model, df_state


def enhance_audio(
    wav_path: str | Path,
    out_path: str | Path,
    model=None,
    df_state=None,
    out_sr: int = OUT_SR,
    target_lufs: float = TARGET_LUFS,
    peak_ceil_db: float = PEAK_CEIL_DB,
) -> Path:
    """Denoise and loudness-normalise a single WAV file.

    Args:
        wav_path:     Path to the input WAV file.
        out_path:     Destination path for the enhanced WAV.
        model:        Pre-loaded DF model (created by init_enhancer_model()).
                      If None a fresh model is loaded for this call.
        df_state:     Matching DF state object.
        out_sr:       Output sample rate in Hz (default 16 000).
        target_lufs:  Integrated loudness target in LUFS (default -23).
        peak_ceil_db: Hard peak ceiling in dBFS (default -1).

    Returns:
        Path: Resolved path to the saved output file.
    """
    if model is None or df_state is None:
        model, df_state = init_enhancer_model()

    df_sr = df_state.sr()

    audio, _ = load_audio(str(wav_path), sr=df_sr)
    enhanced = enhance(model, df_state, audio)

    if df_sr != out_sr:
        import torchaudio
        enhanced = torchaudio.functional.resample(enhanced, df_sr, out_sr)

    audio_np = enhanced.squeeze().numpy()

    meter    = pyln.Meter(out_sr)
    loudness = meter.integrated_loudness(audio_np)
    if not np.isinf(loudness):
        audio_np = pyln.normalize.loudness(audio_np, loudness, target_lufs)

    peak    = np.max(np.abs(audio_np))
    ceiling = db_to_linear(peak_ceil_db)
    if peak > ceiling:
        audio_np *= ceiling / peak

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio_np, out_sr, subtype="PCM_16")
    return out_path


def main():
    model, df_state = init_enhancer_model()
    df_sr = df_state.sr()

    wav_files = sorted(WAV_DIR.glob("*.wav"))
    if not wav_files:
        raise FileNotFoundError(f"No WAV files found in: {WAV_DIR}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Enhancing {len(wav_files)} file(s)  "
          f"[DF internal={df_sr} Hz → saved at {OUT_SR} Hz → {OUT_DIR}]\n")

    for wav_path in tqdm(wav_files, desc="Enhance"):
        enhance_audio(wav_path, OUT_DIR / wav_path.name, model=model, df_state=df_state)

    print("\nDone.")


if __name__ == "__main__":
    main()
