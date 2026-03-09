from __future__ import annotations

from .engine import run, run_async
from .models import (
    BulletSection,
    EducationEntry,
    EducationSection,
    ExperienceEntry,
    ProjectEntry,
    ResumeInput,
)
from .result import InvalidResult, ResultNode, ValidResult, GreyResult, fail, grey, ok
from .validators import (
    evaluate_description,
    validate_achievements,
    validate_duration,
    validate_education,
    validate_email,
    validate_experience,
    validate_grade,
    validate_name,
    validate_phone,
    validate_projects,
    validate_responsibilities,
    validate_skills,
    validate_url_async,
)

__version__ = "3.0.0"
__author__ = "Smart Resume Audit & Verification System"

__all__ = [
    "__version__",
    "__author__",
    "run",
    "run_async",
    "validate_name",
    "validate_email",
    "validate_phone",
    "validate_url_async",
    "validate_duration",
    "validate_grade",
    "validate_education",
    "validate_experience",
    "validate_projects",
    "validate_skills",
    "validate_achievements",
    "validate_responsibilities",
    "evaluate_description",
    "ResumeInput",
    "EducationEntry",
    "EducationSection",
    "ExperienceEntry",
    "ProjectEntry",
    "BulletSection",
    "ResultNode",
    "ValidResult",
    "InvalidResult",
    "GreyResult",
    "ok",
    "fail",
    "grey",
]
