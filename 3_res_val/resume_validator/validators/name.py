from __future__ import annotations

import re

from ..constants import MAX_NAME_LEN, MIN_NAME_LEN
from ..result import ResultNode, fail, grey, ok

__all__ = ["validate_name"]

_NAME_CHARS_RE = re.compile(r"[^a-zA-Z\s\-'.]")
_DIGIT_RE = re.compile(r"[0-9]")
_VOWEL_RE = re.compile(r"[aeiouyAEIOUY]")


def validate_name(name: str | None) -> ResultNode:
    if not name or not name.strip():
        return fail(name, "Name is missing or empty.")

    cleaned = name.strip()

    if len(cleaned) < MIN_NAME_LEN:
        return fail(cleaned, f"Name too short — minimum {MIN_NAME_LEN} characters required.")

    if len(cleaned) > MAX_NAME_LEN:
        return fail(cleaned, f"Name exceeds {MAX_NAME_LEN} characters — likely spam or OCR garbage.")

    if _DIGIT_RE.search(cleaned):
        return fail(cleaned, "Name contains digits — not valid for a person's name.")

    alpha_only = cleaned.replace(" ", "").lower()
    if alpha_only and len(set(alpha_only)) == 1:
        return fail(cleaned, "Name is a single repeated character — spam detected.")

    words = cleaned.split()
    if len(words) >= 2 and len({w.lower() for w in words}) == 1 and len(words[0]) > 2:
        return fail(cleaned, "Name is the same word repeated — spam detected.")

    if _NAME_CHARS_RE.search(cleaned):
        return grey(cleaned, "Name contains unusual characters (accents or symbols) — verify manually.")

    if len(words) < 2:
        return grey(cleaned, "Single-word name — a full name (first + last) is preferred.")

    if not _VOWEL_RE.search(cleaned):
        return grey(cleaned, "Name has no vowels — possible OCR error or non-Latin transliteration.")

    return ok(cleaned)
