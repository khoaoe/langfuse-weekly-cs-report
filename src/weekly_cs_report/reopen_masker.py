from __future__ import annotations

"""Deterministic PII masking for reopen-labeling model inputs.

This module deliberately contains no name detection, NER, or logging.  It
implements only the exact-value and pattern classes approved in the reopen
labeling design.
"""

import re
from typing import Mapping


MAX_REOPEN_TEXT_LENGTH = 4_000
PII_PLACEHOLDER = "[PII]"

_KNOWN_META_KEYS = (
    "UserID",
    "App user",
    "TransID",
    "Số điện thoại người dùng",
)
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_EMAIL = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,63}\b",
    re.IGNORECASE,
)
_SEPARATED_CARD = re.compile(
    r"(?<!\d)(?<!\d[ -])(?:\d[ -]?){12,18}\d(?![ -]?\d)"
)
_DIGIT_SEQUENCE = re.compile(r"(?<!\d)\d{9,20}(?!\d)")


def mask_reopen_text(text: str, meta: Mapping[str, object]) -> str:
    """Return a bounded copy masked only by approved deterministic rules."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(meta, Mapping):
        raise TypeError("meta must be a mapping")

    masked = text
    known_values = {
        value
        for key in _KNOWN_META_KEYS
        for value in (meta.get(key),)
        if isinstance(value, str) and value
    }
    for value in sorted(known_values, key=lambda item: (-len(item), item)):
        masked = masked.replace(value, PII_PLACEHOLDER)

    masked = _URL.sub(PII_PLACEHOLDER, masked)
    masked = _EMAIL.sub(PII_PLACEHOLDER, masked)
    masked = _SEPARATED_CARD.sub(_mask_card_candidate, masked)
    masked = _DIGIT_SEQUENCE.sub(PII_PLACEHOLDER, masked)
    return masked[:MAX_REOPEN_TEXT_LENGTH]


def _mask_card_candidate(match: re.Match[str]) -> str:
    candidate = match.group(0)
    digit_count = sum(character.isdigit() for character in candidate)
    if (
        13 <= digit_count <= 19
        and any(separator in candidate for separator in (" ", "-"))
    ):
        return PII_PLACEHOLDER
    return candidate
