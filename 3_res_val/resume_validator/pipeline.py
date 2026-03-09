from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .result import fail

if TYPE_CHECKING:
    from pydantic import ValidationError

__all__ = ["collect_leaves", "partition", "pydantic_errors_to_output"]


def collect_leaves(
    obj: Any,
    path: str = "",
) -> list[tuple[str, str, Any, dict]]:
    collected: list[tuple[str, str, Any, dict]] = []

    if isinstance(obj, dict) and "status" in obj:
        collected.append((path, obj["status"], obj.get("data"), obj))
        return collected

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.startswith("_"):
                continue
            child_path = f"{path}.{key}" if path else key
            collected.extend(collect_leaves(value, child_path))

    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            collected.extend(collect_leaves(item, f"{path}[{idx}]"))

    return collected


def partition(report: dict) -> dict:
    validated: dict = {}
    invalid: dict = {}
    grey_area: dict = {}

    for path, status, data, result in collect_leaves(report):
        base = {"path": path, "data": data}
        if status == "valid":
            validated[path] = {**base, "note": result.get("note", "")}
        elif status == "invalid":
            invalid[path] = {**base, "error": result.get("error", "Validation failed.")}
        else:
            grey_area[path] = {**base, "note": result.get("note", "Ambiguous or incomplete.")}

    total = len(validated) + len(invalid) + len(grey_area)
    return {
        "summary": {
            "total_checks": total,
            "validated_count": len(validated),
            "invalid_count": len(invalid),
            "grey_area_count": len(grey_area),
            "pass_rate": round(len(validated) / total * 100, 1) if total else 0.0,
        },
        "validated_sections": validated,
        "invalid_sections": invalid,
        "grey_area": grey_area,
    }


def pydantic_errors_to_output(exc: "ValidationError") -> dict:
    invalid: dict = {}
    for error in exc.errors():
        loc = ".".join(str(p) for p in error["loc"])
        invalid[loc] = fail(error.get("input"), f"Schema error at '{loc}': {error['msg']}")

    total = len(invalid)
    return {
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
