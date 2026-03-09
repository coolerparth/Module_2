from __future__ import annotations

from ..constants import MIN_SKILLS
from ..result import ResultNode, fail, grey, ok

__all__ = ["validate_skills"]


def validate_skills(skills: list[str] | None) -> ResultNode:
    if not skills:
        return fail(skills, "Skills section is missing or empty.")

    items = [s.strip() for s in skills if s.strip()]

    if not items:
        return fail(skills, "Skills list is empty after stripping whitespace.")

    if len(items) < MIN_SKILLS:
        return grey(
            items,
            f"Only {len(items)} skill(s) listed — a richer skills section is strongly recommended.",
        )

    return ok(items)
