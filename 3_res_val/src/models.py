from typing import Any, Union
from pydantic import BaseModel, ConfigDict, field_validator

class ValidationResultItem(BaseModel):
    path: str
    data: Any
    note: str | None = None
    error: str | None = None

class ValidationSummary(BaseModel):
    total_checks: int
    validated_count: int
    invalid_count: int
    grey_area_count: int
    pass_rate: float

class ValidationOutput(BaseModel):
    summary: ValidationSummary
    validated_sections: dict[str, ValidationResultItem]
    invalid_sections: dict[str, ValidationResultItem]
    grey_area: dict[str, ValidationResultItem]

class EducationEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    degree: str | None = None
    institution: str | None = None
    duration: str | None = None
    grade: Union[str, float, int, None] = None

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
    education: dict[str, EducationEntry] | None = None
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
        return v

    @field_validator("phone_numbers", mode="before")
    @classmethod
    def _coerce_phones(cls, v: Any) -> list[str] | None:
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("skills", mode="before")
    @classmethod
    def _coerce_skills(cls, v: Any) -> list[str] | None:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v
