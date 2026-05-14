"""
Normalize transcription labels for Stage 3 export (transcriptions.csv).
"""

from __future__ import annotations

import re

_BRACKET = re.compile(r"\[[^\]]+\]")
# laugh, laughing, laughs, laughter
_LAUGH = re.compile(r"laugh(s|ing|ter)?|laughter", re.IGNORECASE)
# uhm, uhmm, ummmm, umm, hmm, etc.
_UHM = re.compile(r"u+h*m+|u+m+|h+m+", re.IGNORECASE)


def _canonical_bracket(inner: str) -> str | None:
    s = inner.strip()
    if not s:
        return None
    if _LAUGH.fullmatch(s):
        return "[laughing]"
    if _UHM.fullmatch(s):
        return "[Uhm]"
    return None


def normalize_label(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)

    def repl(m: re.Match[str]) -> str:
        inner = m.group(0)[1:-1]
        canon = _canonical_bracket(inner)
        return canon if canon is not None else m.group(0)

    text = _BRACKET.sub(repl, text)
    return text.rstrip(".")
