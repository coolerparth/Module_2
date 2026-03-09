from __future__ import annotations

import logging
from datetime import datetime

from ..models import ExperienceEntry
from ..result import fail, grey, ok
from ..utils import is_ongoing, parse_date, today
from .duration import validate_duration
from .extras import evaluate_description

__all__ = ["validate_experience"]

log = logging.getLogger(__name__)


def validate_experience(experience: list[ExperienceEntry]) -> list[dict]:
    if not experience:
        return []

    results: list[dict] = []
    parsed_ranges: list[tuple[datetime, datetime, str]] = []

    for idx, exp in enumerate(experience):
        role_name = (exp.role or "").strip() or "Unknown Role"
        label = f"Experience[{idx}] ({role_name})"
        row: dict = {"_label": label}

        role_str = (exp.role or "").strip()
        row["role"] = (
            ok(role_str) if len(role_str) >= 2
            else fail(exp.role, f"{label}: Role is missing or too short.")
        )

        company_str = (exp.company or "").strip()
        row["company"] = (
            ok(company_str) if len(company_str) >= 2
            else fail(exp.company, f"{label}: Company name is missing or too short.")
        )

        raw_start = (exp.start or "").strip()
        raw_end = (exp.end or "").strip()

        if raw_start and raw_end:
            if is_ongoing(raw_end):
                dur_result = validate_duration(f"{raw_start} - Present", label, allow_future_end=False)
            else:
                dur_result = validate_duration(f"{raw_start} - {raw_end}", label, allow_future_end=False)
            row["duration"] = dur_result

            if dur_result["status"] == "valid":
                d = dur_result["data"]
                s_dt = parse_date(d.get("start") or "")
                e_raw = d.get("end", "")
                e_dt = today() if (not e_raw or e_raw == "Present") else parse_date(e_raw)
                if s_dt and e_dt:
                    parsed_ranges.append((s_dt, e_dt, label))

        elif raw_start:
            row["duration"] = grey(
                {"start": raw_start, "end": None},
                f"{label}: End date missing — treating as ongoing.",
            )
        else:
            row["duration"] = grey(None, f"{label}: Both start and end dates are missing.")

        row["description"] = evaluate_description(exp.points, label)
        results.append(row)

    _tag_overlaps(parsed_ranges, results)
    return results


def _tag_overlaps(
    ranges: list[tuple[datetime, datetime, str]],
    results: list[dict],
) -> None:
    n = len(ranges)
    for a in range(n):
        s1, e1, lbl1 = ranges[a]
        for b in range(a + 1, n):
            s2, e2, lbl2 = ranges[b]
            if s1 < e2 and s2 < e1:
                log.warning("Timeline overlap detected: %s ↔ %s", lbl1, lbl2)
                overlap_note = grey(
                    {"between": [lbl1, lbl2]},
                    f"Timeline overlap between {lbl1} and {lbl2} — verify dates manually.",
                )
                for row in results:
                    if row.get("_label") in (lbl1, lbl2):
                        row["timeline_overlap"] = overlap_note
