"""Text normalisation used by the matching rules.

Only the four operations the project agreed on, applied to title, artist and album
alike: full/half width, whitespace, case, and traditional/simplified Chinese.

Deliberately *not* included: stripping "feat."/"Live"/"Remix" markers, punctuation
mapping, fuzzy containment. Those change meaning, and the rule is "must be equal".
"""
from __future__ import annotations

import re
import unicodedata

try:  # optional at import time so the tool still runs without the dependency
    import zhconv
except ImportError:  # pragma: no cover
    zhconv = None

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_WHITESPACE = re.compile(r"\s+")


def to_halfwidth(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def normalize(text: str | None) -> str:
    """Normalise a metadata string for exact comparison."""
    if not text:
        return ""
    out = _ZERO_WIDTH.sub("", str(text))
    out = to_halfwidth(out)
    out = _WHITESPACE.sub(" ", out).strip()
    out = out.casefold()
    if zhconv is not None:
        try:
            out = zhconv.convert(out, "zh-cn")
        except Exception:
            # A missing dictionary must degrade matching, never crash a sync.
            pass
    return out


def duration_seconds(milliseconds: int | float | None) -> int | None:
    """Round to whole seconds; 0.5s in either direction is the tolerated error."""
    if not milliseconds or milliseconds <= 0:
        return None
    return int(round(milliseconds / 1000.0))
