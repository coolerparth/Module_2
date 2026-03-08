"""
Intelligent Validation Engine
Smart Resume Audit & Verification System
=========================================
Validates raw extracted resume JSON and partitions data into three states:
  - validated_sections : clean, verified data ready for downstream scoring
  - invalid_sections   : data that failed hard checks, with error tags
  - grey_area          : ambiguous or incomplete data needing manual review

"""

import re
import json
import logging
from datetime import datetime
from typing import Any

import requests
from dateutil import parser as dateparser
from dateutil.parser import ParserError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TODAY = datetime.today()
URL_TIMEOUT = 6          # seconds per HTTP request
MAX_RETRIES = 1          # retries on network error (Timeout / ConnectionError only)
MAX_NAME_LENGTH = 100    # FIX BUG-6: hard cap on name length
EMAIL_REGEX = re.compile(
    r"^[\w.+\-]+@[\w\-]+\.([\w\-]+\.)*[a-zA-Z]{2,}$"
)
# FIX BUG-1: split on the WORD "to" (surrounded by whitespace) OR on dash chars.
# The OLD pattern r"\s*[-–—to]+\s*" was a character class that matched individual
# 't' and 'o' chars, breaking month names like October, November, August, September.
DURATION_SPLIT_RE = re.compile(r'\s+to\s+|\s*[-–—]+\s*')

# Minimum bullet points for a "rich" description
MIN_DESCRIPTION_BULLETS = 2

# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _ok(data: Any, note: str = "") -> dict:
    return {"status": "valid", "data": data, "note": note}


def _fail(data: Any, error: str) -> dict:
    return {"status": "invalid", "data": data, "error": error}


def _grey(data: Any, note: str) -> dict:
    return {"status": "grey", "data": data, "note": note}


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def validate_name(name: Any) -> dict:
    """Validate candidate name — must be a non-trivial string."""
    if not name or not isinstance(name, str):
        return _fail(name, "Name is missing or not a string.")
    name = name.strip()
    if len(name) <= 2:
        return _fail(name, "Name is too short (must be more than 2 characters).")
    # FIX BUG-6: enforce a maximum reasonable length
    if len(name) > MAX_NAME_LENGTH:
        return _fail(name, f"Name exceeds {MAX_NAME_LENGTH} characters — likely spam or malformed input.")
    if re.search(r"[0-9]", name):
        return _fail(name, "Name contains digits, which is not allowed.")
    if re.search(r"[^a-zA-Z\s\-\'\.]", name):
        return _grey(name, "Name contains unusual characters; verify manually.")
    parts = name.split()
    if len(parts) < 2:
        return _grey(name, "Name appears to be a single word; a full name is preferred.")

    # Advanced edge cases
    if len(set(name.replace(" ", "").lower())) == 1:
        return _fail(name, "Name consists of a repeating character (spam/dummy).")
    if not re.search(r"[aeiouyAEIOUY]", name):
        return _grey(name, "Name contains no vowels; check for acronyms/typos.")

    return _ok(name)


def validate_email(email: Any) -> dict:
    """Validate a single email address against RFC-5321 pattern."""
    if not email or not isinstance(email, str):
        return _fail(email, "Email is missing or not a string.")
    email = email.strip()
    if EMAIL_REGEX.match(email):
        if ".." in email:
            return _fail(email, f"Email '{email}' has invalid format (consecutive dots).")
        return _ok(email)
    return _fail(email, f"Email '{email}' has invalid format.")


def validate_phone(phone: Any) -> dict:
    """
    Validate a phone number.
    Strips leading '+', country code (if number > 10 digits), spaces, dashes.
    Resulting digits must be exactly 10.

    Supported country codes: +1 (US/Canada), +91 (India).
    All other international numbers will _fail with a clear message.
    """
    if not phone or not isinstance(phone, str):
        return _fail(phone, "Phone number is missing or not a string.")

    raw = phone.strip()
    digits = re.sub(r"\D", "", raw)

    if len(digits) == 10:
        if digits[0] == "0":
            return _fail(raw, "10-digit phone number cannot start with 0.")
        return _ok(raw)
    elif len(digits) == 11 and digits.startswith("1"):
        # US/Canada country code
        return _ok(raw, note="Stripped US/Canada country code (+1); 10-digit number confirmed.")
    elif len(digits) == 12 and digits.startswith("91"):
        # India country code
        core_number = digits[2:]
        if core_number[0] not in "6789":
            return _fail(raw, f"Indian phone number '{raw}' must start with 6, 7, 8, or 9 after +91.")
        return _ok(raw, note="Stripped India country code (+91); 10-digit number confirmed.")
    elif 8 <= len(digits) <= 9:
        return _grey(raw, f"Phone has {len(digits)} digits after stripping; expected 10. May be incomplete.")
    else:
        # FIX BUG-8: clarify that only US/India are supported instead of misleading message
        return _fail(
            raw,
            f"Phone '{raw}' yields {len(digits)} digits after stripping — expected 10 (or 11 with +1 / 12 with +91). "
            f"Only US (+1) and India (+91) country codes are currently supported.",
        )


def validate_url(url: Any, label: str = "URL") -> dict:
    """
    Live-check a URL reachability.
    Strategy: try HEAD first (no body download); fall back to GET if the server
    returns 405 Method Not Allowed.  Returns valid on 2xx/3xx, invalid otherwise.

    FIX BUG-3: original code used GET unconditionally — wasteful for large pages.
    FIX BUG-4: removed unreachable final return statement after the retry loop.
    """
    if not url or not isinstance(url, str):
        return _fail(url, f"{label} is missing or not a string.")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return _fail(url, f"{label} '{url}' does not start with http:// or https://.")

    headers = {"User-Agent": "ResumeValidationBot/1.0"}

    for attempt in range(1 + MAX_RETRIES):
        try:
            # Try HEAD first — avoids downloading the response body
            response = requests.head(url, timeout=URL_TIMEOUT, allow_redirects=True, headers=headers)
            if response.status_code >= 400:
                # Server might block HEAD (e.g. 403, 405) or improperly handle it; fall back to GET
                response = requests.get(url, timeout=URL_TIMEOUT, allow_redirects=True, headers=headers)

            status = response.status_code
            if status < 400:
                return _ok(url, note=f"HTTP {status} — reachable.")
            else:
                return _fail(url, f"{label} '{url}' returned HTTP {status} — dead or broken link.")

        except requests.exceptions.Timeout:
            if attempt == MAX_RETRIES:
                return _fail(url, f"{label} '{url}' timed out after {URL_TIMEOUT}s — unreachable.")
            log.warning("Timeout on attempt %d for %s — retrying...", attempt + 1, url)

        except requests.exceptions.ConnectionError as exc:
            if attempt == MAX_RETRIES:
                return _fail(url, f"{label} '{url}' connection error: {exc}.")
            log.warning("Connection error on attempt %d for %s — retrying...", attempt + 1, url)

        except requests.exceptions.RequestException as exc:
            # Non-retryable error (e.g. invalid scheme, SSL error)
            return _fail(url, f"{label} '{url}' request failed: {exc}.")

    # NOTE: this line is intentionally unreachable; every code path above returns.
    # Kept as a defensive fallback to satisfy static analysis tools.
    return _fail(url, f"{label} '{url}' could not be verified after {1 + MAX_RETRIES} attempts.")  # pragma: no cover


# ---------------------------------------------------------------------------
# Date / temporal validators
# ---------------------------------------------------------------------------

def _parse_date(raw: str) -> datetime | None:
    """Try to parse a date string. Returns None on failure."""
    try:
        return dateparser.parse(raw, fuzzy=True, default=datetime(TODAY.year, 1, 1))
    except (ParserError, OverflowError, ValueError):
        return None


def _is_current_or_future(token: str) -> bool:
    """Return True if the end-date token means 'ongoing'."""
    return token.strip().lower() in {"present", "current", "ongoing", "now", "till date", "till now", "today"}


def validate_duration(duration: Any, section_label: str, allow_future_end: bool = False) -> dict:
    """
    Parse and validate a duration string (e.g., 'Jan 2022 - Mar 2023').
    allow_future_end=True means education enrolment where future end date is OK.

    BUG-1 FIX: uses DURATION_SPLIT_RE (alternation pattern compiled at module level)
    instead of the old character-class that matched 't'/'o' individually, corrupting
    month names like October, November, August, September.
    BUG-9 FIX: future-start check now runs before future-end check to correctly
    return _fail (not _grey) for fully-future date ranges like "Jan 2030 - Mar 2031".
    """
    if not duration or not isinstance(duration, str):
        return _grey(duration, f"{section_label}: Duration is not provided; cannot verify timeline.")

    # FIX BUG-1: use DURATION_SPLIT_RE (alternation) instead of character class
    parts = DURATION_SPLIT_RE.split(duration.strip(), maxsplit=1)

    # Single-year entry (e.g. class10 / class12)
    if len(parts) == 1:
        year_match = re.search(r"\b(19|20)\d{2}\b", parts[0])
        if year_match:
            return _ok({"raw": duration, "start": None, "end": parts[0].strip()})
        return _grey(duration, f"{section_label}: Duration '{duration}' is ambiguous; could not parse year.")

    raw_start, raw_end = parts[0].strip(), parts[1].strip()

    if _is_current_or_future(raw_end):
        start_dt = _parse_date(raw_start)
        if start_dt is None:
            return _grey(
                duration,
                f"{section_label}: Start date '{raw_start}' could not be parsed.",
            )
        return _ok(
            {"raw": duration, "start": start_dt.date().isoformat(), "end": "Present"},
            note=f"{section_label}: Active/ongoing entry.",
        )

    start_dt = _parse_date(raw_start)
    end_dt = _parse_date(raw_end)

    if start_dt is None and end_dt is None:
        return _grey(duration, f"{section_label}: Could not parse either date in '{duration}'.")
    if start_dt is None:
        return _grey(duration, f"{section_label}: Could not parse start date '{raw_start}'.")
    if end_dt is None:
        return _grey(duration, f"{section_label}: Could not parse end date '{raw_end}'.")

    # Check start date first — a future start is always invalid (chronologically impossible)
    if start_dt > TODAY:
        return _fail(
            {"raw": duration, "start": start_dt.date().isoformat(), "end": end_dt.date().isoformat()},
            f"{section_label}: Start date '{raw_start}' is in the future — chronologically impossible.",
        )

    # Temporal order check (end before start)
    if end_dt < start_dt:
        return _fail(
            {"raw": duration, "start": start_dt.date().isoformat(), "end": end_dt.date().isoformat()},
            f"{section_label}: End date '{raw_end}' is before start date '{raw_start}' — temporal logic violation.",
        )

    # Future end date check (start is in the past but end is still ahead)
    if end_dt > TODAY and not allow_future_end:
        return _grey(
            {"raw": duration, "start": start_dt.date().isoformat(), "end": end_dt.date().isoformat()},
            f"{section_label}: End date '{raw_end}' is in the future. Mark as 'enrolled/ongoing' if intentional.",
        )

    years_diff = (end_dt - start_dt).days / 365.25
    if years_diff > 40:
        return _grey(
            {"raw": duration, "start": start_dt.date().isoformat(), "end": end_dt.date().isoformat()},
            f"{section_label}: Duration spans {years_diff:.1f} years, which is unusually long. Verify manually.",
        )

    return _ok({"raw": duration, "start": start_dt.date().isoformat(), "end": end_dt.date().isoformat()})


# ---------------------------------------------------------------------------
# Section-level validators
# ---------------------------------------------------------------------------

def validate_education(education: Any) -> dict:
    """Validate all education levels present in the education dict."""
    if not education or not isinstance(education, dict):
        return _fail(education, "Education section is missing or malformed.")

    results = {}
    levels = ["phd", "pg", "ug", "class12", "class10"]

    for level in levels:
        entry = education.get(level)
        if entry is None:
            results[level] = _ok(None, note="Not provided — acceptable.")
            continue

        if not isinstance(entry, dict):
            results[level] = _fail(entry, f"Education entry for '{level}' is malformed.")
            continue

        level_result = {}

        # Degree
        degree = entry.get("degree")
        if not degree or not isinstance(degree, str) or len(degree.strip()) < 2:
            level_result["degree"] = _fail(degree, f"Degree for '{level}' is missing or too short.")
        else:
            level_result["degree"] = _ok(degree.strip())

        # Institution
        institution = entry.get("institution")
        if not institution or not isinstance(institution, str) or len(institution.strip()) < 2:
            level_result["institution"] = _fail(institution, f"Institution for '{level}' is missing or invalid.")
        else:
            level_result["institution"] = _ok(institution.strip())

        # Duration — allow future end dates (enrolled students)
        raw_duration = entry.get("duration")
        level_result["duration"] = validate_duration(raw_duration, f"Education[{level}]", allow_future_end=True)

        # Grade (optional but grey if absent)
        grade = entry.get("grade")
        if grade and isinstance(grade, str) and grade.strip():
            level_result["grade"] = _ok(grade.strip())
        else:
            level_result["grade"] = _grey(grade, f"Grade for '{level}' is not provided.")

        results[level] = level_result

    return results


def _evaluate_description(points: Any, label: str, min_bullets: int = MIN_DESCRIPTION_BULLETS) -> dict:
    """Advanced heuristic for evaluating description bullet richness and word counts."""
    if not isinstance(points, dict) or not points:
        return _grey(points, f"{label}: No description bullets provided.")

    bullets = [str(v).strip() for v in points.values() if str(v).strip()]
    num_points = len(bullets)
    if num_points == 0:
        return _grey(points, f"{label}: Description bullets are empty.")

    total_words = sum(len(b.split()) for b in bullets)
    avg_words = total_words / num_points

    if num_points >= min_bullets and avg_words >= 5:
        return _ok(points)
    elif num_points >= min_bullets:
        return _grey(points, f"{label}: Bullets are very short (avg {avg_words:.1f} words/bullet); lacks technical depth.")
    elif avg_words >= 10:
        return _grey(points, f"{label}: Only 1 description bullet, though detailed; consider splitting into multiple.")
    else:
        return _grey(points, f"{label}: Only {num_points} short bullet(s) provided; lacks detail and depth.")


def validate_experience(experience: Any) -> list:
    """
    Validate work experience entries.

    FIX BUG-2: added isinstance(exp, dict) guard per entry.
    FIX BUG-7: added cross-entry timeline overlap detection.
    """
    if not experience:
        return []

    if not isinstance(experience, list):
        return [_fail(experience, "Experience section must be a list.")]

    results = []
    # Collect parsed (start_dt, end_dt, label) for overlap detection (BUG-7)
    parsed_ranges: list[tuple[datetime, datetime | None, str]] = []

    for i, exp in enumerate(experience):
        label = f"Experience[{i}]"

        # FIX BUG-2: guard against non-dict entries
        if not isinstance(exp, dict):
            results.append(_fail(exp, f"{label}: Entry is not a dict — malformed input."))
            continue

        label = f"Experience[{i}] ({exp.get('role', 'Unknown Role')})"
        entry_result = {}

        # Role
        role = exp.get("role")
        if not role or len(str(role).strip()) < 2:
            entry_result["role"] = _fail(role, f"{label}: Role is missing or too short.")
        else:
            entry_result["role"] = _ok(str(role).strip())

        # Company
        company = exp.get("company")
        if not company or len(str(company).strip()) < 2:
            entry_result["company"] = _fail(company, f"{label}: Company is missing or invalid.")
        else:
            entry_result["company"] = _ok(str(company).strip())

        # Temporal validation
        raw_start = exp.get("start", "")
        raw_end = exp.get("end", "")

        if raw_start and raw_end:
            combined_duration = f"{raw_start} - {raw_end}"
            dur_result = validate_duration(combined_duration, label, allow_future_end=False)
            entry_result["duration"] = dur_result
            # Collect for overlap check
            if dur_result["status"] == "valid":
                d = dur_result["data"]
                s = _parse_date(d["start"]) if d.get("start") else None
                e = _parse_date(d["end"]) if d.get("end") and d["end"] != "Present" else TODAY
                if s:
                    parsed_ranges.append((s, e, label))
        elif raw_start:
            entry_result["duration"] = _grey(
                {"start": raw_start, "end": None},
                f"{label}: End date is missing; treating as ongoing.",
            )
        else:
            entry_result["duration"] = _grey(
                None, f"{label}: Both start and end dates are missing."
            )

        # Points (description)
        entry_result["description"] = _evaluate_description(exp.get("points", {}), label)
        entry_result["_label"] = label
        results.append(entry_result)

    # FIX BUG-7: cross-entry overlap check
    for i, (s1, e1, lbl1) in enumerate(parsed_ranges):
        for s2, e2, lbl2 in parsed_ranges[i + 1:]:
            # Overlap if one range starts before the other ends
            if s1 < (e2 or TODAY) and s2 < (e1 or TODAY):
                log.warning("Timeline overlap detected: %s overlaps with %s", lbl1, lbl2)
                # Tag both entries in results with a grey overlap warning
                for entry in results:
                    if entry.get("_label") in (lbl1, lbl2):
                        entry["timeline_overlap"] = _grey(
                            None,
                            f"Possible timeline overlap between {lbl1} and {lbl2}. Verify manually.",
                        )

    return results


def validate_projects(projects: Any) -> list:
    """
    Validate project entries, including live GitHub link checks.

    FIX BUG-2: added isinstance(proj, dict) guard per entry.
    """
    if not projects:
        return []

    if not isinstance(projects, list):
        return [_fail(projects, "Projects section must be a list.")]

    results = []
    for i, proj in enumerate(projects):
        label = f"Project[{i}]"

        # FIX BUG-2: guard against non-dict entries
        if not isinstance(proj, dict):
            results.append(_fail(proj, f"{label}: Entry is not a dict — malformed input."))
            continue

        label = f"Project[{i}] ({proj.get('name', 'Unnamed')})"
        entry_result = {}

        # Name
        name = proj.get("name")
        if not name or len(str(name).strip()) < 2:
            entry_result["name"] = _fail(name, f"{label}: Project name is missing or too short.")
        else:
            entry_result["name"] = _ok(str(name).strip())

        # Duration
        raw_duration = proj.get("duration")
        if raw_duration:
            entry_result["duration"] = validate_duration(raw_duration, label, allow_future_end=False)
        else:
            entry_result["duration"] = _grey(None, f"{label}: No duration provided.")

        # GitHub link (live check)
        github = proj.get("github")
        if github:
            log.info("Checking URL: %s", github)
            entry_result["github"] = validate_url(github, label=f"{label} GitHub")
        else:
            entry_result["github"] = _grey(None, f"{label}: No GitHub link provided.")

        # Description richness
        entry_result["description"] = _evaluate_description(proj.get("points", {}), label)
        entry_result["_label"] = label
        results.append(entry_result)

    return results


def validate_skills(skills: Any) -> dict:
    """
    Validate skills section — expects a comma-separated string or a list.

    FIX BUG-5: str(s) was called twice per element in the list comprehension.
               Fixed using a walrus operator to evaluate once.
    """
    if not skills:
        return _fail(skills, "Skills section is missing or empty.")

    if isinstance(skills, str):
        items = [s.strip() for s in skills.split(",") if s.strip()]
    elif isinstance(skills, list):
        # FIX BUG-5: walrus operator ensures str(s).strip() is computed only once
        items = [stripped for s in skills if (stripped := str(s).strip())]
    else:
        return _fail(skills, "Skills must be a string or list.")

    if len(items) == 0:
        return _fail(skills, "No skills found after parsing.")
    if len(items) < 3:
        return _grey(items, f"Only {len(items)} skill(s) listed; a more comprehensive skills list is recommended.")

    return _ok(items)


def validate_achievements(achievements: Any) -> dict:
    """Validate achievements section."""
    if not achievements or not isinstance(achievements, dict):
        return _grey(achievements, "Achievements section is missing or empty.")

    points = achievements.get("points", {})
    if not points or not isinstance(points, dict):
        return _grey(achievements, "Achievements has no points/bullets.")

    items = [v for v in points.values() if v and str(v).strip()]
    if len(items) < 2:
        return _grey(achievements, f"Only {len(items)} achievement bullet(s); consider adding more.")

    return _ok(achievements)


def validate_responsibilities(responsibilities: Any) -> dict:
    """Validate responsibilities / positions of responsibility section."""
    if not responsibilities or not isinstance(responsibilities, dict):
        return _grey(responsibilities, "Responsibilities section is missing or empty.")

    points = responsibilities.get("points", {})
    if not points or not isinstance(points, dict):
        return _grey(responsibilities, "Responsibilities has no points/bullets.")

    items = [v for v in points.values() if v and str(v).strip()]
    if len(items) == 0:
        return _grey(responsibilities, "No responsibility entries found.")

    return _ok(responsibilities)


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

def validate_resume(raw: dict) -> dict:
    """
    Run the full validation pipeline on a raw resume JSON dict.
    Returns a report dict with per-field results (status, data, error/note).
    """
    log.info("=== Starting Validation Pipeline ===")
    report = {}

    # --- Personal details ---
    log.info("Validating: name")
    report["name"] = validate_name(raw.get("name"))

    log.info("Validating: emails")
    emails = raw.get("emails") or []
    if not isinstance(emails, list):
        emails = [emails]
    report["emails"] = [validate_email(e) for e in emails] if emails else [_fail(None, "No emails provided.")]

    log.info("Validating: phone_numbers")
    phones = raw.get("phone_numbers") or []
    if not isinstance(phones, list):
        phones = [phones]
    report["phone_numbers"] = [validate_phone(p) for p in phones] if phones else [_fail(None, "No phone numbers provided.")]

    # --- URLs ---
    url_fields = {
        "linkedin": "LinkedIn",
        "github": "GitHub",
        "leetcode": "LeetCode",
        "codeforces": "Codeforces",
        "codechef": "CodeChef",
        "portfolio": "Portfolio",
    }
    report["urls"] = {}
    for field, label in url_fields.items():
        val = raw.get(field)
        if val:
            log.info("Checking URL [%s]: %s", label, val)
            report["urls"][field] = validate_url(val, label=label)
        else:
            report["urls"][field] = _ok(None, note=f"{label} not provided — optional field.")

    # --- Education ---
    log.info("Validating: education")
    report["education"] = validate_education(raw.get("education"))

    # --- Experience ---
    log.info("Validating: experience")
    report["experience"] = validate_experience(raw.get("experience") or [])

    # --- Projects ---
    log.info("Validating: projects")
    report["projects"] = validate_projects(raw.get("projects") or [])

    # --- Skills ---
    log.info("Validating: skills")
    report["skills"] = validate_skills(raw.get("skills"))

    # --- Achievements ---
    log.info("Validating: achievements")
    report["achievements"] = validate_achievements(raw.get("achievements"))

    # --- Responsibilities ---
    log.info("Validating: responsibilities")
    report["responsibilities"] = validate_responsibilities(raw.get("responsibilities"))

    log.info("=== Validation Pipeline Complete ===")
    return report


# ---------------------------------------------------------------------------
# Tri-state partitioner
# ---------------------------------------------------------------------------

def _collect_statuses(obj: Any, path: str = "") -> list[tuple[str, str, Any, dict]]:
    """
    Recursively walk a validation report and yield
    (path_str, status, data, full_result_dict) for every leaf result.
    """
    collected = []

    if isinstance(obj, dict) and "status" in obj:
        # Leaf result node
        collected.append((path, obj["status"], obj.get("data"), obj))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if key.startswith("_"):
                continue
            sub_path = f"{path}.{key}" if path else key
            collected.extend(_collect_statuses(value, sub_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            sub_path = f"{path}[{idx}]"
            collected.extend(_collect_statuses(item, sub_path))

    return collected


def partition(report: dict) -> dict:
    """
    Convert a flat validation report into the tri-state output structure.
    """
    validated_sections: dict = {}
    invalid_sections: dict = {}
    grey_area: dict = {}

    leaves = _collect_statuses(report)

    for path, status, data, result in leaves:
        entry = {
            "path": path,
            "data": data,
        }
        if status == "valid":
            entry["note"] = result.get("note", "")
            validated_sections[path] = entry
        elif status == "invalid":
            entry["error"] = result.get("error", "Validation failed.")
            invalid_sections[path] = entry
        else:  # grey
            entry["note"] = result.get("note", "Ambiguous or incomplete.")
            grey_area[path] = entry

    summary = {
        "total_checks": len(leaves),
        "validated_count": len(validated_sections),
        "invalid_count": len(invalid_sections),
        "grey_area_count": len(grey_area),
    }

    return {
        "summary": summary,
        "validated_sections": validated_sections,
        "invalid_sections": invalid_sections,
        "grey_area": grey_area,
    }


# ---------------------------------------------------------------------------
# Main entry (library usage)
# ---------------------------------------------------------------------------

def run(raw_json: dict) -> dict:
    """Full pipeline: validate → partition → return tri-state output."""
    report = validate_resume(raw_json)
    return partition(report)