import pytest

from src.engine import run_async
from src.models import ValidationOutput


@pytest.mark.asyncio
async def test_engine_output_schema_and_summary_invariants():
    payload = {
        "name": "Jane Doe",
        "emails": ["jane.doe@gmail.com"],
        "phone_numbers": ["+91 9876543210"],
        "skills": ["Python", "Pydantic", "Testing"],
    }

    output = await run_async(payload)
    ValidationOutput.model_validate(output)

    summary = output["summary"]
    total = summary["validated_count"] + summary["invalid_count"] + summary["grey_area_count"]
    assert summary["total_checks"] == total


@pytest.mark.asyncio
async def test_experience_overlap_detection_marks_both_entries():
    payload = {
        "name": "Jane Doe",
        "emails": ["jane.doe@gmail.com"],
        "phone_numbers": ["+91 9876543210"],
        "skills": ["Python", "Pydantic", "Testing"],
        "experience": [
            {
                "role": "Engineer A",
                "company": "Comp A",
                "start": "Jan 2020",
                "end": "Jan 2022",
                "points": {"1": "Delivered distributed systems at scale with measurable reliability gains."},
            },
            {
                "role": "Engineer B",
                "company": "Comp B",
                "start": "Jun 2021",
                "end": "Dec 2022",
                "points": {"1": "Built API platform components and improved release quality significantly."},
            },
        ],
    }
    output = await run_async(payload)
    grey = output["grey_area"]
    assert "experience[0].timeline_overlap" in grey
    assert "experience[1].timeline_overlap" in grey


@pytest.mark.asyncio
async def test_schema_errors_are_returned_as_invalid_sections():
    payload = {
        "name": "Jane Doe",
        "emails": [None],  # invalid list item type for list[str]
        "skills": ["Python", "Pydantic", "Testing"],
    }
    output = await run_async(payload)
    assert output["summary"]["invalid_count"] > 0
    assert any("emails" in path for path in output["invalid_sections"])


@pytest.mark.asyncio
async def test_skills_csv_input_is_coerced_by_model():
    payload = {
        "name": "Jane Doe",
        "emails": ["jane.doe@gmail.com"],
        "phone_numbers": ["+91 9876543210"],
        "skills": "Python, SQL, Docker",
    }
    output = await run_async(payload)
    assert output["validated_sections"]["skills"]["data"] == ["Python", "SQL", "Docker"]
