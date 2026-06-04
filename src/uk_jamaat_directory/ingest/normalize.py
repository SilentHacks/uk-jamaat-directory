from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_mosque_name(name: str) -> str:
    collapsed = _WHITESPACE.sub(" ", name.strip().lower())
    return collapsed
