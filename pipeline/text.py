"""Plain-English output rules. No em dashes anywhere, whatever the model returns."""

from __future__ import annotations

import re
from typing import Any

_RANGE_DASH = re.compile(r"(?<=\d)\s*[–—]\s*(?=\d)")   # 2022–24 -> 2022-24
_OTHER_DASH = re.compile(r"\s*[–—]\s*")                 # a — b   -> a, b


def clean(s: str) -> str:
    s = _RANGE_DASH.sub("-", s)
    return _OTHER_DASH.sub(", ", s)


def plain(value: Any) -> Any:
    """Apply clean() to every string inside nested dicts and lists."""
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value
