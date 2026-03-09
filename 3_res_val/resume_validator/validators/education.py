from __future__ import annotations

from typing import Union

from ..constants import MAX_CGPA, MAX_PERCENTAGE
from ..models import EducationEntry, EducationSection
from ..result import ResultNode, fail, grey, ok
from .duration import validate_duration

__all__ = ["validate_grade", "validate_education"]


def validate_grade(grade: Union[str, float, int, None], level: str) -> ResultNode:
    if grade is None:
        return grey(None, f"Grade for '{level}' not provided.")

    grade_str = str(grade).strip()
    if not grade_str or grade_str.lower() == "none":
        return grey(grade, f"Grade for '{level}' not provided.")

    if isinstance(grade, (int, float)):
        if grade < 0:
            return fail(grade, f"Grade for '{level}' is {grade} — negative values are invalid.")
        if grade <= MAX_CGPA:
            return ok(grade_str, note=f"CGPA format detected: {grade}/10.0")
        if grade <= MAX_PERCENTAGE:
            return ok(grade_str, note=f"Percentage format detected: {grade}%")
        return fail(
            grade,
            f"Grade for '{level}' is {grade} — exceeds maximum valid percentage of {MAX_PERCENTAGE}.",
        )

    return ok(grade_str)


def validate_education(education: EducationSection | None) -> dict:
    if education is None:
        return {"_error": fail(None, "Education section is missing.")}

    level_map: dict[str, EducationEntry | None] = {
        "phd":     education.phd,
        "pg":      education.pg,
        "ug":      education.ug,
        "class12": education.class12,
        "class10": education.class10,
    }

    results: dict = {}
    for level, entry in level_map.items():
        if entry is None:
            results[level] = ok(None, note=f"'{level}' not provided — acceptable.")
            continue

        row: dict = {}

        degree = (entry.degree or "").strip()
        row["degree"] = (
            ok(degree) if len(degree) >= 2
            else fail(entry.degree, f"Degree for '{level}' is missing or too short.")
        )

        institution = (entry.institution or "").strip()
        row["institution"] = (
            ok(institution) if len(institution) >= 2
            else fail(entry.institution, f"Institution for '{level}' is missing or too short.")
        )

        row["duration"] = validate_duration(
            entry.duration,
            f"Education[{level}]",
            allow_future_end=True,
        )
        row["grade"] = validate_grade(entry.grade, level)
        results[level] = row

    return results
