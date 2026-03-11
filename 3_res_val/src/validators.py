import difflib
import os
import re
from datetime import datetime
from typing import Any, Mapping, Union
import aiohttp
import asyncio
from dateutil import parser as dateparser
from dateutil.parser import ParserError

URL_TIMEOUT: int = 8
MAX_RETRIES: int = 1
MAX_NAME_LEN: int = 100
MIN_NAME_LEN: int = 3
MIN_BULLETS: int = 2
MIN_BULLET_WORDS: float = 5.0
MIN_SKILLS: int = 3
MAX_CGPA: float = 10.0
MAX_PERCENTAGE: float = 100.0
DOMAIN_TYPO_CUTOFF: float = 0.82
URL_POLICY: str = os.getenv("RESUME_URL_POLICY", "balanced").strip().lower()

if URL_POLICY not in {"strict", "balanced"}:
    URL_POLICY = "balanced"

_EMAIL_RE = re.compile(
    r"^[\w.+\-]+"
    r"@"
    r"(?!-)"
    r"([\w][\w\-]*\.)+"
    r"[a-zA-Z]{2,}$"
)

_DURATION_SPLIT_RE = re.compile(
    r"\s+to\s+"
    r"|\s*[\u2013\u2014]\s*"
    r"|\s+-\s+"
)

_COMPACT_YEAR_RANGE_RE = re.compile(
    r"^\s*((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2}|present|current|ongoing|now|today|date|enrolled)\s*$",
    re.IGNORECASE,
)

_ONGOING_TOKENS: frozenset[str] = frozenset({
    "present", "current", "ongoing", "now",
    "till date", "till now", "today", "date",
    "enrolled",
})

_KNOWN_EMAIL_DOMAINS: frozenset[str] = frozenset({
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

_INDIAN_MOBILE_STARTS: frozenset[str] = frozenset("6789")
_HEAD_BLOCKED_CODES: frozenset[int] = frozenset({403, 405, 501})

def _ok(data: Any, note: str = "") -> dict:
    return {"status": "valid", "data": data, "note": note}

def _fail(data: Any, error: str) -> dict:
    return {"status": "invalid", "data": data, "error": error}

def _grey(data: Any, note: str) -> dict:
    return {"status": "grey", "data": data, "note": note}

def _today() -> datetime:
    return datetime.today()

def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = dateparser.parse(
            raw,
            fuzzy=True,
            default=datetime(_today().year, 1, 1),
        )
        return dt.replace(tzinfo=None) if dt else None
    except (ParserError, OverflowError, ValueError, TypeError):
        return None

def _is_ongoing(token: str) -> bool:
    return token.strip().lower() in _ONGOING_TOKENS

def _years_between(start: datetime, end: datetime) -> float:
    return (end - start).days / 365.25


def build_url_validation_session() -> aiohttp.ClientSession:
    headers = {"User-Agent": "ResumeValidationBot/2.0"}
    timeout = aiohttp.ClientTimeout(total=URL_TIMEOUT)
    return aiohttp.ClientSession(headers=headers, timeout=timeout)


def _split_duration(raw: str) -> tuple[str, str] | None:
    parts = _DURATION_SPLIT_RE.split(raw, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    compact = _COMPACT_YEAR_RANGE_RE.match(raw)
    if compact:
        return compact.group(1).strip(), compact.group(2).strip()
    return None


def _coerce_to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    if _is_ongoing(token):
        return _today()
    try:
        return datetime.fromisoformat(token)
    except ValueError:
        return _parse_date(token)


def duration_payload_to_range(payload: Mapping[str, Any] | None) -> tuple[datetime, datetime] | None:
    if not payload:
        return None
    start_dt = _coerce_to_datetime(payload.get("start"))
    end_dt = _coerce_to_datetime(payload.get("end"))
    if start_dt is None or end_dt is None:
        return None
    if end_dt < start_dt:
        return None
    return start_dt, end_dt

def _suggest_domain(domain: str) -> str | None:
    d = domain.lower()
    if d in _KNOWN_EMAIL_DOMAINS:
        return None
    matches = difflib.get_close_matches(d, _KNOWN_EMAIL_DOMAINS, n=1, cutoff=DOMAIN_TYPO_CUTOFF)
    return matches[0] if matches else None

def validate_name(name: str | None) -> dict:
    if not name or not name.strip():
        return _fail(name, "Name is missing or empty.")
    cleaned = name.strip()
    if len(cleaned) < MIN_NAME_LEN:
        return _fail(cleaned, f"Name is too short — minimum {MIN_NAME_LEN} characters required.")
    if len(cleaned) > MAX_NAME_LEN:
        return _fail(cleaned, f"Name exceeds {MAX_NAME_LEN} characters — likely spam or malformed input.")
    if re.search(r"[0-9]", cleaned):
        return _fail(cleaned, "Name contains digits — not allowed in a person's name.")
    alpha_only = cleaned.replace(" ", "").lower()
    if alpha_only and len(set(alpha_only)) == 1:
        return _fail(cleaned, "Name consists of a single repeated character — appears to be spam.")
    words = cleaned.split()
    if len(words) >= 2 and len(set(w.lower() for w in words)) == 1 and len(words[0]) > 2:
        return _fail(cleaned, "Name consists of a single word repeated — appears to be spam.")
    if re.search(r"[^a-zA-Z\s\-'.]", cleaned):
        return _grey(cleaned, "Name contains unusual characters; verify manually.")
    if len(cleaned.split()) < 2:
        return _grey(cleaned, "Name appears to be a single word — a full name (first + last) is preferred.")
    if not re.search(r"[aeiouyAEIOUY]", cleaned):
        return _grey(cleaned, "Name contains no vowels — check for acronyms or OCR errors.")
    return _ok(cleaned)

def validate_email(email: str) -> dict:
    addr = email.strip()
    if not addr:
        return _fail(addr, "Email is empty after stripping whitespace.")
    if not _EMAIL_RE.match(addr):
        return _fail(addr, f"Email '{addr}' has an invalid format.")
    if ".." in addr:
        return _fail(addr, f"Email '{addr}' contains consecutive dots (..) — invalid per RFC.")
    domain = addr.split("@", 1)[1].lower()
    suggestion = _suggest_domain(domain)
    if suggestion:
        return _grey(
            addr,
            f"Email domain '{domain}' may be a typo — did you mean '{suggestion}'?",
        )
    return _ok(addr)

def validate_phone(phone: str) -> dict:
    raw = phone.strip()
    if not raw:
        return _fail(raw, "Phone number is empty after stripping whitespace.")
    digits = re.sub(r"\D", "", raw)
    n = len(digits)
    if n == 10:
        if digits[0] == "0":
            return _fail(raw, "Phone number cannot start with 0 in 10-digit national format.")
        if digits[0] in _INDIAN_MOBILE_STARTS:
            return _ok(
                f"+91{digits}", 
                note=f"Normalized Indian mobile number to strict E.164: +91{digits}"
            )
        return _grey(
            raw,
            "10-digit number without a country code — cannot determine country of origin. "
            "Please include the country code (e.g. +91 for India, +1 for US/Canada).",
        )
    if n == 11 and digits.startswith("1"):
        core = digits[1:]
        if core[0] == "0":
            return _fail(raw, f"US/Canada number '{raw}' has an invalid area code starting with 0.")
        return _ok(f"+{digits}", note=f"Normalized US/Canada (+1) number to strict E.164: +{digits}.")
    if n == 12 and digits.startswith("91"):
        core = digits[2:]
        if core[0] not in _INDIAN_MOBILE_STARTS:
            return _fail(
                raw,
                f"Indian number '{raw}' must begin with 6, 7, 8, or 9 after the +91 prefix.",
            )
        return _ok(f"+{digits}", note=f"India (+91) — 10-digit mobile number confirmed.")
    if 7 <= n <= 9:
        return _grey(
            raw,
            f"Phone has only {n} digits after stripping — expected at least 10. "
            "May be incomplete or missing country code.",
        )
    return _fail(
        raw,
        f"Phone '{raw}' has {n} digits — does not match any supported format. "
        "Use international format: +91 XXXXXXXXXX (India), +1 XXXXXXXXXX (US/Canada), etc.",
    )

def _network_issue_result(url: str, label: str, issue: str) -> dict:
    if URL_POLICY == "strict":
        return _fail(url, f"{label} '{url}' {issue}.")
    return _grey(url, f"{label} '{url}' could not be verified ({issue}); verify manually.")


async def _fetch_status(session: aiohttp.ClientSession, url: str) -> int:
    async with session.head(url, allow_redirects=True) as response:
        status = response.status
    if status in _HEAD_BLOCKED_CODES:
        async with session.get(url, allow_redirects=True) as response:
            status = response.status
    return status


async def _validate_url_async(
    url: str | None,
    label: str,
    session: aiohttp.ClientSession | None = None,
) -> dict:
    import logging
    log = logging.getLogger(__name__)

    if not url or not url.strip():
        return _ok(None, note=f"{label} not provided — optional field.")

    u = url.strip()
    if not u.startswith(("http://", "https://")):
        return _fail(u, f"{label} '{u}' must begin with http:// or https://.")
        
    for attempt in range(1 + MAX_RETRIES):
        try:
            if session is None:
                async with build_url_validation_session() as owned_session:
                    status = await _fetch_status(owned_session, u)
            else:
                status = await _fetch_status(session, u)

            if status < 400:
                return _ok(u, note=f"Reachable — HTTP {status}.")
            return _fail(u, f"{label} '{u}' returned HTTP {status} — dead or broken link.")

        except asyncio.TimeoutError:
            if attempt == MAX_RETRIES:
                return _network_issue_result(u, label, f"timed out after {URL_TIMEOUT}s")
            log.warning("[%s] Timeout on attempt %d — retrying...", label, attempt + 1)
        
        except aiohttp.ClientSSLError as exc:
            return _fail(u, f"{label} '{u}' SSL/TLS error: {exc}.")
            
        except aiohttp.ClientConnectorError as exc:
            if attempt == MAX_RETRIES:
                return _network_issue_result(u, label, f"connection failed: {exc}")
            log.warning("[%s] Connection error on attempt %d — retrying...", label, attempt + 1)
            
        except aiohttp.ClientError as exc:
            return _network_issue_result(u, label, f"request failed: {exc}")
        
        except Exception as exc:
            return _fail(u, f"{label} '{u}' could not be verified: {exc}.")

    return _fail(u, f"{label} '{u}' could not be verified.")

def validate_duration(
    duration: str | None,
    section_label: str,
    *,
    allow_future_end: bool = False,
) -> dict:
    if not duration or not duration.strip():
        return _grey(duration, f"{section_label}: Duration is missing or blank.")
    stripped = duration.strip()
    split = _split_duration(stripped)
    if split is None:
        if re.search(r"\b(19|20)\d{2}\b", stripped):
            return _ok(
                {"raw": stripped, "start": None, "end": stripped},
                note=f"{section_label}: Single-year entry.",
            )
        return _grey(
            stripped,
            f"{section_label}: Duration '{stripped}' is ambiguous — could not identify a year.",
        )
    raw_start, raw_end = split
    if _is_ongoing(raw_end):
        start_dt = _parse_date(raw_start)
        if start_dt is None:
            return _grey(stripped, f"{section_label}: Start date '{raw_start}' could not be parsed.")
        if start_dt > _today():
            return _grey(
                {"raw": stripped, "start": start_dt.date().isoformat(), "end": "Present"},
                f"{section_label}: Start date '{raw_start}' is in the future — verify if this is an upcoming role.",
            )
        return _ok(
            {"raw": stripped, "start": start_dt.date().isoformat(), "end": "Present"},
            note=f"{section_label}: Active/ongoing entry.",
        )
    start_dt = _parse_date(raw_start)
    end_dt = _parse_date(raw_end)
    if start_dt is None and end_dt is None:
        return _grey(
            stripped,
            f"{section_label}: Neither '{raw_start}' nor '{raw_end}' could be parsed as dates.",
        )
    if start_dt is None:
        return _grey(stripped, f"{section_label}: Start date '{raw_start}' could not be parsed.")
    if end_dt is None:
        return _grey(stripped, f"{section_label}: End date '{raw_end}' could not be parsed.")
    payload = {
        "raw": stripped,
        "start": start_dt.date().isoformat(),
        "end": end_dt.date().isoformat(),
    }
    if end_dt < start_dt:
        return _fail(
            payload,
            f"{section_label}: End date '{raw_end}' is before start date '{raw_start}' — impossible timeline.",
        )
    if start_dt > _today():
        return _grey(
            payload,
            f"{section_label}: Start date '{raw_start}' is in the future — verify if this is an upcoming role.",
        )
    if end_dt > _today() and not allow_future_end:
        return _grey(
            payload,
            f"{section_label}: End date '{raw_end}' is in the future — mark as 'ongoing' if still active.",
        )
    span_years = _years_between(start_dt, end_dt)
    if span_years > 40:
        return _grey(
            payload,
            f"{section_label}: Duration spans {span_years:.1f} years — unusually long; verify manually.",
        )
    return _ok(payload)

def _evaluate_description(points: dict[str, Any] | None, label: str) -> dict:
    if not points:
        return _grey(points, f"{label}: No description bullets provided.")
    bullets = [s for v in points.values() if (s := str(v).strip())]
    count = len(bullets)
    if count == 0:
        return _grey(points, f"{label}: All description bullets are empty.")
    avg_words = sum(len(b.split()) for b in bullets) / count
    if count >= MIN_BULLETS and avg_words >= MIN_BULLET_WORDS:
        return _ok(points)
    if count >= MIN_BULLETS:
        return _grey(
            points,
            f"{label}: {count} bullets present but average is only {avg_words:.1f} words — lacks depth.",
        )
    if avg_words >= 10:
        return _grey(
            points,
            f"{label}: Only {count} bullet — detailed but consider expanding to multiple points.",
        )
    return _grey(points, f"{label}: Only {count} short bullet(s) — lacks sufficient detail.")

def _validate_grade(grade: Union[str, float, int, None], level: str) -> dict:
    if grade is None:
        return _grey(None, f"Grade for '{level}' is not provided.")
    grade_str = str(grade).strip()
    if not grade_str or grade_str.lower() == "none":
        return _grey(grade, f"Grade for '{level}' is not provided.")
    if isinstance(grade, (int, float)):
        if grade < 0:
            return _fail(grade, f"Grade for '{level}' is negative ({grade}) — invalid value.")
        if grade <= MAX_CGPA:
            return _ok(grade_str, note=f"CGPA format ({grade}/10.0).")
        if grade <= MAX_PERCENTAGE:
            return _ok(grade_str, note=f"Percentage format ({grade}%).")
        return _fail(
            grade,
            f"Grade for '{level}' is {grade} — exceeds maximum valid percentage (100%).",
        )
    return _ok(grade_str)
