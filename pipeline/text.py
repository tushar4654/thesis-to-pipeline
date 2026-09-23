"""Plain-English output rules. No em dashes anywhere, whatever the model returns."""

from __future__ import annotations

import re
from typing import Any

_RANGE_DASH = re.compile("(?<=\\d)\\s*[\u2013\u2014]\\s*(?=\\d)")  # "2022 to 24" ranges become 2022-24
_OTHER_DASH = re.compile("\\s*[\u2013\u2014]\\s*")                 # any other dash becomes a comma


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
