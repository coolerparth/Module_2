from __future__ import annotations

from ..constants import DIGITS_RE, INDIAN_MOBILE_STARTS
from ..result import ResultNode, fail, grey, ok

__all__ = ["validate_phone"]


def validate_phone(phone: str) -> ResultNode:
    raw = phone.strip()
    if not raw:
        return fail(raw, "Phone number is empty.")

    digits = DIGITS_RE.sub("", raw)
    n = len(digits)

    if n == 10:
        if digits[0] == "0":
            return fail(raw, "10-digit number cannot start with 0.")
        if digits[0] in INDIAN_MOBILE_STARTS:
            return grey(
                raw,
                f"'{raw}' appears to be an Indian mobile number — +91 prefix is mandatory. "
                f"Correct format: +91 {digits[:5]} {digits[5:]}",
            )
        return grey(
            raw,
            "10-digit number has no country code — origin cannot be determined. "
            "Use: +91 (India), +1 (US/Canada), +44 (UK), etc.",
        )

    if n == 11 and digits.startswith("1"):
        if digits[1] == "0":
            return fail(raw, f"US/Canada number '{raw}' — area code cannot start with 0.")
        return ok(raw, note="US/Canada (+1) — valid 10-digit number.")

    if n == 12 and digits.startswith("91"):
        core_start = digits[2]
        if core_start not in INDIAN_MOBILE_STARTS:
            return fail(
                raw,
                f"India (+91) number '{raw}' — mobile must start with 6, 7, 8, or 9 after prefix.",
            )
        return ok(raw, note="India (+91) — valid 10-digit mobile number.")

    if 7 <= n <= 9:
        return grey(
            raw,
            f"Only {n} digits after stripping — minimum 10 expected. "
            "Number appears incomplete or missing country code.",
        )

    return fail(
        raw,
        f"'{raw}' has {n} digits — no matching phone format found. "
        "Use international format, e.g. +91 XXXXX XXXXX or +1 XXX XXX XXXX.",
    )
