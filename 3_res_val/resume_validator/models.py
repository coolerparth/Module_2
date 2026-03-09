from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = [
    "EducationEntry",
    "EducationSection",
    "ExperienceEntry",
    "ProjectEntry",
    "BulletSection",
    "ResumeInput",
]


class EducationEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    degree: str | None = None
    institution: str | None = None
    duration: str | None = None
    grade: Union[str, float, int, None] = None


class EducationSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    phd: EducationEntry | None = None
    pg: EducationEntry | None = None
    ug: EducationEntry | None = None
    class12: EducationEntry | None = None
    class10: EducationEntry | None = None


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str | None = None
    company: str | None = None
    start: str | None = None
    end: str | None = None
    points: dict[str, Any] | None = None


class ProjectEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None
    duration: str | None = None
    github: str | None = None
    points: dict[str, Any] | None = None


class BulletSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    points: dict[str, Any] | None = None


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    emails: list[str] | None = None
    phone_numbers: list[str] | None = None

    linkedin: str | None = None
    github: str | None = None
    leetcode: str | None = None
    codeforces: str | None = None
    codechef: str | None = None
    portfolio: str | None = None

    education: EducationSection | None = None
    experience: list[ExperienceEntry] | None = None
    projects: list[ProjectEntry] | None = None
    skills: list[str] | None = None
    achievements: BulletSection | None = None
    responsibilities: BulletSection | None = None

    @field_validator("emails", mode="before")
    @classmethod
    def _coerce_emails(cls, v: Any) -> list[str] | None:
        if isinstance(v, str):
            return [v]
        if not isinstance(v, (list, type(None))):
            return None
        return v

    @field_validator("phone_numbers", mode="before")
    @classmethod
    def _coerce_phones(cls, v: Any) -> list[str] | None:
        if isinstance(v, str):
            return [v]
        if not isinstance(v, (list, type(None))):
            return None
        return v

    @field_validator("skills", mode="before")
    @classmethod
    def _coerce_skills(cls, v: Any) -> list[str] | None:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if not isinstance(v, (list, type(None))):
            return None
        return v

    @field_validator("experience", mode="before")
    @classmethod
    def _coerce_experience(cls, v: Any) -> list | None:
        if v is None:
            return None
        if isinstance(v, dict):
            return list(v.values()) if v else None
        if not isinstance(v, list):
            return None
        return v

    @field_validator("projects", mode="before")
    @classmethod
    def _coerce_projects(cls, v: Any) -> list | None:
        if v is None:
            return None
        if isinstance(v, dict):
            return list(v.values()) if v else None
        if not isinstance(v, list):
            return None
        return v
