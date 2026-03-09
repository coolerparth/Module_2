from __future__ import annotations

import re

__all__ = [
    "URL_TIMEOUT",
    "MAX_RETRIES",
    "URL_EXECUTOR_WORKERS",
    "MAX_NAME_LEN",
    "MIN_NAME_LEN",
    "MIN_BULLETS",
    "MIN_BULLET_WORDS",
    "MIN_SKILLS",
    "MAX_CGPA",
    "MAX_PERCENTAGE",
    "MAX_EXPERIENCE_SPAN_YEARS",
    "DOMAIN_TYPO_CUTOFF",
    "EMAIL_RE",
    "DURATION_SPLIT_RE",
    "YEAR_RE",
    "DIGITS_RE",
    "ONGOING_TOKENS",
    "KNOWN_EMAIL_DOMAINS",
    "INDIAN_MOBILE_STARTS",
    "HEAD_BLOCKED_CODES",
    "URL_HEADERS",
]

URL_TIMEOUT: int = 8
MAX_RETRIES: int = 1
URL_EXECUTOR_WORKERS: int = 12

MAX_NAME_LEN: int = 100
MIN_NAME_LEN: int = 3

MIN_BULLETS: int = 2
MIN_BULLET_WORDS: float = 5.0

MIN_SKILLS: int = 3

MAX_CGPA: float = 10.0
MAX_PERCENTAGE: float = 100.0
MAX_EXPERIENCE_SPAN_YEARS: float = 40.0

DOMAIN_TYPO_CUTOFF: float = 0.82

EMAIL_RE: re.Pattern[str] = re.compile(
    r"^[\w.+\-]+"
    r"@"
    r"(?!-)"
    r"([\w][\w\-]*\.)+"
    r"[a-zA-Z]{2,}$"
)

DURATION_SPLIT_RE: re.Pattern[str] = re.compile(
    r"\s+to\s+"
    r"|\s*[\u2013\u2014]\s*"
    r"|\s+-\s+"
)

YEAR_RE: re.Pattern[str] = re.compile(r"\b(19|20)\d{2}\b")

DIGITS_RE: re.Pattern[str] = re.compile(r"\D")

ONGOING_TOKENS: frozenset[str] = frozenset({
    "present", "current", "ongoing", "now",
    "till date", "till now", "today", "date",
})

KNOWN_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.in", "yahoo.co.in", "yahoo.co.uk", "yahoo.co.jp",
    "outlook.com", "outlook.in", "outlook.co.uk",
    "hotmail.com", "hotmail.in", "hotmail.co.uk",
    "live.com", "live.in", "live.co.uk",
    "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me",
    "rediffmail.com",
    "aol.com",
    "msn.com",
})

INDIAN_MOBILE_STARTS: frozenset[str] = frozenset("6789")
HEAD_BLOCKED_CODES: frozenset[int] = frozenset({403, 405, 501})
URL_HEADERS: dict[str, str] = {"User-Agent": "ResumeValidationBot/3.0"}
