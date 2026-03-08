"""
Validation_engine.py
===================
Intelligent Validation Engine — Smart Resume Audit & Verification System

Validates raw extracted resume JSON and partitions results into three states:
    validated_sections  — clean, verified data ready for downstream scoring
    invalid_sections    — data that failed hard checks, with error messages
    grey_area           — ambiguous or incomplete data needing manual review

Public API
----------
    run(raw_json: dict) -> dict
        Full pipeline: validate → partition → tri-state output.

    validate_resume(raw: dict) -> dict
        Raw per-field validation report (for advanced consumers).

    partition(report: dict) -> dict
        Convert a raw report into the tri-state structure.

Design decisions
----------------
- _today() is a function, NOT a module-level constant.
  A constant would freeze at import time, breaking long-running servers.

- This module never calls logging.basicConfig — it is a library.
  Callers configure their own logging handlers.

- All datetime comparisons use naive datetimes (tzinfo=None).
  dateutil can return tz-aware objects; _parse_date() always strips tz.

- Duration split uses alternation ( \\s+to\\s+ | en/em-dash | spaced-hyphen ).
  A character class [-–—to] would match individual 't' and 'o' chars,
  corrupting month names like October, November, August, September.

- HEAD is tried first for URL reachability checks; GET (stream=True) is the
  fallback only when the server blocks HEAD (403 / 405 / 501).
  Using GET unconditionally downloads the full response body — wasteful.

- Future start dates in experience are flagged grey (not hard-fail) because
  "Incoming SWE at Google, starts June 2026" is a valid resume entry.

- Grade fields use str(grade) before checking, so numeric CGPAs (9.2 float)
  are handled correctly.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import requests
from dateutil import parser as dateparser
from dateutil.parser import ParserError

# ---------------------------------------------------------------------------
# Module logger  (callers configure handlers — we never call basicConfig here)
# ---------------------------------------------------------------------------
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants & compiled patterns
# ---------------------------------------------------------------------------

URL_TIMEOUT: int = 8          # seconds per HTTP attempt
MAX_RETRIES: int = 1          # extra retry on Timeout / ConnectionError
MAX_NAME_LEN: int = 100       # guard against junk / spam names
MIN_NAME_LEN: int = 3         # must be > 2 printable characters
MIN_BULLETS: int = 2          # minimum bullets for a "rich" description
MIN_BULLET_WORDS: float = 5.0 # minimum average words per bullet
MIN_SKILLS: int = 3           # minimum skills expected

# Email: local@domain.tld
#   - local  : word-chars, dots, plus, dash
#   - domain : must NOT start with a dash; each label is [word][word-dash]*
#   - TLD    : letters only, min 2 chars
#   - double-dot (..) is checked separately after regex match
_EMAIL_RE = re.compile(
    r"^[\w.+\-]+"
    r"@"
    r"(?!-)"                       # domain must not start with dash
    r"([\w][\w\-]*\.)+"            # one or more domain labels, each ending with dot
    r"[a-zA-Z]{2,}$"              # TLD: only letters, at least 2
)

# Duration split — matches the separator between start and end date tokens.
# Handles:
#   "Jan 2022 - Mar 2023"   spaced hyphen
#   "Jan 2022 – Mar 2023"   en-dash (U+2013)
#   "Jan 2022 — Mar 2023"   em-dash (U+2014)
#   "Jan 2022 to Mar 2023"  word "to"
# Does NOT split on hyphens inside words ("Toronto-based", "full-time").
_DURATION_SPLIT_RE = re.compile(
    r"\s+to\s+"                 # word "to" with surrounding whitespace
    r"|\s*[\u2013\u2014]\s*"    # en-dash or em-dash (unambiguous separators)
    r"|\s+-\s+"                 # hyphen ONLY when surrounded by whitespace
)

# Tokens that mean "this entry is still active / ongoing"
_ONGOING_TOKENS: frozenset[str] = frozenset({
    "present", "current", "ongoing", "now",
    "till date", "till now", "today", "date",
})

# Supported country code prefixes and their digit lengths
_COUNTRY_CODES: dict[str, tuple[int, str]] = {
    "1":  (11, "US/Canada (+1)"),
    "91": (12, "India (+91)"),
}


# ---------------------------------------------------------------------------
# Result-node factories
# ---------------------------------------------------------------------------

def _ok(data: Any, note: str = "") -> dict:
    """Represents a field that passed all validation checks."""
    return {"status": "valid", "data": data, "note": note}


def _fail(data: Any, error: str) -> dict:
    """Represents a field that failed a hard check."""
    return {"status": "invalid", "data": data, "error": error}


def _grey(data: Any, note: str) -> dict:
    """Represents a field that is ambiguous, incomplete, or needs review."""
    return {"status": "grey", "data": data, "note": note}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _today() -> datetime:
    """Return the current datetime.  Called at runtime — never frozen."""
    return datetime.today()


def _parse_date(raw: str) -> datetime | None:
    """
    Parse a fuzzy date string into a naive datetime.
    Returns None if parsing fails for any reason.
    Always strips timezone info so comparisons with _today() never raise TypeError.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = dateparser.parse(
            raw,
            fuzzy=True,
            default=datetime(_today().year, 1, 1),
        )
        if dt is None:
            return None
        # Strip tz — dateutil may return tz-aware objects (e.g. "Jan 2022 UTC")
        # and comparing tz-aware vs tz-naive raises TypeError.
        return dt.replace(tzinfo=None)
    except (ParserError, OverflowError, ValueError, TypeError):
        return None


def _is_ongoing(token: str) -> bool:
    """Return True if the token represents an ongoing / active entry."""
    return token.strip().lower() in _ONGOING_TOKENS


def _years_between(start: datetime, end: datetime) -> float:
    """Return the number of years between two datetimes (float)."""
    return (end - start).days / 365.25


# ---------------------------------------------------------------------------
# Individual field validators
# ---------------------------------------------------------------------------

def validate_name(name: Any) -> dict:
    """
    Validate a candidate name.

    Rules (hard failures):
        - Must be a non-empty string
        - Length: 3–100 characters
        - No digits
        - Not a single repeating character (e.g. "aaaa aaaa")

    Rules (grey — needs human review):
        - Contains unusual characters (not a-zA-Z space hyphen apostrophe dot)
        - Only one word (first name only)
        - Contains no vowels (possible acronym or OCR error)
    """
    if not name or not isinstance(name, str):
        return _fail(name, "Name is missing or not a string.")

    cleaned = name.strip()

    if len(cleaned) < MIN_NAME_LEN:
        return _fail(cleaned, f"Name is too short — minimum {MIN_NAME_LEN} characters required.")

    if len(cleaned) > MAX_NAME_LEN:
        return _fail(cleaned, f"Name exceeds {MAX_NAME_LEN} characters — likely spam or malformed input.")

    if re.search(r"[0-9]", cleaned):
        return _fail(cleaned, "Name contains digits — not allowed in a person's name.")

    # Repeating-character spam check (e.g. "aaaa aaaa", "zzzzz zzzzz")
    alpha_only = cleaned.replace(" ", "").lower()
    if alpha_only and len(set(alpha_only)) == 1:
        return _fail(cleaned, "Name consists of a single repeated character — appears to be spam.")

    # Unusual character check (allow: letters, space, hyphen, apostrophe, period)
    if re.search(r"[^a-zA-Z\s\-'.]", cleaned):
        return _grey(cleaned, "Name contains unusual characters (e.g. accents or symbols); verify manually.")

    words = cleaned.split()
    if len(words) < 2:
        return _grey(cleaned, "Name appears to be a single word — a full name (first + last) is preferred.")

    # No vowels: could be an acronym, OCR garbage, or a non-Latin transliteration
    if not re.search(r"[aeiouyAEIOUY]", cleaned):
        return _grey(cleaned, "Name contains no vowels — check for acronyms or OCR errors.")

    return _ok(cleaned)


def validate_email(email: Any) -> dict:
    """
    Validate a single email address.

    Checks:
        - Non-empty string
        - Matches RFC-5321-inspired pattern (local@domain.tld)
        - Domain does not start with a dash
        - TLD is at least 2 alphabetic characters
        - No consecutive dots (..)
    """
    if not email or not isinstance(email, str):
        return _fail(email, "Email is missing or not a string.")

    addr = email.strip()

    if not addr:
        return _fail(addr, "Email is an empty string after stripping whitespace.")

    if not _EMAIL_RE.match(addr):
        return _fail(addr, f"Email '{addr}' has an invalid format.")

    if ".." in addr:
        return _fail(addr, f"Email '{addr}' contains consecutive dots (..) — invalid format.")

    return _ok(addr)


def validate_phone(phone: Any) -> dict:
    """
    Validate a phone number.

    Strips all non-digit characters, then:
        10 digits  → valid bare number (must not start with 0)
        11 digits starting with "1"  → US/Canada (+1)
        12 digits starting with "91" → India (+91); core must start 6-9
        8–9 digits → grey (possibly incomplete)
        Anything else → invalid (with clear message listing supported codes)
    """
    if not phone or not isinstance(phone, str):
        return _fail(phone, "Phone number is missing or not a string.")

    raw = phone.strip()
    if not raw:
        return _fail(raw, "Phone number is empty after stripping whitespace.")

    digits = re.sub(r"\D", "", raw)
    n = len(digits)

    # ── 10-digit bare number ─────────────────────────────────────────────────
    if n == 10:
        if digits[0] == "0":
            return _fail(raw, "Phone number cannot start with 0 (10-digit national format).")
        return _ok(raw)

    # ── US / Canada (+1) ─────────────────────────────────────────────────────
    if n == 11 and digits.startswith("1"):
        core = digits[1:]
        if core[0] == "0":
            return _fail(raw, f"US/Canada number '{raw}' has an invalid area code (starts with 0).")
        return _ok(raw, note="US/Canada country code (+1) detected; 10-digit number confirmed.")

    # ── India (+91) ──────────────────────────────────────────────────────────
    if n == 12 and digits.startswith("91"):
        core = digits[2:]
        if core[0] not in "6789":
            return _fail(
                raw,
                f"Indian mobile number '{raw}' must begin with 6, 7, 8, or 9 after the +91 prefix.",
            )
        return _ok(raw, note="India country code (+91) detected; 10-digit number confirmed.")

    # ── Possibly incomplete ───────────────────────────────────────────────────
    if 7 <= n <= 9:
        return _grey(
            raw,
            f"Phone has only {n} digits after stripping — expected 10. May be incomplete or missing country code.",
        )

    # ── Everything else ───────────────────────────────────────────────────────
    supported = ", ".join(f"{v[1]} ({v[0]} digits)" for v in _COUNTRY_CODES.values())
    return _fail(
        raw,
        f"Phone '{raw}' has {n} digits after stripping — cannot match any known format. "
        f"Supported formats: 10-digit bare number, {supported}.",
    )


def validate_url(url: Any, label: str = "URL") -> dict:
    """
    Live-check URL reachability via HTTP.

    Strategy:
        1. Send a HEAD request (no body download).
        2. If the server returns 403 / 405 / 501 (HEAD blocked or unsupported),
           fall back to a GET with stream=True (downloads headers only).
        3. HTTP 2xx or 3xx → valid.  4xx or 5xx → invalid.

    Retries MAX_RETRIES additional times on Timeout or ConnectionError.
    Non-retryable errors (SSL, invalid scheme, etc.) fail immediately.
    """
    if not url or not isinstance(url, str):
        return _fail(url, f"{label}: URL is missing or not a string.")

    url = url.strip()
    if not url:
        return _fail(url, f"{label}: URL is an empty string.")

    if not url.startswith(("http://", "https://")):
        return _fail(url, f"{label} '{url}' must begin with http:// or https://.")

    headers = {"User-Agent": "ResumeValidationBot/1.0"}
    # Codes that mean HEAD is blocked/unsupported — fall back to GET
    HEAD_BLOCKED_CODES = {403, 405, 501}

    for attempt in range(1 + MAX_RETRIES):
        try:
            # ── Step 1: HEAD (bandwidth-free reachability check) ─────────────
            with requests.head(
                url,
                timeout=URL_TIMEOUT,
                allow_redirects=True,
                headers=headers,
            ) as head_resp:
                status = head_resp.status_code

            # ── Step 2: GET fallback only when HEAD is explicitly blocked ─────
            if status in HEAD_BLOCKED_CODES:
                log.debug("%s: HEAD returned %d — falling back to GET (stream)", label, status)
                with requests.get(
                    url,
                    timeout=URL_TIMEOUT,
                    allow_redirects=True,
                    headers=headers,
                    stream=True,   # fetch headers only — no body download
                ) as get_resp:
                    status = get_resp.status_code

            # ── Step 3: evaluate final status ────────────────────────────────
            if status < 400:
                return _ok(url, note=f"Reachable — HTTP {status}.")
            return _fail(url, f"{label} '{url}' returned HTTP {status} — dead or broken link.")

        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES:
                return _fail(
                    url,
                    f"{label} '{url}' timed out after {URL_TIMEOUT}s — server unreachable.",
                )
            log.warning("[%s] Timeout on attempt %d — retrying...", label, attempt + 1)

        except requests.exceptions.SSLError as exc:
            return _fail(url, f"{label} '{url}' SSL/TLS error: {exc}.")

        except requests.exceptions.ConnectionError as exc:
            if attempt == MAX_RETRIES:
                return _fail(url, f"{label} '{url}' connection error: {exc}.")
            log.warning("[%s] Connection error on attempt %d — retrying...", label, attempt + 1)

        except requests.exceptions.RequestException as exc:
            # Non-retryable (malformed URL, proxy error, etc.)
            return _fail(url, f"{label} '{url}' request failed: {exc}.")

    # Safety net — every branch above returns, but static analysers need this.
    return _fail(url, f"{label} '{url}' could not be verified.")  # pragma: no cover


# ---------------------------------------------------------------------------
# Date / duration validator
# ---------------------------------------------------------------------------

def validate_duration(
    duration: Any,
    section_label: str,
    *,
    allow_future_end: bool = False,
) -> dict:
    """
    Parse and validate a duration string (e.g. "Jan 2022 - Mar 2023").

    Parameters
    ----------
    duration        : raw duration string from the resume
    section_label   : human-readable context used in error messages
    allow_future_end: set True for education (enrolled students have future end dates)

    Validation order
    ----------------
    1. Unparse-able input                       → grey
    2. Single-year entry (class10/12)           → ok (partial)
    3. Ongoing entry (ends with "Present" etc.) → ok
    4. Either/both dates unparseable            → grey
    5. end < start                              → invalid  (hard temporal violation)
    6. start > today                            → grey     (possible "Incoming" role)
    7. end > today and not allow_future_end     → grey     (flag for review)
    8. span > 40 years                          → grey     (unusually long)
    9. All checks passed                        → ok

    Split logic: uses _DURATION_SPLIT_RE which splits on:
        - word "to" surrounded by whitespace (Jan 2022 to Mar 2023)
        - en-dash or em-dash (unambiguous)
        - hyphen surrounded by whitespace (Jan 2022 - Mar 2023)
    This avoids splitting on hyphens inside words (e.g. "Toronto-based").
    """
    if not duration or not isinstance(duration, str):
        return _grey(duration, f"{section_label}: Duration is missing or not a string.")

    stripped = duration.strip()
    if not stripped:
        return _grey(stripped, f"{section_label}: Duration is blank.")

    parts = _DURATION_SPLIT_RE.split(stripped, maxsplit=1)

    # ── Single token: might be a graduation year (class10/12) ────────────────
    if len(parts) == 1:
        if re.search(r"\b(19|20)\d{2}\b", parts[0]):
            return _ok(
                {"raw": stripped, "start": None, "end": parts[0].strip()},
                note=f"{section_label}: Single-year entry.",
            )
        return _grey(
            stripped,
            f"{section_label}: Duration '{stripped}' is ambiguous — could not identify a year.",
        )

    raw_start, raw_end = parts[0].strip(), parts[1].strip()

    # ── Ongoing entry ─────────────────────────────────────────────────────────
    if _is_ongoing(raw_end):
        start_dt = _parse_date(raw_start)
        if start_dt is None:
            return _grey(
                stripped,
                f"{section_label}: Start date '{raw_start}' could not be parsed.",
            )
        if start_dt > _today():
            return _grey(
                {"raw": stripped, "start": start_dt.date().isoformat(), "end": "Present"},
                f"{section_label}: Start date '{raw_start}' is in the future — "
                "verify if this is an upcoming/incoming role.",
            )
        return _ok(
            {"raw": stripped, "start": start_dt.date().isoformat(), "end": "Present"},
            note=f"{section_label}: Active/ongoing entry.",
        )

    # ── Parse both ends ───────────────────────────────────────────────────────
    start_dt = _parse_date(raw_start)
    end_dt = _parse_date(raw_end)

    if start_dt is None and end_dt is None:
        return _grey(
            stripped,
            f"{section_label}: Neither '{raw_start}' nor '{raw_end}' could be parsed as dates.",
        )
    if start_dt is None:
        return _grey(
            stripped,
            f"{section_label}: Start date '{raw_start}' could not be parsed.",
        )
    if end_dt is None:
        return _grey(
            stripped,
            f"{section_label}: End date '{raw_end}' could not be parsed.",
        )

    payload = {
        "raw": stripped,
        "start": start_dt.date().isoformat(),
        "end": end_dt.date().isoformat(),
    }

    # ── Rule 5: end before start — always a hard failure ─────────────────────
    if end_dt < start_dt:
        return _fail(
            payload,
            f"{section_label}: End date '{raw_end}' is before start date '{raw_start}' "
            "— impossible timeline (temporal logic violation).",
        )

    # ── Rule 6: start in the future ──────────────────────────────────────────
    # Soft check: could be an "Incoming" role or a typo.
    if start_dt > _today():
        return _grey(
            payload,
            f"{section_label}: Start date '{raw_start}' is in the future. "
            "Verify if this is an upcoming/incoming role or a data entry error.",
        )

    # ── Rule 7: end in the future (and not allow_future_end) ─────────────────
    if end_dt > _today() and not allow_future_end:
        return _grey(
            payload,
            f"{section_label}: End date '{raw_end}' is in the future. "
            "Mark as 'enrolled/ongoing' if still active.",
        )

    # ── Rule 8: unreasonably long span ───────────────────────────────────────
    span_years = _years_between(start_dt, end_dt)
    if span_years > 40:
        return _grey(
            payload,
            f"{section_label}: Duration spans {span_years:.1f} years — unusually long; verify manually.",
        )

    return _ok(payload)


# ---------------------------------------------------------------------------
# Description / bullet heuristic
# ---------------------------------------------------------------------------

def _evaluate_description(points: Any, label: str, min_bullets: int = MIN_BULLETS) -> dict:
    """
    Assess the richness of a bullet-point description.

    Expects points to be a dict of {key: bullet_text}.
    Returns:
        ok    — enough bullets with sufficient average word count
        grey  — present but thin (few bullets or very short text)
    """
    if not isinstance(points, dict) or not points:
        return _grey(points, f"{label}: No description bullets provided.")

    # Build bullet list — avoid double str() call by computing once per value
    bullets: list[str] = []
    for v in points.values():
        text = str(v).strip()
        if text:
            bullets.append(text)

    count = len(bullets)
    if count == 0:
        return _grey(points, f"{label}: All description bullets are empty.")

    avg_words = sum(len(b.split()) for b in bullets) / count

    if count >= min_bullets and avg_words >= MIN_BULLET_WORDS:
        return _ok(points)
    if count >= min_bullets:
        return _grey(
            points,
            f"{label}: Bullets present ({count}) but very short "
            f"(avg {avg_words:.1f} words/bullet) — lacks technical depth.",
        )
    if avg_words >= 10:
        return _grey(
            points,
            f"{label}: Only {count} bullet — detailed but consider expanding to multiple points.",
        )
    return _grey(
        points,
        f"{label}: Only {count} short bullet(s) — lacks sufficient detail and depth.",
    )


# ---------------------------------------------------------------------------
# Section validators
# ---------------------------------------------------------------------------

def validate_education(education: Any) -> dict:
    """
    Validate all education levels in the education dict.

    Recognised levels: phd, pg, ug, class12, class10.
    Missing levels are silently accepted (not every candidate has all levels).

    Grade field accepts any type (str, float, int) because CGPA is often a
    float (e.g. 9.2) that the JSON extractor may not stringify.
    """
    if not education or not isinstance(education, dict):
        return _fail(education, "Education section is missing or not a dict.")

    results: dict = {}
    levels = ("phd", "pg", "ug", "class12", "class10")

    for level in levels:
        entry = education.get(level)

        if entry is None:
            results[level] = _ok(None, note=f"'{level}' not provided — acceptable.")
            continue

        if not isinstance(entry, dict):
            results[level] = _fail(
                entry, f"Education entry for '{level}' must be a dict, got {type(entry).__name__}."
            )
            continue

        row: dict = {}

        # ── Degree ───────────────────────────────────────────────────────────
        degree = entry.get("degree")
        if not degree or not isinstance(degree, str) or len(degree.strip()) < 2:
            row["degree"] = _fail(degree, f"Degree for '{level}' is missing or too short.")
        else:
            row["degree"] = _ok(degree.strip())

        # ── Institution ───────────────────────────────────────────────────────
        institution = entry.get("institution")
        if not institution or not isinstance(institution, str) or len(institution.strip()) < 2:
            row["institution"] = _fail(
                institution, f"Institution for '{level}' is missing or too short."
            )
        else:
            row["institution"] = _ok(institution.strip())

        # ── Duration  (enrolled students may have future end dates) ──────────
        row["duration"] = validate_duration(
            entry.get("duration"),
            f"Education[{level}]",
            allow_future_end=True,
        )

        # ── Grade  (accept str, int, float — CGPA is often a float) ──────────
        grade = entry.get("grade")
        grade_str = str(grade).strip() if grade is not None else ""
        if grade_str and grade_str.lower() != "none":
            row["grade"] = _ok(grade_str)
        else:
            row["grade"] = _grey(grade, f"Grade for '{level}' is not provided.")

        results[level] = row

    return results


def validate_experience(experience: Any) -> list:
    """
    Validate work experience entries.

    Each entry must be a dict with at minimum: role, company, start, end.
    Also performs cross-entry timeline overlap detection and tags overlapping
    entries with a grey warning (partial overlap is common in consulting /
    part-time work, so it is not a hard failure).
    """
    if not experience:
        return []
    if not isinstance(experience, list):
        return [_fail(experience, "Experience section must be a list of dicts.")]

    results: list[dict] = []
    # (start_dt, end_dt, label) tuples for overlap detection
    parsed_ranges: list[tuple[datetime, datetime, str]] = []

    for i, exp in enumerate(experience):
        slot_label = f"Experience[{i}]"

        # ── Guard: must be a dict ─────────────────────────────────────────────
        if not isinstance(exp, dict):
            results.append(
                _fail(exp, f"{slot_label}: Entry must be a dict, got {type(exp).__name__}.")
            )
            continue

        role_name = str(exp.get("role", "Unknown Role")).strip() or "Unknown Role"
        label = f"Experience[{i}] ({role_name})"
        row: dict = {"_label": label}

        # ── Role ──────────────────────────────────────────────────────────────
        role = exp.get("role")
        role_str = str(role).strip() if role else ""
        if len(role_str) < 2:
            row["role"] = _fail(role, f"{label}: Role is missing or too short.")
        else:
            row["role"] = _ok(role_str)

        # ── Company ───────────────────────────────────────────────────────────
        company = exp.get("company")
        company_str = str(company).strip() if company else ""
        if len(company_str) < 2:
            row["company"] = _fail(company, f"{label}: Company name is missing or too short.")
        else:
            row["company"] = _ok(company_str)

        # ── Duration ──────────────────────────────────────────────────────────
        raw_start = str(exp.get("start", "")).strip()
        raw_end   = str(exp.get("end", "")).strip()

        if raw_start and raw_end:
            dur_str = f"{raw_start} - {raw_end}"
            dur_result = validate_duration(dur_str, label, allow_future_end=False)
            row["duration"] = dur_result

            # Collect valid ranges for overlap check
            if dur_result["status"] == "valid":
                d = dur_result["data"]
                s_dt = _parse_date(d.get("start") or "")
                # "Present" end → treat as today
                e_dt = (
                    _parse_date(d["end"])
                    if d.get("end") and d["end"] != "Present"
                    else _today()
                )
                if s_dt and e_dt:
                    parsed_ranges.append((s_dt, e_dt, label))

        elif raw_start:
            row["duration"] = _grey(
                {"start": raw_start, "end": None},
                f"{label}: End date missing — treating as ongoing.",
            )
        else:
            row["duration"] = _grey(
                None,
                f"{label}: Both start and end dates are missing.",
            )

        # ── Description ───────────────────────────────────────────────────────
        row["description"] = _evaluate_description(exp.get("points") or {}, label)

        results.append(row)

    # ── Cross-entry overlap detection ─────────────────────────────────────────
    # O(n²) but n is typically < 10 for resumes — acceptable.
    n = len(parsed_ranges)
    for i in range(n):
        s1, e1, lbl1 = parsed_ranges[i]
        for j in range(i + 1, n):
            s2, e2, lbl2 = parsed_ranges[j]
            # Two ranges overlap when one starts before the other ends
            if s1 < e2 and s2 < e1:
                log.warning("Timeline overlap: %s overlaps %s", lbl1, lbl2)
                for row in results:
                    if row.get("_label") in (lbl1, lbl2):
                        row["timeline_overlap"] = _grey(
                            None,
                            f"Timeline overlap detected between {lbl1} and {lbl2} — verify manually.",
                        )

    return results


def validate_projects(projects: Any) -> list:
    """
    Validate project entries.

    Each entry must be a dict with at minimum: name.
    GitHub links are live-checked if present.
    """
    if not projects:
        return []
    if not isinstance(projects, list):
        return [_fail(projects, "Projects section must be a list of dicts.")]

    results: list[dict] = []

    for i, proj in enumerate(projects):
        slot_label = f"Project[{i}]"

        # ── Guard: must be a dict ─────────────────────────────────────────────
        if not isinstance(proj, dict):
            results.append(
                _fail(proj, f"{slot_label}: Entry must be a dict, got {type(proj).__name__}.")
            )
            continue

        proj_name = str(proj.get("name", "Unnamed")).strip() or "Unnamed"
        label = f"Project[{i}] ({proj_name})"
        row: dict = {"_label": label}

        # ── Name ──────────────────────────────────────────────────────────────
        name = proj.get("name")
        name_str = str(name).strip() if name else ""
        if len(name_str) < 2:
            row["name"] = _fail(name, f"{label}: Project name is missing or too short.")
        else:
            row["name"] = _ok(name_str)

        # ── Duration ──────────────────────────────────────────────────────────
        raw_dur = proj.get("duration")
        if raw_dur:
            row["duration"] = validate_duration(
                raw_dur, label, allow_future_end=False
            )
        else:
            row["duration"] = _grey(None, f"{label}: No duration provided.")

        # ── GitHub URL (live check) ───────────────────────────────────────────
        github = proj.get("github")
        if github and isinstance(github, str) and github.strip():
            log.info("Checking GitHub URL for %s: %s", label, github.strip())
            row["github"] = validate_url(github.strip(), label=f"{label} GitHub")
        else:
            row["github"] = _grey(None, f"{label}: No GitHub link provided.")

        # ── Description ───────────────────────────────────────────────────────
        row["description"] = _evaluate_description(proj.get("points") or {}, label)

        results.append(row)

    return results


def validate_skills(skills: Any) -> dict:
    """
    Validate the skills section.

    Accepts either:
        - A comma-separated string: "Python, Go, Rust, SQL"
        - A list: ["Python", "Go", "Rust", "SQL"]

    Returns invalid if empty/wrong type, grey if fewer than MIN_SKILLS items.
    """
    if not skills:
        return _fail(skills, "Skills section is missing or empty.")

    if isinstance(skills, str):
        items = [s.strip() for s in skills.split(",") if s.strip()]
    elif isinstance(skills, list):
        # Compute str(s).strip() once per element using walrus operator
        items = [t for s in skills if (t := str(s).strip())]
    else:
        return _fail(
            skills,
            f"Skills must be a comma-separated string or a list, got {type(skills).__name__}.",
        )

    if not items:
        return _fail(skills, "No skills found after parsing — the list appears to be empty.")

    if len(items) < MIN_SKILLS:
        return _grey(
            items,
            f"Only {len(items)} skill(s) listed — a more comprehensive list is strongly recommended.",
        )

    return _ok(items)


def validate_achievements(achievements: Any) -> dict:
    """
    Validate the achievements section.

    Expects: {"points": {"1": "...", "2": "...", ...}}
    At least 2 non-empty bullets are recommended.
    """
    if not achievements or not isinstance(achievements, dict):
        return _grey(achievements, "Achievements section is missing or not a dict.")

    points = achievements.get("points")
    if not points or not isinstance(points, dict):
        return _grey(achievements, "Achievements section has no 'points' dict.")

    items = [str(v).strip() for v in points.values() if v and str(v).strip()]
    if not items:
        return _grey(achievements, "Achievements 'points' dict contains no non-empty entries.")
    if len(items) < 2:
        return _grey(
            achievements,
            f"Only {len(items)} achievement bullet — consider adding more to strengthen the profile.",
        )

    return _ok(achievements)


def validate_responsibilities(responsibilities: Any) -> dict:
    """
    Validate positions of responsibility.

    Expects: {"points": {"1": "...", "2": "...", ...}}
    At least one non-empty bullet is required.
    """
    if not responsibilities or not isinstance(responsibilities, dict):
        return _grey(responsibilities, "Responsibilities section is missing or not a dict.")

    points = responsibilities.get("points")
    if not points or not isinstance(points, dict):
        return _grey(responsibilities, "Responsibilities section has no 'points' dict.")

    items = [str(v).strip() for v in points.values() if v and str(v).strip()]
    if not items:
        return _grey(responsibilities, "No non-empty responsibility entries found.")

    return _ok(responsibilities)


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------

def validate_resume(raw: dict) -> dict:
    """
    Run the full validation pipeline on a raw resume JSON dict.

    Returns a nested report dict; every leaf is a result node with
    "status" in {"valid", "invalid", "grey"}.
    """
    if not isinstance(raw, dict):
        raise TypeError(f"validate_resume() expects a dict, got {type(raw).__name__}.")

    log.info("=== Validation pipeline started ===")
    report: dict = {}

    # ── Personal details ──────────────────────────────────────────────────────
    log.info("Validating: name")
    report["name"] = validate_name(raw.get("name"))

    log.info("Validating: emails")
    emails = raw.get("emails") or []
    if isinstance(emails, str):
        emails = [emails]
    if not isinstance(emails, list):
        emails = []
    report["emails"] = (
        [validate_email(e) for e in emails]
        if emails
        else [_fail(None, "No email addresses provided.")]
    )

    log.info("Validating: phone_numbers")
    phones = raw.get("phone_numbers") or []
    if isinstance(phones, str):
        phones = [phones]
    if not isinstance(phones, list):
        phones = []
    report["phone_numbers"] = (
        [validate_phone(p) for p in phones]
        if phones
        else [_fail(None, "No phone numbers provided.")]
    )

    # ── URLs (optional fields — missing is acceptable) ───────────────────────
    url_fields = {
        "linkedin":   "LinkedIn",
        "github":     "GitHub",
        "leetcode":   "LeetCode",
        "codeforces": "Codeforces",
        "codechef":   "CodeChef",
        "portfolio":  "Portfolio",
    }
    report["urls"] = {}
    for field, label in url_fields.items():
        val = raw.get(field)
        if val and isinstance(val, str) and val.strip():
            log.info("Checking URL [%s]: %s", label, val.strip())
            report["urls"][field] = validate_url(val.strip(), label=label)
        else:
            report["urls"][field] = _ok(None, note=f"{label} not provided — optional field.")

    # ── Education ─────────────────────────────────────────────────────────────
    log.info("Validating: education")
    report["education"] = validate_education(raw.get("education"))

    # ── Experience ────────────────────────────────────────────────────────────
    log.info("Validating: experience")
    report["experience"] = validate_experience(raw.get("experience") or [])

    # ── Projects ──────────────────────────────────────────────────────────────
    log.info("Validating: projects")
    report["projects"] = validate_projects(raw.get("projects") or [])

    # ── Skills ────────────────────────────────────────────────────────────────
    log.info("Validating: skills")
    report["skills"] = validate_skills(raw.get("skills"))

    # ── Achievements ──────────────────────────────────────────────────────────
    log.info("Validating: achievements")
    report["achievements"] = validate_achievements(raw.get("achievements"))

    # ── Responsibilities ──────────────────────────────────────────────────────
    log.info("Validating: responsibilities")
    report["responsibilities"] = validate_responsibilities(raw.get("responsibilities"))

    log.info("=== Validation pipeline complete ===")
    return report


# ---------------------------------------------------------------------------
# Tri-state partitioner
# ---------------------------------------------------------------------------

def _collect_leaves(
    obj: Any,
    path: str = "",
) -> list[tuple[str, str, Any, dict]]:
    """
    Recursively walk a validation report tree and collect every leaf node.

    A leaf is any dict that contains the key "status".
    Keys starting with "_" (internal metadata) are skipped.

    Returns a list of (path, status, data, full_result_dict) tuples.
    """
    collected: list[tuple[str, str, Any, dict]] = []

    if isinstance(obj, dict) and "status" in obj:
        # This is a result leaf node
        collected.append((path, obj["status"], obj.get("data"), obj))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if key.startswith("_"):
                continue
            child_path = f"{path}.{key}" if path else key
            collected.extend(_collect_leaves(value, child_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            collected.extend(_collect_leaves(item, f"{path}[{idx}]"))

    return collected


def partition(report: dict) -> dict:
    """
    Convert a raw validation report into the tri-state output structure:
        validated_sections, invalid_sections, grey_area.

    Also returns a summary with counts.
    """
    validated_sections: dict = {}
    invalid_sections: dict   = {}
    grey_area: dict          = {}

    leaves = _collect_leaves(report)

    for path, status, data, result in leaves:
        base = {"path": path, "data": data}
        if status == "valid":
            validated_sections[path] = {**base, "note":  result.get("note", "")}
        elif status == "invalid":
            invalid_sections[path]   = {**base, "error": result.get("error", "Validation failed.")}
        else:
            grey_area[path]          = {**base, "note":  result.get("note", "Ambiguous or incomplete.")}

    total = len(leaves)
    return {
        "summary": {
            "total_checks":     total,
            "validated_count":  len(validated_sections),
            "invalid_count":    len(invalid_sections),
            "grey_area_count":  len(grey_area),
            "pass_rate":        round(len(validated_sections) / total * 100, 1) if total else 0.0,
        },
        "validated_sections": validated_sections,
        "invalid_sections":   invalid_sections,
        "grey_area":          grey_area,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(raw_json: dict) -> dict:
    """
    Full pipeline entry point.

    Runs validate_resume() then partition() and returns the tri-state output.

    Parameters
    ----------
    raw_json : dict
        Raw resume data as extracted by a parser / OCR system.

    Returns
    -------
    dict with keys:
        summary             — counts and pass_rate
        validated_sections  — fields that passed all checks
        invalid_sections    — fields with hard failures
        grey_area           — fields needing human review
    """
    report = validate_resume(raw_json)
    return partition(report)