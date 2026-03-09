from __future__ import annotations

from ..constants import EMAIL_RE
from ..result import ResultNode, fail, grey, ok
from ..utils import suggest_domain

__all__ = ["validate_email"]


def validate_email(email: str) -> ResultNode:
    addr = email.strip()
    if not addr:
        return fail(addr, "Email is empty.")

    if not EMAIL_RE.match(addr):
        return fail(addr, f"'{addr}' is not a valid email address format.")

    if ".." in addr:
        return fail(addr, f"'{addr}' contains consecutive dots (..) — invalid per RFC 5321.")

    at_pos = addr.index("@")
    if at_pos == 0:
        return fail(addr, f"'{addr}' has an empty local part before @.")

    domain = addr[at_pos + 1:].lower()
    suggestion = suggest_domain(domain)
    if suggestion:
        return grey(
            addr,
            f"Domain '{domain}' looks like a typo — did you mean '{suggestion}'?",
        )

    return ok(addr)
