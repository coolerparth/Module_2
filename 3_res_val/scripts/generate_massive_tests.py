import argparse
import copy
import json
import random
from pathlib import Path
from typing import Any, Callable

Expectation = dict[str, str]
Mutator = Callable[[dict[str, Any]], tuple[dict[str, Any], list[Expectation], str]]


def _exp(path: str, status: str, contains: str | None = None) -> Expectation:
    item: Expectation = {"path": path, "status": status}
    if contains:
        item["contains"] = contains
    return item


def _base_resume() -> dict[str, Any]:
    return {
        "name": "Jane Doe",
        "emails": ["jane.doe@gmail.com"],
        "phone_numbers": ["+91 9876543210"],
        "education": {
            "bachelors": {
                "degree": "B.Tech Computer Science",
                "institution": "Indian Institute of Technology",
                "duration": "2018 - 2022",
                "grade": 8.7,
            }
        },
        "experience": [
            {
                "role": "Software Engineer",
                "company": "Example Corp",
                "start": "2022",
                "end": "Present",
                "points": {
                    "1": "Built backend services that handled high throughput traffic reliably.",
                    "2": "Improved API latency and reduced incident count using observability tooling.",
                },
            }
        ],
        "projects": [
            {
                "name": "Validation Engine",
                "duration": "2023 - Present",
                "github": None,
                "points": {
                    "1": "Implemented async validation flows with deterministic output contracts.",
                    "2": "Designed strict schema checks to protect downstream integrations.",
                },
            }
        ],
        "skills": ["Python", "Pydantic", "FastAPI", "AsyncIO", "Testing"],
        "achievements": {
            "points": {
                "1": "Won internal engineering award for quality improvements.",
                "2": "Mentored junior developers and improved onboarding velocity.",
            }
        },
        "responsibilities": {
            "points": {
                "1": "Owned production incident response and postmortem documentation.",
                "2": "Led sprint planning and release coordination with product stakeholders.",
            }
        },
    }


def _m_valid_compact_duration(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["education"]["bachelors"]["duration"] = "2018-2022"
    return case, [_exp("education.bachelors.duration", "valid")], "compact_year_range"


def _m_name_digits(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["name"] = "John 123 Doe"
    return case, [_exp("name", "invalid", "digits")], "name_digits"


def _m_name_emoji(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["name"] = "M!y N@me"
    return case, [_exp("name", "grey", "unusual characters")], "name_unusual_chars"


def _m_name_too_long(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["name"] = "A" * 140
    return case, [_exp("name", "invalid", "exceeds")], "name_too_long"


def _m_name_single_word(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["name"] = "Prince"
    return case, [_exp("name", "grey", "single word")], "name_single_word"


def _m_email_invalid(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["emails"] = ["bad-email-format"]
    return case, [_exp("emails[0]", "invalid", "invalid format")], "email_invalid_format"


def _m_email_typo(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["emails"] = ["jane@gmial.com"]
    return case, [_exp("emails[0]", "grey", "typo")], "email_typo_domain"


def _m_email_empty(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["emails"] = []
    return case, [_exp("emails[0]", "invalid", "No email addresses provided")], "email_missing"


def _m_phone_short(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["phone_numbers"] = ["12345"]
    return case, [_exp("phone_numbers[0]", "invalid", "does not match")], "phone_too_short"


def _m_phone_missing_cc(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["phone_numbers"] = ["9876543210"]
    return case, [_exp("phone_numbers[0]", "valid", "strict E.164")], "phone_missing_country_code"


def _m_phone_us_invalid(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["phone_numbers"] = ["+1 0123456789"]
    return case, [_exp("phone_numbers[0]", "invalid", "invalid area code")], "phone_invalid_us"


def _m_education_reversed(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["education"]["bachelors"]["duration"] = "2025 - 2022"
    return case, [_exp("education.bachelors.duration", "invalid", "before start date")], "education_reversed_dates"


def _m_education_grade_high(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["education"]["bachelors"]["grade"] = 120.0
    return case, [_exp("education.bachelors.grade", "invalid", "exceeds")], "education_invalid_grade"


def _m_education_missing_institution(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["education"]["bachelors"]["institution"] = ""
    return case, [_exp("education.bachelors.institution", "invalid", "too short")], "education_missing_institution"


def _m_experience_overlap(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["experience"] = [
        {
            "role": "Engineer A",
            "company": "CompA",
            "start": "Jan 2020",
            "end": "Jan 2022",
            "points": {"1": "Built distributed systems with reliability focus and measurable outcomes."},
        },
        {
            "role": "Engineer B",
            "company": "CompB",
            "start": "Jun 2021",
            "end": "Dec 2022",
            "points": {"1": "Designed APIs and automated deployment workflows for faster releases."},
        },
    ]
    return case, [
        _exp("experience[0].timeline_overlap", "grey", "Timeline overlap"),
        _exp("experience[1].timeline_overlap", "grey", "Timeline overlap"),
    ], "experience_overlap"


def _m_experience_missing_end(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["experience"][0]["end"] = ""
    return case, [_exp("experience[0].duration", "grey", "End date missing")], "experience_missing_end"


def _m_project_missing_protocol(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["projects"][0]["github"] = "github.com/jane/repo"
    return case, [_exp("projects[0].github", "invalid", "must begin with http")], "project_bad_protocol"


def _m_project_missing_duration(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["projects"][0]["duration"] = ""
    return case, [_exp("projects[0].duration", "grey", "No duration provided")], "project_missing_duration"


def _m_project_short_description(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["projects"][0]["points"] = {"1": "quick work"}
    return case, [_exp("projects[0].description", "grey", "lacks sufficient detail")], "project_weak_description"


def _m_skills_missing(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["skills"] = []
    return case, [_exp("skills", "invalid", "missing or empty")], "skills_missing"


def _m_skills_short(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["skills"] = ["Python", "SQL"]
    return case, [_exp("skills", "grey", "Only 2 skill")], "skills_too_few"


def _m_skills_csv(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["skills"] = "Python, SQL, Docker"
    return case, [_exp("skills", "valid")], "skills_csv_input"


def _m_achievements_missing(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["achievements"] = None
    return case, [_exp("achievements", "grey", "missing")], "achievements_missing"


def _m_responsibilities_missing(case: dict[str, Any]) -> tuple[dict[str, Any], list[Expectation], str]:
    case["responsibilities"] = None
    return case, [_exp("responsibilities", "grey", "missing")], "responsibilities_missing"


MUTATORS: list[Mutator] = [
    _m_valid_compact_duration,
    _m_name_digits,
    _m_name_emoji,
    _m_name_too_long,
    _m_name_single_word,
    _m_email_invalid,
    _m_email_typo,
    _m_email_empty,
    _m_phone_short,
    _m_phone_missing_cc,
    _m_phone_us_invalid,
    _m_education_reversed,
    _m_education_grade_high,
    _m_education_missing_institution,
    _m_experience_overlap,
    _m_experience_missing_end,
    _m_project_missing_protocol,
    _m_project_missing_duration,
    _m_project_short_description,
    _m_skills_missing,
    _m_skills_short,
    _m_skills_csv,
    _m_achievements_missing,
    _m_responsibilities_missing,
]


def _build_case(
    idx: int,
    category: str,
    resume: dict[str, Any],
    expectations: list[Expectation],
    description: str,
) -> dict[str, Any]:
    case = copy.deepcopy(resume)
    case["_meta"] = {
        "id": f"case-{idx:06d}",
        "category": category,
        "description": description,
        "expectations": expectations,
    }
    return case


def generate_massive_cases(count: int, seed: int = 7) -> list[dict[str, Any]]:
    if count < len(MUTATORS):
        raise ValueError(f"count must be >= {len(MUTATORS)} to cover all mutators at least once")

    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    base = _base_resume()

    # Deterministic seed bank: one case per mutator.
    for i, mutator in enumerate(MUTATORS):
        mutated, expectations, category = mutator(copy.deepcopy(base))
        cases.append(_build_case(i, category, mutated, expectations, "seed case"))

    # Massive randomized corpus with controlled mutation classes.
    while len(cases) < count:
        case_idx = len(cases)
        mutator = rng.choice(MUTATORS)
        mutated, expectations, category = mutator(copy.deepcopy(base))
        targeted_roots = {exp["path"].split(".")[0].split("[")[0] for exp in expectations if "path" in exp}
        if "name" not in targeted_roots:
            suffix = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(4))
            mutated["name"] = f"Candidate {suffix} {mutated['name']}"
        if rng.random() < 0.35 and "education" not in targeted_roots:
            # Inject harmless variation to increase parser stress without changing intent.
            mutated["education"]["bachelors"]["degree"] = (
                f"{mutated['education']['bachelors']['degree']} ({rng.choice(['Hons', 'Major', 'AI'])})"
            )
        if rng.random() < 0.20 and "emails" not in targeted_roots and mutated.get("emails"):
            mutated["emails"] = [mutated["emails"][0].upper() if "@" in mutated["emails"][0] else mutated["emails"][0]]
        cases.append(_build_case(case_idx, category, mutated, expectations, "randomized stress case"))

    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a massive deterministic edge-case resume test corpus.")
    parser.add_argument(
        "--output",
        default="data/test_cases/massive_edge_cases.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5000,
        help="Total number of cases to generate",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Deterministic random seed",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cases = generate_massive_cases(count=args.count, seed=args.seed)
    output_path.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {len(cases)} cases at {output_path}")


if __name__ == "__main__":
    main()
