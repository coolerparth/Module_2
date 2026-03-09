from __future__ import annotations

import asyncio

from ..models import ProjectEntry
from ..result import fail, grey, ok
from .duration import validate_duration
from .extras import evaluate_description
from .url import validate_url_async

__all__ = ["validate_projects"]


async def validate_projects(projects: list[ProjectEntry]) -> list[dict]:
    if not projects:
        return []
    return list(await asyncio.gather(*[_validate_one(i, p) for i, p in enumerate(projects)]))


async def _validate_one(idx: int, proj: ProjectEntry) -> dict:
    proj_name = (proj.name or "").strip() or "Unnamed"
    label = f"Project[{idx}] ({proj_name})"
    row: dict = {"_label": label}

    name_str = (proj.name or "").strip()
    row["name"] = (
        ok(name_str) if len(name_str) >= 2
        else fail(proj.name, f"{label}: Project name is missing or too short.")
    )

    row["duration"] = (
        validate_duration(proj.duration, label, allow_future_end=False)
        if proj.duration
        else grey(None, f"{label}: No duration provided.")
    )

    row["github"] = await validate_url_async(proj.github, label=f"{label} GitHub")
    row["description"] = evaluate_description(proj.points, label)
    return row
