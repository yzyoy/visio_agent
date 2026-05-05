"""Helpers for normalizing LLM-provided shape text."""

from __future__ import annotations

import re
from typing import Any, Tuple


_LINE_BREAK_RE = re.compile(r"\s*(?:\r\n|\r|\n)+\s*")


def normalize_shape_text(value: Any) -> Tuple[str, bool]:
    """Collapse embedded line breaks in shape text into single spaces.

    Returns the normalized text plus a flag indicating whether the input
    had to be rewritten.
    """

    original = "" if value is None else str(value)
    normalized = _LINE_BREAK_RE.sub(" ", original).strip()
    return normalized, normalized != original
