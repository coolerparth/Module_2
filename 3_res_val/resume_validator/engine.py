from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError

from .models import ResumeInput
from .pipeline import partition, pydantic_errors_to_output
from .result import fail
from .validators import (
    validate_achievements,
    validate_education,
    validate_email,
    validate_experience,
    validate_name,
    validate_phone,
    validate_projects,
    validate_responsibilities,
    validate_skills,
    validate_url_async,
)

__all__ = ["run", "run_async"]

log = logging.getLogger(__name__)

_URL_FIELDS: tuple[tuple[str, str], ...] = (
    ("linkedin",   "LinkedIn"),
    ("github",     "GitHub"),
    ("leetcode",   "LeetCode"),
    ("codeforces", "Codeforces"),
    ("codechef",   "CodeChef"),
    ("portfolio",  "Portfolio"),
)


async def _build_report(resume: ResumeInput) -> dict:
    report: dict = {}

    report["name"] = validate_name(resume.name)

    emails = resume.emails or []
    report["emails"] = (
        [validate_email(e) for e in emails]
        if emails
        else [fail(None, "No email addresses provided.")]
    )

    phones = resume.phone_numbers or []
    report["phone_numbers"] = (
        [validate_phone(p) for p in phones]
        if phones
        else [fail(None, "No phone numbers provided.")]
    )

    url_results = await asyncio.gather(*[
        validate_url_async(getattr(resume, field, None), label=label)
        for field, label in _URL_FIELDS
    ])
    report["urls"] = {
        field: result for (field, _), result in zip(_URL_FIELDS, url_results)
    }

    report["education"]        = validate_education(resume.education)
    report["experience"]       = validate_experience(resume.experience or [])
    report["projects"]         = await validate_projects(resume.projects or [])
    report["skills"]           = validate_skills(resume.skills)
    report["achievements"]     = validate_achievements(resume.achievements)
    report["responsibilities"] = validate_responsibilities(resume.responsibilities)

    return report


async def run_async(raw_json: dict) -> dict:
    if not isinstance(raw_json, dict):
        raise TypeError(f"run_async() expects a dict, got {type(raw_json).__name__}.")

    try:
        resume = ResumeInput.model_validate(raw_json)
    except ValidationError as exc:
        log.warning("Pydantic schema validation failed: %d error(s)", len(exc.errors()))
        return pydantic_errors_to_output(exc)

    log.info("Starting validation pipeline for resume: %s", raw_json.get("name", "<unknown>"))
    report = await _build_report(resume)
    result = partition(report)
    log.info(
        "Validation complete — total=%d valid=%d invalid=%d grey=%d pass_rate=%.1f%%",
        result["summary"]["total_checks"],
        result["summary"]["validated_count"],
        result["summary"]["invalid_count"],
        result["summary"]["grey_area_count"],
        result["summary"]["pass_rate"],
    )
    return result


def run(raw_json: dict) -> dict:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, run_async(raw_json))
            return future.result()

    return asyncio.run(run_async(raw_json))
