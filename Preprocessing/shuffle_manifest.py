"""
Shuffle a JSONL manifest in-place (or write to a different output path).

Default target:
    Dataset/dataset.jsonl

Usage:
    python shuffle_manifest.py
    python shuffle_manifest.py --seed 42
    python shuffle_manifest.py --input "../Dataset/dataset.jsonl" --output "../Dataset/dataset.shuffled.jsonl"
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "Dataset" / "dataset.jsonl"


def shuffle_manifest(input_path: Path, output_path: Path, seed: int | None = None) -> int:
    if not input_path.exists():
        raise FileNotFoundError(f"Manifest not found: {input_path}")

    lines = [ln for ln in input_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    rng = random.Random(seed)
    rng.shuffle(lines)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Shuffle JSONL manifest line order.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Input JSONL path (default: Dataset/dataset.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSONL path (default: same as --input, in-place shuffle)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible shuffling.",
    )
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else (Path.cwd() / args.input).resolve()
    output_path = args.output if args.output else input_path
    if not output_path.is_absolute():
        output_path = (Path.cwd() / output_path).resolve()

    count = shuffle_manifest(input_path=input_path, output_path=output_path, seed=args.seed)
    mode = "in-place" if output_path == input_path else "copy"
    print(f"Shuffled {count} JSONL entries ({mode})")
    print(f"  input : {input_path}")
    print(f"  output: {output_path}")
    if args.seed is not None:
        print(f"  seed  : {args.seed}")


if __name__ == "__main__":
    main()

