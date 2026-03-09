from __future__ import annotations

from ..constants import DURATION_SPLIT_RE, MAX_EXPERIENCE_SPAN_YEARS, YEAR_RE
from ..result import ResultNode, fail, grey, ok
from ..utils import is_ongoing, parse_date, today, years_between

__all__ = ["validate_duration"]


def validate_duration(
    duration: str | None,
    section_label: str,
    *,
    allow_future_end: bool = False,
) -> ResultNode:
    if not duration or not duration.strip():
        return grey(duration, f"{section_label}: Duration is missing or blank.")

    stripped = duration.strip()
    parts = DURATION_SPLIT_RE.split(stripped, maxsplit=1)

    if len(parts) == 1:
        if YEAR_RE.search(parts[0]):
            return ok(
                {"raw": stripped, "start": None, "end": parts[0].strip()},
                note=f"{section_label}: Single-year entry.",
            )
        return grey(
            stripped,
            f"{section_label}: '{stripped}' is ambiguous — no recognisable year found.",
        )

    raw_start, raw_end = parts[0].strip(), parts[1].strip()

    if is_ongoing(raw_end):
        start_dt = parse_date(raw_start)
        if start_dt is None:
            return grey(
                stripped,
                f"{section_label}: Start date '{raw_start}' could not be parsed.",
            )
        if start_dt > today():
            return grey(
                {"raw": stripped, "start": start_dt.date().isoformat(), "end": "Present"},
                f"{section_label}: Start '{raw_start}' is in the future — upcoming role?",
            )
        return ok(
            {"raw": stripped, "start": start_dt.date().isoformat(), "end": "Present"},
            note=f"{section_label}: Active/ongoing entry.",
        )

    start_dt = parse_date(raw_start)
    end_dt = parse_date(raw_end)

    if start_dt is None and end_dt is None:
        return grey(
            stripped,
            f"{section_label}: Neither '{raw_start}' nor '{raw_end}' could be parsed as dates.",
        )
    if start_dt is None:
        return grey(stripped, f"{section_label}: Start date '{raw_start}' could not be parsed.")
    if end_dt is None:
        return grey(stripped, f"{section_label}: End date '{raw_end}' could not be parsed.")

    payload = {
        "raw": stripped,
        "start": start_dt.date().isoformat(),
        "end": end_dt.date().isoformat(),
    }

    if end_dt < start_dt:
        return fail(
            payload,
            f"{section_label}: End '{raw_end}' precedes start '{raw_start}' — impossible timeline.",
        )

    if start_dt > today():
        return grey(
            payload,
            f"{section_label}: Start '{raw_start}' is in the future — upcoming or incoming role?",
        )

    if end_dt > today() and not allow_future_end:
        return grey(
            payload,
            f"{section_label}: End '{raw_end}' is in the future — mark as 'ongoing' if still active.",
        )

    span = years_between(start_dt, end_dt)
    if span > MAX_EXPERIENCE_SPAN_YEARS:
        return grey(
            payload,
            f"{section_label}: Span of {span:.1f} years is unusually long — verify manually.",
        )

    return ok(payload)
