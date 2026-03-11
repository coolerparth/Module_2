import asyncio
import logging
from typing import Any
from .models import ResumeInput, ValidationOutput, ExperienceEntry, ProjectEntry, EducationEntry, BulletSection
from .validators import (
    validate_name, validate_email, validate_phone, _validate_url_async,
    validate_duration, _evaluate_description, _validate_grade, _ok, _fail, _grey,
    build_url_validation_session, duration_payload_to_range,
)
from pydantic import ValidationError

log = logging.getLogger(__name__)

def validate_education(education: dict[str, EducationEntry] | None) -> dict:
    if not education:
        return _fail(None, "Education section is missing or empty.")
    results: dict = {}
    for level, entry in education.items():
        if entry is None:
            results[level] = _ok(None, note=f"'{level}' not provided — acceptable.")
            continue
        row: dict = {}
        degree = (entry.degree or "").strip()
        row["degree"] = (
            _ok(degree) if len(degree) >= 2
            else _fail(entry.degree, f"Degree for '{level}' is missing or too short.")
        )
        institution = (entry.institution or "").strip()
        row["institution"] = (
            _ok(institution) if len(institution) >= 2
            else _fail(entry.institution, f"Institution for '{level}' is missing or too short.")
        )
        row["duration"] = validate_duration(
            entry.duration, f"Education[{level}]", allow_future_end=True
        )
        row["grade"] = _validate_grade(entry.grade, level)
        results[level] = row
    return results

def validate_experience(experience: list[ExperienceEntry]) -> list:
    if not experience:
        return []
    results: list[dict] = []
    parsed_ranges: list[tuple[Any, Any, str]] = []
    for i, exp in enumerate(experience):
        role_name = (exp.role or "").strip() or "Unknown Role"
        label = f"Experience[{i}] ({role_name})"
        row: dict = {"_label": label}
        role_str = (exp.role or "").strip()
        row["role"] = (
            _ok(role_str) if len(role_str) >= 2
            else _fail(exp.role, f"{label}: Role is missing or too short.")
        )
        company_str = (exp.company or "").strip()
        row["company"] = (
            _ok(company_str) if len(company_str) >= 2
            else _fail(exp.company, f"{label}: Company name is missing or too short.")
        )
        raw_start = (exp.start or "").strip()
        raw_end = (exp.end or "").strip()
        if raw_start and raw_end:
            dur_result = validate_duration(f"{raw_start} - {raw_end}", label, allow_future_end=False)
            row["duration"] = dur_result
            if dur_result["status"] == "valid":
                d = dur_result["data"]
                span = duration_payload_to_range(d if isinstance(d, dict) else None)
                if span:
                    parsed_ranges.append((span[0], span[1], label))
        elif raw_start:
            row["duration"] = _grey(
                {"start": raw_start, "end": None},
                f"{label}: End date missing — treating as ongoing.",
            )
        else:
            row["duration"] = _grey(None, f"{label}: Both start and end dates are missing.")
        row["description"] = _evaluate_description(exp.points, label)
        results.append(row)
    n = len(parsed_ranges)
    for i in range(n):
        s1, e1, lbl1 = parsed_ranges[i]
        for j in range(i + 1, n):
            s2, e2, lbl2 = parsed_ranges[j]
            try:
                if s1 < e2 and s2 < e1:
                    log.debug("Timeline overlap: %s overlaps %s", lbl1, lbl2)
                    for row in results:
                        if row.get("_label") in (lbl1, lbl2):
                            row["timeline_overlap"] = _grey(
                                None,
                                f"Timeline overlap detected between {lbl1} and {lbl2} — verify manually.",
                            )
            except TypeError:
                pass
    return results

async def _validate_projects_async(
    projects: list[ProjectEntry],
    session: Any | None = None,
) -> list:
    if not projects:
        return []
    async def _one(i: int, proj: ProjectEntry) -> dict:
        proj_name = (proj.name or "").strip() or "Unnamed"
        label = f"Project[{i}] ({proj_name})"
        row: dict = {"_label": label}
        name_str = (proj.name or "").strip()
        row["name"] = (
            _ok(name_str) if len(name_str) >= 2
            else _fail(proj.name, f"{label}: Project name is missing or too short.")
        )
        row["duration"] = (
            validate_duration(proj.duration, label, allow_future_end=False)
            if proj.duration
            else _grey(None, f"{label}: No duration provided.")
        )
        row["github"] = await _validate_url_async(proj.github, label=f"{label} GitHub", session=session)
        row["description"] = _evaluate_description(proj.points, label)
        return row
    return list(await asyncio.gather(*[_one(i, p) for i, p in enumerate(projects)]))

def validate_skills(skills: list[str] | None) -> dict:
    MIN_SKILLS = 3
    if not skills:
        return _fail(skills, "Skills section is missing or empty.")
    items = [s.strip() for s in skills if s.strip()]
    if not items:
        return _fail(skills, "No skills found after parsing — the list appears to be empty.")
    if len(items) < MIN_SKILLS:
        return _grey(
            items,
            f"Only {len(items)} skill(s) listed — a more comprehensive list is strongly recommended.",
        )
    return _ok(items)

def validate_achievements(achievements: BulletSection | None) -> dict:
    if achievements is None or achievements.points is None:
        return _grey(None, "Achievements section is missing or has no 'points' dict.")
    items = [s for v in achievements.points.values() if (s := str(v).strip())]
    if not items:
        return _grey(achievements.model_dump(), "Achievements contain no non-empty entries.")
    if len(items) < 2:
        return _grey(
            achievements.model_dump(),
            f"Only {len(items)} achievement bullet — consider adding more to strengthen the profile.",
        )
    return _ok(achievements.model_dump())

def validate_responsibilities(responsibilities: BulletSection | None) -> dict:
    if responsibilities is None or responsibilities.points is None:
        return _grey(None, "Responsibilities section is missing or has no 'points' dict.")
    items = [s for v in responsibilities.points.values() if (s := str(v).strip())]
    if not items:
        return _grey(responsibilities.model_dump(), "No non-empty responsibility entries found.")
    return _ok(responsibilities.model_dump())

async def _run_pipeline(resume: ResumeInput) -> dict:
    report: dict = {}
    report["name"] = validate_name(resume.name)
    emails = resume.emails or []
    report["emails"] = (
        [validate_email(e) for e in emails]
        if emails
        else [_fail(None, "No email addresses provided.")]
    )
    phones = resume.phone_numbers or []
    report["phone_numbers"] = (
        [validate_phone(p) for p in phones]
        if phones
        else [_fail(None, "No phone numbers provided.")]
    )
    url_defs: list[tuple[str, str, str | None]] = [
        ("linkedin",   "LinkedIn",   resume.linkedin),
        ("github",     "GitHub",     resume.github),
        ("leetcode",   "LeetCode",   resume.leetcode),
        ("codeforces", "Codeforces", resume.codeforces),
        ("codechef",   "CodeChef",   resume.codechef),
        ("portfolio",  "Portfolio",  resume.portfolio),
    ]
    requires_network = any((value or "").strip() for _, _, value in url_defs) or any(
        (project.github or "").strip() for project in (resume.projects or [])
    )
    if requires_network:
        async with build_url_validation_session() as session:
            url_results = await asyncio.gather(*[
                _validate_url_async(val, label=label, session=session) for _, label, val in url_defs
            ])
            report["urls"] = {
                field: result for (field, _, _), result in zip(url_defs, url_results)
            }
            report["projects"] = await _validate_projects_async(resume.projects or [], session=session)
    else:
        url_results = await asyncio.gather(*[
            _validate_url_async(val, label=label) for _, label, val in url_defs
        ])
        report["urls"] = {
            field: result for (field, _, _), result in zip(url_defs, url_results)
        }
        report["projects"] = await _validate_projects_async(resume.projects or [])
    report["education"] = validate_education(resume.education)
    report["experience"] = validate_experience(resume.experience or [])
    report["skills"] = validate_skills(resume.skills)
    report["achievements"] = validate_achievements(resume.achievements)
    report["responsibilities"] = validate_responsibilities(resume.responsibilities)
    return report

def _collect_leaves(obj: Any, path: str = "") -> list[tuple[str, str, Any, dict]]:
    collected: list[tuple[str, str, Any, dict]] = []
    if isinstance(obj, dict) and "status" in obj:
        collected.append((path, obj["status"], obj.get("data"), obj))
        return collected
    if isinstance(obj, dict):
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
    validated_sections: dict = {}
    invalid_sections: dict = {}
    grey_area: dict = {}
    for path, status, data, result in _collect_leaves(report):
        base = {"path": path, "data": data}
        if status == "valid":
            validated_sections[path] = {**base, "note": result.get("note", "")}
        elif status == "invalid":
            invalid_sections[path] = {**base, "error": result.get("error", "Validation failed.")}
        else:
            grey_area[path] = {**base, "note": result.get("note", "Ambiguous or incomplete.")}
    total = len(validated_sections) + len(invalid_sections) + len(grey_area)
    raw_output = {
        "summary": {
            "total_checks": total,
            "validated_count": len(validated_sections),
            "invalid_count": len(invalid_sections),
            "grey_area_count": len(grey_area),
            "pass_rate": round(len(validated_sections) / total * 100, 1) if total else 0.0,
        },
        "validated_sections": validated_sections,
        "invalid_sections": invalid_sections,
        "grey_area": grey_area,
    }
    return ValidationOutput.model_validate(raw_output).model_dump()

def _pydantic_errors_to_output(exc: ValidationError) -> dict:
    invalid: dict = {}
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        invalid[loc] = {
            "path": loc,
            "data": error.get("input"),
            "error": f"Schema error at '{loc}': {error['msg']}",
        }
    total = len(invalid)
    raw_output = {
        "summary": {
            "total_checks": total,
            "validated_count": 0,
            "invalid_count": total,
            "grey_area_count": 0,
            "pass_rate": 0.0,
        },
        "validated_sections": {},
        "invalid_sections": invalid,
        "grey_area": {},
    }
    return ValidationOutput.model_validate(raw_output).model_dump()

async def run_async(raw_json: dict) -> dict:
    if not isinstance(raw_json, dict):
        raise TypeError(f"run_async() expects a dict, got {type(raw_json).__name__}.")
    try:
        resume = ResumeInput.model_validate(raw_json)
    except ValidationError as exc:
        return _pydantic_errors_to_output(exc)
    report = await _run_pipeline(resume)
    return partition(report)

def run(raw_json: dict) -> dict:
    return asyncio.run(run_async(raw_json))
