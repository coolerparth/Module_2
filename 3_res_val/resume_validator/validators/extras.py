from __future__ import annotations

from typing import Any

from ..constants import MIN_BULLET_WORDS, MIN_BULLETS
from ..models import BulletSection
from ..result import ResultNode, grey, ok

__all__ = ["evaluate_description", "validate_achievements", "validate_responsibilities"]


def evaluate_description(points: dict[str, Any] | None, label: str) -> ResultNode:
    if not points:
        return grey(points, f"{label}: No description bullets provided.")

    bullets = [s for v in points.values() if (s := str(v).strip())]
    count = len(bullets)

    if count == 0:
        return grey(points, f"{label}: All description bullets are empty.")

    avg_words = sum(len(b.split()) for b in bullets) / count

    if count >= MIN_BULLETS and avg_words >= MIN_BULLET_WORDS:
        return ok(points)

    if count >= MIN_BULLETS:
        return grey(
            points,
            f"{label}: {count} bullets but average is only {avg_words:.1f} words — add more depth.",
        )

    if avg_words >= 10:
        return grey(
            points,
            f"{label}: Only {count} bullet — well-written but consider expanding to multiple points.",
        )

    return grey(points, f"{label}: Only {count} short bullet(s) — insufficient detail.")


def validate_achievements(achievements: BulletSection | None) -> ResultNode:
    if achievements is None or achievements.points is None:
        return grey(None, "Achievements section missing or has no 'points' dict.")

    items = [s for v in achievements.points.values() if (s := str(v).strip())]

    if not items:
        return grey(achievements.model_dump(), "Achievements 'points' has no non-empty entries.")

    if len(items) < 2:
        return grey(
            achievements.model_dump(),
            f"Only {len(items)} achievement bullet — add more to strengthen the profile.",
        )

    return ok(achievements.model_dump())


def validate_responsibilities(responsibilities: BulletSection | None) -> ResultNode:
    if responsibilities is None or responsibilities.points is None:
        return grey(None, "Responsibilities section missing or has no 'points' dict.")

    items = [s for v in responsibilities.points.values() if (s := str(v).strip())]

    if not items:
        return grey(responsibilities.model_dump(), "Responsibilities 'points' has no non-empty entries.")

    return ok(responsibilities.model_dump())
