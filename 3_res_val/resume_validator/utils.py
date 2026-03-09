from __future__ import annotations

import difflib
from datetime import datetime
from typing import Optional

from dateutil import parser as dateparser
from dateutil.parser import ParserError

from .constants import DOMAIN_TYPO_CUTOFF, KNOWN_EMAIL_DOMAINS, ONGOING_TOKENS

__all__ = ["today", "parse_date", "is_ongoing", "years_between", "suggest_domain"]


def today() -> datetime:
    return datetime.today()


def parse_date(raw: str) -> Optional[datetime]:
    if not raw or not raw.strip():
        return None
    try:
        dt = dateparser.parse(
            raw.strip(),
            fuzzy=True,
            default=datetime(today().year, 1, 1),
        )
        return dt.replace(tzinfo=None) if dt is not None else None
    except (ParserError, OverflowError, ValueError, TypeError):
        return None


def is_ongoing(token: str) -> bool:
    return token.strip().lower() in ONGOING_TOKENS


def years_between(start: datetime, end: datetime) -> float:
    return (end - start).days / 365.25


def suggest_domain(domain: str) -> Optional[str]:
    d = domain.lower().strip()
    if d in KNOWN_EMAIL_DOMAINS:
        return None
    matches = difflib.get_close_matches(d, KNOWN_EMAIL_DOMAINS, n=1, cutoff=DOMAIN_TYPO_CUTOFF)
    return matches[0] if matches else None
