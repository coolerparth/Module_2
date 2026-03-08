#!/usr/bin/env python3
"""
validation_engine.py
====================
Intelligent Validation Engine — Smart Resume Audit & Verification System

Validates raw extracted resume JSON and partitions results into three states:
    validated_sections  — clean, verified data ready for downstream scoring
    invalid_sections    — data that failed hard checks, with error messages
    grey_area           — ambiguous or incomplete data needing manual review

COUNTRY CONFIGURATION
---------------------
This engine is fully configurable per country. Phone number rules and
education level names differ by region — a UK resume has "a_levels" and
"gcse", while an Indian resume has "class10" and "class12".

Configuration priority (highest to lowest):
    1. Passed directly to run() / validate_resume()  ->  run(data, country="GB")
    2. Environment variable                          ->  RESUME_COUNTRY=GB
    3. configure() called at startup                 ->  configure("GB")
    4. Hard-coded default                            ->  "IN" (India)

Built-in country profiles
--------------------------
    IN  - India              US  - United States
    CA  - Canada             GB  - United Kingdom
    AE  - UAE                AU  - Australia
    DE  - Germany            SG  - Singapore
    CN  - China              GENERIC - any country (relaxed phone rules)

Adding a custom country:
    Call configure_from_file("my_country.json").
    See CountryProfile and PhoneRule docstrings for the JSON schema.

Public API
----------
    run(raw_json, country=None)            -> dict   (full pipeline)
    validate_resume(raw, country=None)     -> dict   (raw field report)
    partition(report)                      -> dict   (tri-state output)
    configure(country_code)                          (set global default)
    configure_from_file(path)                        (load custom JSON profile)
    list_countries()                       -> list   (all registered codes)
    get_active_country()                   -> str    (currently active code)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dateutil import parser as dateparser
from dateutil.parser import ParserError

# ---------------------------------------------------------------------------
# Module logger  (callers configure handlers — we never call basicConfig here)
# ---------------------------------------------------------------------------
log = logging.getLogger(__name__)


# ===========================================================================
# COUNTRY PROFILE SYSTEM
# ===========================================================================

@dataclass
class PhoneRule:
    """
    Describes one valid phone number format for a country.

    Attributes
    ----------
    country_prefix    : digit-only country calling code, e.g. "91" for India.
                        Use "" for bare-number-only rules.
    bare_digits       : total digits expected when NO country code is given.
    prefixed_digits   : total digits expected when country code IS included.
    core_valid_starts : string of allowed first digits of the core number
                        (after stripping country code and optional leading 0).
                        "" means no restriction.
    local_zero_strip  : if True, a leading 0 on the core is stripped before
                        checking (AU 0412-xxx, GB 07911-xxx, DE 030-xxx).
    description       : label used in error/note messages, e.g. "India (+91)".
    """
    country_prefix: str
    bare_digits: int
    prefixed_digits: int
    core_valid_starts: str
    local_zero_strip: bool = False
    description: str = ""


@dataclass
class CountryProfile:
    """
    Complete country-specific validation configuration.

    All other validators (name, email, dates, URL, etc.) are country-agnostic.
    Only phone_rules and education_levels change by country.

    Attributes
    ----------
    code              : ISO 3166-1 alpha-2, used as the registry key, e.g. "IN".
    name              : Human-readable country name.
    phone_rules       : List of PhoneRule objects.  A number is VALID if it
                        satisfies ANY one of the rules.
    education_levels  : Ordered list of education-level keys expected in the
                        resume's education dict. Missing levels are accepted.
    min_skills        : Minimum skills before a grey warning is raised.
    """
    code: str
    name: str
    phone_rules: list[PhoneRule]
    education_levels: list[str]
    min_skills: int = 3


# ---------------------------------------------------------------------------
# Built-in country profiles registry
# ---------------------------------------------------------------------------

def _build_profiles() -> dict[str, CountryProfile]:
    """Construct and return the registry of all built-in country profiles."""
    return {

        # ── India ─────────────────────────────────────────────────────────
        "IN": CountryProfile(
            code="IN", name="India",
            phone_rules=[
                PhoneRule(
                    country_prefix="91", bare_digits=10, prefixed_digits=12,
                    core_valid_starts="6789",
                    description="India (+91)",
                ),
            ],
            education_levels=["class10", "class12", "ug", "pg", "phd"],
        ),

        # ── United States ─────────────────────────────────────────────────
        "US": CountryProfile(
            code="US", name="United States",
            phone_rules=[
                PhoneRule(
                    country_prefix="1", bare_digits=10, prefixed_digits=11,
                    core_valid_starts="23456789",
                    description="US (+1)",
                ),
            ],
            education_levels=["high_school", "associates", "bachelors", "masters", "phd"],
        ),

        # ── Canada ────────────────────────────────────────────────────────
        "CA": CountryProfile(
            code="CA", name="Canada",
            phone_rules=[
                PhoneRule(
                    country_prefix="1", bare_digits=10, prefixed_digits=11,
                    core_valid_starts="23456789",
                    description="Canada (+1)",
                ),
            ],
            education_levels=["high_school", "associates", "bachelors", "masters", "phd"],
        ),

        # ── United Kingdom ────────────────────────────────────────────────
        # UK local dialling uses a leading 0: 07911-123456 (11 digits).
        # bare_digits=11 so the leading 0 is included; local_zero_strip
        # removes it before applying core_valid_starts check.
        "GB": CountryProfile(
            code="GB", name="United Kingdom",
            phone_rules=[
                PhoneRule(
                    country_prefix="44", bare_digits=11, prefixed_digits=12,
                    core_valid_starts="",
                    local_zero_strip=True,   # 07911… (11 digits) -> strip leading 0
                    description="UK (+44)",
                ),
            ],
            education_levels=["gcse", "a_levels", "bachelors", "masters", "phd"],
        ),

        # ── UAE ───────────────────────────────────────────────────────────
        # UAE has two valid formats: 9-digit mobile and 8-digit landline
        "AE": CountryProfile(
            code="AE", name="United Arab Emirates",
            phone_rules=[
                PhoneRule(
                    country_prefix="971", bare_digits=9, prefixed_digits=12,
                    core_valid_starts="5",
                    description="UAE mobile (+971)",
                ),
                PhoneRule(
                    country_prefix="971", bare_digits=8, prefixed_digits=11,
                    core_valid_starts="",
                    description="UAE landline (+971)",
                ),
            ],
            education_levels=["high_school", "bachelors", "masters", "phd"],
        ),

        # ── Australia ─────────────────────────────────────────────────────
        # AU local dialling uses a leading 0: 0412-345-678 (10 digits).
        # bare_digits=10 includes the leading 0; local_zero_strip removes it.
        "AU": CountryProfile(
            code="AU", name="Australia",
            phone_rules=[
                PhoneRule(
                    country_prefix="61", bare_digits=10, prefixed_digits=11,
                    core_valid_starts="",
                    local_zero_strip=True,   # 0412… (10 digits) -> strip leading 0
                    description="Australia (+61)",
                ),
            ],
            education_levels=["year12", "bachelors", "honours", "masters", "phd"],
        ),

        # ── Germany ───────────────────────────────────────────────────────
        # German number length varies: area code (2-5 digits) + subscriber
        # (3-10 digits). Local bare format includes a leading 0.
        # Three rules cover the most common total lengths: 11, 12, and 13.
        "DE": CountryProfile(
            code="DE", name="Germany",
            phone_rules=[
                PhoneRule(
                    country_prefix="49", bare_digits=11, prefixed_digits=12,
                    core_valid_starts="", local_zero_strip=True,
                    description="Germany (+49) 11-digit",
                ),
                PhoneRule(
                    country_prefix="49", bare_digits=12, prefixed_digits=13,
                    core_valid_starts="", local_zero_strip=True,
                    description="Germany (+49) 12-digit",
                ),
                PhoneRule(
                    country_prefix="49", bare_digits=13, prefixed_digits=14,
                    core_valid_starts="", local_zero_strip=True,
                    description="Germany (+49) 13-digit",
                ),
            ],
            education_levels=["abitur", "bachelor", "master", "phd"],
        ),

        # ── Singapore ─────────────────────────────────────────────────────
        "SG": CountryProfile(
            code="SG", name="Singapore",
            phone_rules=[
                PhoneRule(
                    country_prefix="65", bare_digits=8, prefixed_digits=10,
                    core_valid_starts="3689",
                    description="Singapore (+65)",
                ),
            ],
            education_levels=["o_levels", "a_levels", "bachelors", "masters", "phd"],
        ),

        # ── China ─────────────────────────────────────────────────────────
        "CN": CountryProfile(
            code="CN", name="China",
            phone_rules=[
                PhoneRule(
                    country_prefix="86", bare_digits=11, prefixed_digits=13,
                    core_valid_starts="1",
                    description="China (+86)",
                ),
            ],
            education_levels=["gaokao", "bachelors", "masters", "phd"],
        ),

        # ── Generic / International ───────────────────────────────────────
        # Accepts any number with 7–15 digits (ITU-T E.164 range)
        "GENERIC": CountryProfile(
            code="GENERIC", name="Generic / International",
            phone_rules=[
                PhoneRule(
                    country_prefix="", bare_digits=10, prefixed_digits=15,
                    core_valid_starts="",
                    description="International (E.164: 7-15 digits)",
                ),
            ],
            education_levels=["level_1", "level_2", "level_3", "level_4", "level_5"],
        ),
    }


_PROFILES: dict[str, CountryProfile] = _build_profiles()
_DEFAULT_COUNTRY: str = "IN"
_ENV_VAR: str = "RESUME_COUNTRY"


# ---------------------------------------------------------------------------
# Profile management helpers
# ---------------------------------------------------------------------------

def configure(country_code: str) -> None:
    """
    Set the global default country profile used when no country is passed to run().

    Parameters
    ----------
    country_code : ISO 3166-1 alpha-2 code, e.g. "GB". Case-insensitive.

    Raises
    ------
    ValueError  if code is not in the registry.
    """
    global _DEFAULT_COUNTRY
    code = country_code.strip().upper()
    if code not in _PROFILES:
        raise ValueError(
            f"Unknown country code '{code}'. "
            f"Registered codes: {sorted(_PROFILES)}. "
            "Use configure_from_file() to add a custom profile."
        )
    _DEFAULT_COUNTRY = code
    log.info("Active country profile set to: %s (%s)", code, _PROFILES[code].name)


def configure_from_file(path: str | Path) -> None:
    """
    Load a custom country profile from a JSON file and register it as the
    active default.

    JSON schema
    -----------
    {
      "code": "MY",
      "name": "Malaysia",
      "phone_rules": [
        {
          "country_prefix": "60",
          "bare_digits": 10,
          "prefixed_digits": 12,
          "core_valid_starts": "1",
          "local_zero_strip": false,
          "description": "Malaysia (+60)"
        }
      ],
      "education_levels": ["spm", "stpm", "diploma", "bachelors", "masters", "phd"],
      "min_skills": 3
    }

    Raises
    ------
    FileNotFoundError  if the file does not exist.
    ValueError         if required fields are missing or malformed.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Country config file not found: {p.resolve()}")

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in '{p}': {exc}") from exc

    _assert_valid_config(raw, source=str(p))

    code = raw["code"].strip().upper()
    rules = [
        PhoneRule(
            country_prefix   = str(r["country_prefix"]),
            bare_digits      = int(r["bare_digits"]),
            prefixed_digits  = int(r["prefixed_digits"]),
            core_valid_starts= str(r.get("core_valid_starts", "")),
            local_zero_strip = bool(r.get("local_zero_strip", False)),
            description      = str(r.get("description", f"{raw['name']} (+{r['country_prefix']})")),
        )
        for r in raw["phone_rules"]
    ]

    profile = CountryProfile(
        code             = code,
        name             = raw["name"],
        phone_rules      = rules,
        education_levels = [lvl.lower() for lvl in raw["education_levels"]],
        min_skills       = int(raw.get("min_skills", 3)),
    )

    _PROFILES[code] = profile
    global _DEFAULT_COUNTRY
    _DEFAULT_COUNTRY = code
    log.info("Custom country profile loaded and activated: %s (%s)", code, profile.name)


def _assert_valid_config(raw: dict, source: str) -> None:
    """Raise ValueError if a country config dict is missing required fields."""
    required = ["code", "name", "phone_rules", "education_levels"]
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(f"Country config '{source}' is missing required fields: {missing}")
    if not isinstance(raw["phone_rules"], list) or not raw["phone_rules"]:
        raise ValueError(f"Country config '{source}': 'phone_rules' must be a non-empty list.")
    rule_required = ["country_prefix", "bare_digits", "prefixed_digits"]
    for i, rule in enumerate(raw["phone_rules"]):
        mr = [k for k in rule_required if k not in rule]
        if mr:
            raise ValueError(f"Country config '{source}': phone_rules[{i}] missing: {mr}")
    if not isinstance(raw["education_levels"], list) or not raw["education_levels"]:
        raise ValueError(f"Country config '{source}': 'education_levels' must be a non-empty list.")


def _resolve_profile(country: str | None) -> CountryProfile:
    """
    Resolve the active CountryProfile using the priority chain:
        1. country argument (if given)
        2. RESUME_COUNTRY environment variable
        3. Module-level _DEFAULT_COUNTRY (set by configure())
        4. Hard-coded "IN"
    """
    code = (
        country.strip().upper()
        if country
        else os.environ.get(_ENV_VAR, _DEFAULT_COUNTRY).strip().upper()
    )
    if code not in _PROFILES:
        log.warning(
            "Unknown country code '%s' — falling back to GENERIC profile. "
            "Registered codes: %s",
            code, sorted(_PROFILES),
        )
        return _PROFILES["GENERIC"]
    return _PROFILES[code]


def list_countries() -> list[dict]:
    """Return all registered country profiles as a list of {code, name} dicts."""
    return [{"code": c, "name": p.name} for c, p in sorted(_PROFILES.items())]


def get_active_country() -> str:
    """Return the currently active default country code (env var or module default)."""
    return os.environ.get(_ENV_VAR, _DEFAULT_COUNTRY).strip().upper()


# ===========================================================================
# CONSTANTS & COMPILED PATTERNS  (fully country-agnostic)
# ===========================================================================

URL_TIMEOUT: int = 8
MAX_RETRIES: int = 1
MAX_NAME_LEN: int = 100
MIN_NAME_LEN: int = 3
MIN_BULLETS: int = 2
MIN_BULLET_WORDS: float = 5.0

# Email regex: local@domain.tld
# - Domain must NOT start with a dash
# - TLD must be letters only, minimum 2 chars
_EMAIL_RE = re.compile(
    r"^[\w.+\-]+"
    r"@"
    r"(?!-)"
    r"([\w][\w\-]*\.)+"
    r"[a-zA-Z]{2,}$"
)

# Duration split — matches the separator between start and end date tokens.
# Uses alternation so it NEVER splits on 't'/'o' inside month names
# (the old character-class [-to] bug that broke October, November, etc.)
_DURATION_SPLIT_RE = re.compile(
    r"\s+to\s+"             # word "to" with surrounding whitespace
    r"|\s*[\u2013\u2014]\s*" # en-dash or em-dash (unambiguous)
    r"|\s+-\s+"             # hyphen ONLY when surrounded by whitespace
)

_ONGOING_TOKENS: frozenset[str] = frozenset({
    "present", "current", "ongoing", "now",
    "till date", "till now", "today", "date",
})

_HEAD_BLOCKED: frozenset[int] = frozenset({403, 405, 501})


# ===========================================================================
# RESULT-NODE FACTORIES
# ===========================================================================

def _ok(data: Any, note: str = "") -> dict:
    return {"status": "valid",   "data": data, "note":  note}

def _fail(data: Any, error: str) -> dict:
    return {"status": "invalid", "data": data, "error": error}

def _grey(data: Any, note: str) -> dict:
    return {"status": "grey",    "data": data, "note":  note}


# ===========================================================================
# UTILITIES
# ===========================================================================

def _today() -> datetime:
    """Return current datetime. Called at runtime — never frozen at import."""
    return datetime.today()


def _parse_date(raw: str) -> datetime | None:
    """
    Parse a fuzzy date string into a naive datetime.
    Always strips tzinfo to prevent TypeError when comparing with _today().
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = dateparser.parse(
            raw, fuzzy=True, default=datetime(_today().year, 1, 1)
        )
        return dt.replace(tzinfo=None) if dt else None
    except (ParserError, OverflowError, ValueError, TypeError):
        return None


def _is_ongoing(token: str) -> bool:
    return token.strip().lower() in _ONGOING_TOKENS


def _years_between(start: datetime, end: datetime) -> float:
    return (end - start).days / 365.25


# ===========================================================================
# INDIVIDUAL VALIDATORS
# ===========================================================================

def validate_name(name: Any) -> dict:
    """
    Validate candidate name.

    Hard failures : missing/non-string, too short/long, contains digits,
                    single repeating character.
    Grey          : unusual characters, single word, no vowels.
    """
    if not name or not isinstance(name, str):
        return _fail(name, "Name is missing or not a string.")

    cleaned = name.strip()

    if len(cleaned) < MIN_NAME_LEN:
        return _fail(cleaned, f"Name too short — minimum {MIN_NAME_LEN} characters required.")
    if len(cleaned) > MAX_NAME_LEN:
        return _fail(cleaned, f"Name exceeds {MAX_NAME_LEN} characters — likely spam or malformed.")
    if re.search(r"[0-9]", cleaned):
        return _fail(cleaned, "Name contains digits — not allowed in a person's name.")

    alpha = cleaned.replace(" ", "").lower()
    if alpha and len(set(alpha)) == 1:
        return _fail(cleaned, "Name is a single repeated character — appears to be spam.")

    if re.search(r"[^a-zA-Z\s\-'.]", cleaned):
        return _grey(cleaned, "Name contains unusual characters; verify manually.")
    if len(cleaned.split()) < 2:
        return _grey(cleaned, "Name appears to be a single word; full name preferred.")
    if not re.search(r"[aeiouyAEIOUY]", cleaned):
        return _grey(cleaned, "Name contains no vowels — check for OCR errors or acronyms.")

    return _ok(cleaned)


def validate_email(email: Any) -> dict:
    """
    Validate a single email address.
    Checks: format, dash-leading domain, TLD length, consecutive dots.
    """
    if not email or not isinstance(email, str):
        return _fail(email, "Email is missing or not a string.")
    addr = email.strip()
    if not addr:
        return _fail(addr, "Email is empty after stripping whitespace.")
    if not _EMAIL_RE.match(addr):
        return _fail(addr, f"Email '{addr}' has an invalid format.")
    if ".." in addr:
        return _fail(addr, f"Email '{addr}' contains consecutive dots (..) — invalid.")
    return _ok(addr)


def validate_phone(phone: Any, profile: CountryProfile) -> dict:
    """
    Validate a phone number against the active country profile.

    Algorithm (for each PhoneRule in profile.phone_rules):
        1. Strip all non-digit characters.
        2. Check bare_digits  (no country code provided).
        3. Check prefixed_digits + correct country_prefix.
        4. If local_zero_strip=True, strip a leading 0 from core before
           checking core_valid_starts.
        5. A number is VALID if it satisfies ANY one rule.

    GENERIC profile uses ITU-T E.164 range (7-15 digits, no other rules).
    Numbers with 7-9 digits that match no rule are returned as GREY
    (possibly incomplete).
    Everything else is INVALID with a message listing all expected formats.
    """
    if not phone or not isinstance(phone, str):
        return _fail(phone, "Phone number is missing or not a string.")
    raw = phone.strip()
    if not raw:
        return _fail(raw, "Phone number is empty after stripping whitespace.")

    digits = re.sub(r"\D", "", raw)
    n = len(digits)

    # GENERIC profile: accept any E.164-range number
    if profile.code == "GENERIC":
        if 7 <= n <= 15:
            return _ok(raw, note=f"Accepted as international number ({n} digits, E.164 range).")
        return _fail(
            raw,
            f"Phone '{raw}' has {n} digits — E.164 standard requires 7-15 digits.",
        )

    for rule in profile.phone_rules:

        # ── Bare number (no country code) ────────────────────────────────
        if n == rule.bare_digits:
            core = digits
            if rule.local_zero_strip and core.startswith("0"):
                core = core[1:]
            if rule.core_valid_starts and core and core[0] not in rule.core_valid_starts:
                return _fail(
                    raw,
                    f"{profile.name} ({rule.description}): number must start with "
                    f"one of [{rule.core_valid_starts}] — got '{core[0]}'.",
                )
            return _ok(raw, note=f"{rule.description}: {rule.bare_digits}-digit number confirmed.")

        # ── Number with country code prefix ──────────────────────────────
        prefix = rule.country_prefix
        if prefix and n == rule.prefixed_digits and digits.startswith(prefix):
            core = digits[len(prefix):]
            if rule.local_zero_strip and core.startswith("0"):
                core = core[1:]
            if rule.core_valid_starts and core and core[0] not in rule.core_valid_starts:
                return _fail(
                    raw,
                    f"{profile.name} ({rule.description}): number must start with "
                    f"one of [{rule.core_valid_starts}] after country code "
                    f"+{prefix} — got '{core[0]}'.",
                )
            return _ok(raw, note=f"{rule.description} prefix detected; number confirmed.")

    # ── Possibly incomplete ───────────────────────────────────────────────
    if 7 <= n <= 9:
        return _grey(
            raw,
            f"Phone has only {n} digits — may be incomplete or missing "
            f"country code for {profile.name}.",
        )

    # ── No rule matched ───────────────────────────────────────────────────
    fmt_lines = "\n    ".join(
        f"{r.description}: {r.bare_digits} digits (bare) or "
        f"{r.prefixed_digits} digits with +{r.country_prefix}"
        for r in profile.phone_rules
    )
    return _fail(
        raw,
        f"Phone '{raw}' has {n} digits and matches no {profile.name} format.\n"
        f"    Expected:\n    {fmt_lines}",
    )


def validate_url(url: Any, label: str = "URL") -> dict:
    """
    Live-check URL reachability via HTTP.
    Tries HEAD first (no body); falls back to streaming GET only on 403/405/501.
    """
    if not url or not isinstance(url, str):
        return _fail(url, f"{label}: URL is missing or not a string.")
    url = url.strip()
    if not url:
        return _fail(url, f"{label}: URL is empty.")
    if not url.startswith(("http://", "https://")):
        return _fail(url, f"{label} '{url}' must begin with http:// or https://.")

    headers = {"User-Agent": "ResumeValidationBot/2.0"}

    for attempt in range(1 + MAX_RETRIES):
        try:
            with requests.head(
                url, timeout=URL_TIMEOUT, allow_redirects=True, headers=headers
            ) as r:
                status = r.status_code

            if status in _HEAD_BLOCKED:
                with requests.get(
                    url, timeout=URL_TIMEOUT, allow_redirects=True,
                    headers=headers, stream=True,
                ) as r2:
                    status = r2.status_code

            if status < 400:
                return _ok(url, note=f"Reachable — HTTP {status}.")
            return _fail(url, f"{label} '{url}' returned HTTP {status} — dead or broken link.")

        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES:
                return _fail(url, f"{label} '{url}' timed out after {URL_TIMEOUT}s.")
            log.warning("[%s] Timeout on attempt %d — retrying…", label, attempt + 1)
        except requests.exceptions.SSLError as exc:
            return _fail(url, f"{label} '{url}' SSL error: {exc}.")
        except requests.exceptions.ConnectionError as exc:
            if attempt == MAX_RETRIES:
                return _fail(url, f"{label} '{url}' connection error: {exc}.")
            log.warning("[%s] Connection error on attempt %d — retrying…", label, attempt + 1)
        except requests.exceptions.RequestException as exc:
            return _fail(url, f"{label} '{url}' request failed: {exc}.")

    return _fail(url, f"{label} '{url}' could not be verified.")  # pragma: no cover


# ---------------------------------------------------------------------------
# Duration validator
# ---------------------------------------------------------------------------

def validate_duration(
    duration: Any,
    section_label: str,
    *,
    allow_future_end: bool = False,
) -> dict:
    """
    Parse and validate a duration string such as 'Jan 2022 - Mar 2023'.

    Split logic uses alternation (_DURATION_SPLIT_RE) — never a character
    class — so month names containing 't' or 'o' (October, November,
    August, September, Toronto-based, etc.) are never split mid-word.

    Validation order:
        1. Not a string / blank       -> grey
        2. Single-year token          -> ok  (graduation year)
        3. Ongoing end token          -> ok  (active entry)
        4. Either/both unparseable    -> grey
        5. end < start                -> invalid  (hard temporal violation)
        6. start > today              -> grey     (possible upcoming role)
        7. end > today, not allowed   -> grey     (needs review)
        8. span > 40 years            -> grey     (suspiciously long)
        9. All checks passed          -> ok
    """
    if not duration or not isinstance(duration, str):
        return _grey(duration, f"{section_label}: Duration is missing or not a string.")
    stripped = duration.strip()
    if not stripped:
        return _grey(stripped, f"{section_label}: Duration is blank.")

    parts = _DURATION_SPLIT_RE.split(stripped, maxsplit=1)

    # Single-year entry (graduation year for class10/12/year12/abitur/etc.)
    if len(parts) == 1:
        if re.search(r"\b(19|20)\d{2}\b", parts[0]):
            return _ok(
                {"raw": stripped, "start": None, "end": parts[0].strip()},
                note=f"{section_label}: Single-year entry.",
            )
        return _grey(
            stripped,
            f"{section_label}: Duration '{stripped}' is ambiguous — no year identified.",
        )

    raw_start, raw_end = parts[0].strip(), parts[1].strip()

    # Ongoing / active entry
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
                "verify if this is an upcoming role.",
            )
        return _ok(
            {"raw": stripped, "start": start_dt.date().isoformat(), "end": "Present"},
            note=f"{section_label}: Active/ongoing entry.",
        )

    start_dt = _parse_date(raw_start)
    end_dt   = _parse_date(raw_end)

    if start_dt is None and end_dt is None:
        return _grey(stripped, f"{section_label}: Neither date could be parsed in '{stripped}'.")
    if start_dt is None:
        return _grey(stripped, f"{section_label}: Start date '{raw_start}' could not be parsed.")
    if end_dt is None:
        return _grey(stripped, f"{section_label}: End date '{raw_end}' could not be parsed.")

    payload = {
        "raw":   stripped,
        "start": start_dt.date().isoformat(),
        "end":   end_dt.date().isoformat(),
    }

    if end_dt < start_dt:
        return _fail(
            payload,
            f"{section_label}: End date '{raw_end}' is before start date '{raw_start}' "
            "— impossible timeline.",
        )
    if start_dt > _today():
        return _grey(
            payload,
            f"{section_label}: Start date '{raw_start}' is in the future — "
            "verify if this is an upcoming or incoming role.",
        )
    if end_dt > _today() and not allow_future_end:
        return _grey(
            payload,
            f"{section_label}: End date '{raw_end}' is in the future. "
            "Mark as ongoing if still active.",
        )
    if _years_between(start_dt, end_dt) > 40:
        return _grey(
            payload,
            f"{section_label}: Duration spans {_years_between(start_dt, end_dt):.1f} years "
            "— unusually long; verify manually.",
        )

    return _ok(payload)


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

def validate_education(education: Any, profile: CountryProfile) -> dict:
    """
    Validate all education levels defined in the active country profile.

    The only country-specific part is profile.education_levels.
    Grade accepts any type (str, int, float) because CGPA is often a float.
    """
    if not education or not isinstance(education, dict):
        return _fail(education, "Education section is missing or not a dict.")

    results: dict = {}
    for level in profile.education_levels:
        entry = education.get(level)

        if entry is None:
            results[level] = _ok(None, note=f"'{level}' not provided — acceptable.")
            continue
        if not isinstance(entry, dict):
            results[level] = _fail(
                entry,
                f"Education entry '{level}' must be a dict, got {type(entry).__name__}.",
            )
            continue

        row: dict = {}

        degree = entry.get("degree")
        row["degree"] = (
            _ok(degree.strip())
            if degree and isinstance(degree, str) and len(degree.strip()) >= 2
            else _fail(degree, f"Degree for '{level}' is missing or too short.")
        )

        institution = entry.get("institution")
        row["institution"] = (
            _ok(institution.strip())
            if institution and isinstance(institution, str) and len(institution.strip()) >= 2
            else _fail(institution, f"Institution for '{level}' is missing or too short.")
        )

        # Enrolled students may have a future end date
        row["duration"] = validate_duration(
            entry.get("duration"), f"Education[{level}]", allow_future_end=True
        )

        # Accept any grade type (float CGPA, int percentage, str letter-grade)
        grade = entry.get("grade")
        grade_str = str(grade).strip() if grade is not None else ""
        row["grade"] = (
            _ok(grade_str)
            if grade_str and grade_str.lower() not in ("none", "")
            else _grey(grade, f"Grade for '{level}' is not provided.")
        )

        results[level] = row

    return results


# ---------------------------------------------------------------------------
# Description / bullet heuristic
# ---------------------------------------------------------------------------

def _evaluate_description(points: Any, label: str) -> dict:
    """Assess the richness of bullet-point descriptions."""
    if not isinstance(points, dict) or not points:
        return _grey(points, f"{label}: No description bullets provided.")

    bullets: list[str] = []
    for v in points.values():
        t = str(v).strip()
        if t:
            bullets.append(t)

    count = len(bullets)
    if count == 0:
        return _grey(points, f"{label}: All description bullets are empty.")

    avg_words = sum(len(b.split()) for b in bullets) / count

    if count >= MIN_BULLETS and avg_words >= MIN_BULLET_WORDS:
        return _ok(points)
    if count >= MIN_BULLETS:
        return _grey(
            points,
            f"{label}: Bullets present but very short "
            f"(avg {avg_words:.1f} words/bullet) — lacks technical depth.",
        )
    if avg_words >= 10:
        return _grey(points, f"{label}: Only {count} bullet — consider expanding to multiple.")
    return _grey(points, f"{label}: Only {count} short bullet(s) — lacks detail and depth.")


# ---------------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------------

def validate_experience(experience: Any) -> list:
    """
    Validate work experience entries.
    Guards against non-dict list items.
    Detects cross-entry timeline overlaps.
    """
    if not experience:
        return []
    if not isinstance(experience, list):
        return [_fail(experience, "Experience section must be a list.")]

    results: list[dict] = []
    parsed_ranges: list[tuple[datetime, datetime, str]] = []

    for i, exp in enumerate(experience):
        slot = f"Experience[{i}]"

        if not isinstance(exp, dict):
            results.append(
                _fail(exp, f"{slot}: Entry must be a dict, got {type(exp).__name__}.")
            )
            continue

        role_str = str(exp.get("role", "Unknown Role")).strip() or "Unknown Role"
        label = f"Experience[{i}] ({role_str})"
        row: dict = {"_label": label}

        role = exp.get("role")
        rs = str(role).strip() if role else ""
        row["role"] = (
            _ok(rs) if len(rs) >= 2
            else _fail(role, f"{label}: Role is missing or too short.")
        )

        company = exp.get("company")
        cs = str(company).strip() if company else ""
        row["company"] = (
            _ok(cs) if len(cs) >= 2
            else _fail(company, f"{label}: Company is missing or too short.")
        )

        raw_start = str(exp.get("start", "")).strip()
        raw_end   = str(exp.get("end",   "")).strip()

        if raw_start and raw_end:
            dur = validate_duration(
                f"{raw_start} - {raw_end}", label, allow_future_end=False
            )
            row["duration"] = dur
            if dur["status"] == "valid":
                d = dur["data"]
                s_dt = _parse_date(d.get("start") or "")
                e_dt = (
                    _parse_date(d["end"]) if d.get("end") and d["end"] != "Present"
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
            row["duration"] = _grey(None, f"{label}: Both start and end dates are missing.")

        row["description"] = _evaluate_description(exp.get("points") or {}, label)
        results.append(row)

    # Cross-entry overlap detection (O(n^2), n < 20 for resumes — fine)
    n = len(parsed_ranges)
    for i in range(n):
        s1, e1, lbl1 = parsed_ranges[i]
        for j in range(i + 1, n):
            s2, e2, lbl2 = parsed_ranges[j]
            if s1 < e2 and s2 < e1:
                log.warning("Timeline overlap: %s overlaps %s", lbl1, lbl2)
                for row in results:
                    if row.get("_label") in (lbl1, lbl2):
                        row["timeline_overlap"] = _grey(
                            None,
                            f"Timeline overlap detected between {lbl1} and {lbl2} "
                            "— verify manually.",
                        )

    return results


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def validate_projects(projects: Any) -> list:
    """Validate project entries. Guards against non-dict items. Live-checks GitHub URLs."""
    if not projects:
        return []
    if not isinstance(projects, list):
        return [_fail(projects, "Projects section must be a list.")]

    results: list[dict] = []
    for i, proj in enumerate(projects):
        slot = f"Project[{i}]"
        if not isinstance(proj, dict):
            results.append(
                _fail(proj, f"{slot}: Entry must be a dict, got {type(proj).__name__}.")
            )
            continue

        proj_name = str(proj.get("name", "Unnamed")).strip() or "Unnamed"
        label = f"Project[{i}] ({proj_name})"
        row: dict = {"_label": label}

        name = proj.get("name")
        ns = str(name).strip() if name else ""
        row["name"] = (
            _ok(ns) if len(ns) >= 2
            else _fail(name, f"{label}: Project name is missing or too short.")
        )

        raw_dur = proj.get("duration")
        row["duration"] = (
            validate_duration(raw_dur, label, allow_future_end=False)
            if raw_dur
            else _grey(None, f"{label}: No duration provided.")
        )

        github = proj.get("github")
        if github and isinstance(github, str) and github.strip():
            log.info("Checking GitHub URL for %s: %s", label, github.strip())
            row["github"] = validate_url(github.strip(), label=f"{label} GitHub")
        else:
            row["github"] = _grey(None, f"{label}: No GitHub link provided.")

        row["description"] = _evaluate_description(proj.get("points") or {}, label)
        results.append(row)

    return results


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def validate_skills(skills: Any, profile: CountryProfile) -> dict:
    """
    Validate the skills section. Accepts comma-separated string or list.
    Minimum threshold comes from the active country profile.
    """
    if not skills:
        return _fail(skills, "Skills section is missing or empty.")

    if isinstance(skills, str):
        items = [s.strip() for s in skills.split(",") if s.strip()]
    elif isinstance(skills, list):
        items = [t for s in skills if (t := str(s).strip())]
    else:
        return _fail(
            skills,
            f"Skills must be a comma-separated string or a list, got {type(skills).__name__}.",
        )

    if not items:
        return _fail(skills, "No skills found after parsing — list appears empty.")
    if len(items) < profile.min_skills:
        return _grey(
            items,
            f"Only {len(items)} skill(s) listed — "
            f"at least {profile.min_skills} recommended for {profile.name}.",
        )

    return _ok(items)


# ---------------------------------------------------------------------------
# Achievements & Responsibilities
# ---------------------------------------------------------------------------

def validate_achievements(achievements: Any) -> dict:
    if not achievements or not isinstance(achievements, dict):
        return _grey(achievements, "Achievements section is missing or not a dict.")
    points = achievements.get("points")
    if not points or not isinstance(points, dict):
        return _grey(achievements, "Achievements section has no 'points' dict.")
    items = [str(v).strip() for v in points.values() if v and str(v).strip()]
    if not items:
        return _grey(achievements, "Achievements 'points' contains no non-empty entries.")
    if len(items) < 2:
        return _grey(achievements, f"Only {len(items)} achievement bullet — consider adding more.")
    return _ok(achievements)


def validate_responsibilities(responsibilities: Any) -> dict:
    if not responsibilities or not isinstance(responsibilities, dict):
        return _grey(responsibilities, "Responsibilities section is missing or not a dict.")
    points = responsibilities.get("points")
    if not points or not isinstance(points, dict):
        return _grey(responsibilities, "Responsibilities section has no 'points' dict.")
    items = [str(v).strip() for v in points.values() if v and str(v).strip()]
    if not items:
        return _grey(responsibilities, "No non-empty responsibility entries found.")
    return _ok(responsibilities)


# ===========================================================================
# TOP-LEVEL PIPELINE
# ===========================================================================

def validate_resume(raw: dict, country: str | None = None) -> dict:
    """
    Run the full validation pipeline on a raw resume JSON dict.

    Parameters
    ----------
    raw     : raw resume data dict from the extraction stage.
    country : ISO code override, e.g. "GB", "US", "AE".
              None -> RESUME_COUNTRY env var -> module default -> "IN".

    Returns
    -------
    Nested report dict; every leaf node has "status" in {valid, invalid, grey}.
    """
    if not isinstance(raw, dict):
        raise TypeError(f"validate_resume() expects a dict, got {type(raw).__name__}.")

    profile = _resolve_profile(country)
    log.info("=== Validation pipeline started [country=%s] ===", profile.code)

    report: dict = {}

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
        if emails else [_fail(None, "No email addresses provided.")]
    )

    log.info("Validating: phone_numbers")
    phones = raw.get("phone_numbers") or []
    if isinstance(phones, str):
        phones = [phones]
    if not isinstance(phones, list):
        phones = []
    report["phone_numbers"] = (
        [validate_phone(p, profile) for p in phones]
        if phones else [_fail(None, "No phone numbers provided.")]
    )

    log.info("Validating: URLs")
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

    log.info("Validating: education")
    report["education"] = validate_education(raw.get("education"), profile)

    log.info("Validating: experience")
    report["experience"] = validate_experience(raw.get("experience") or [])

    log.info("Validating: projects")
    report["projects"] = validate_projects(raw.get("projects") or [])

    log.info("Validating: skills")
    report["skills"] = validate_skills(raw.get("skills"), profile)

    log.info("Validating: achievements")
    report["achievements"] = validate_achievements(raw.get("achievements"))

    log.info("Validating: responsibilities")
    report["responsibilities"] = validate_responsibilities(raw.get("responsibilities"))

    # Internal metadata — prefixed with _ so _collect_leaves skips it
    report["_meta"] = {"country": profile.code, "country_name": profile.name}

    log.info("=== Validation pipeline complete [country=%s] ===", profile.code)
    return report


# ===========================================================================
# TRI-STATE PARTITIONER
# ===========================================================================

def _collect_leaves(obj: Any, path: str = "") -> list[tuple[str, str, Any, dict]]:
    """Recursively collect every result-node leaf from the validation report."""
    collected: list[tuple[str, str, Any, dict]] = []

    if isinstance(obj, dict) and "status" in obj:
        collected.append((path, obj["status"], obj.get("data"), obj))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if key.startswith("_"):
                continue
            child = f"{path}.{key}" if path else key
            collected.extend(_collect_leaves(value, child))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            collected.extend(_collect_leaves(item, f"{path}[{idx}]"))

    return collected


def partition(report: dict) -> dict:
    """Convert a raw validation report into the tri-state output structure."""
    validated: dict = {}
    invalid:   dict = {}
    grey:      dict = {}

    leaves = _collect_leaves(report)

    for path, status, data, result in leaves:
        base = {"path": path, "data": data}
        if status == "valid":
            validated[path] = {**base, "note":  result.get("note", "")}
        elif status == "invalid":
            invalid[path]   = {**base, "error": result.get("error", "Validation failed.")}
        else:
            grey[path]      = {**base, "note":  result.get("note", "Ambiguous or incomplete.")}

    total = len(leaves)
    meta  = report.get("_meta", {})

    return {
        "meta": {
            "country":      meta.get("country", "UNKNOWN"),
            "country_name": meta.get("country_name", "Unknown"),
            "validated_at": _today().isoformat(timespec="seconds"),
        },
        "summary": {
            "total_checks":    total,
            "validated_count": len(validated),
            "invalid_count":   len(invalid),
            "grey_area_count": len(grey),
            "pass_rate":       round(len(validated) / total * 100, 1) if total else 0.0,
        },
        "validated_sections": validated,
        "invalid_sections":   invalid,
        "grey_area":          grey,
    }


# ===========================================================================
# PUBLIC ENTRY POINT
# ===========================================================================

def run(raw_json: dict, country: str | None = None) -> dict:
    """
    Full pipeline entry point.

    Parameters
    ----------
    raw_json : dict   — raw resume data from the extraction stage.
    country  : str    — ISO 3166-1 alpha-2 code, e.g. "GB", "US", "IN".
                        Overrides env var and module-level default.
                        None = use env var RESUME_COUNTRY or configured default.

    Returns
    -------
    dict with keys:
        meta                — country used and validation timestamp
        summary             — total_checks, counts, pass_rate
        validated_sections  — fields that passed all checks
        invalid_sections    — fields with hard failures
        grey_area           — fields needing human review
    """
    report = validate_resume(raw_json, country=country)
    return partition(report)
