import asyncio
from unittest.mock import patch

import pytest

from src import validators
from src.validators import (
    _validate_url_async,
    duration_payload_to_range,
    validate_duration,
    validate_email,
    validate_name,
    validate_phone,
)


def test_validate_name_rules():
    assert validate_name("Jane Doe")["status"] == "valid"
    assert validate_name("John 123 Doe")["status"] == "invalid"
    assert validate_name("Prince")["status"] == "grey"


def test_validate_email_rules():
    assert validate_email("jane.doe@gmail.com")["status"] == "valid"
    assert validate_email("bad-email")["status"] == "invalid"
    assert validate_email("jane@gmial.com")["status"] == "grey"


def test_validate_phone_rules():
    assert validate_phone("+91 9876543210")["status"] == "valid"
    assert validate_phone("9876543210")["status"] == "grey"
    assert validate_phone("12345")["status"] == "invalid"


def test_validate_duration_supports_compact_year_range():
    result = validate_duration("2018-2022", "Education")
    assert result["status"] == "valid"
    assert result["data"]["start"] == "2018-01-01"
    assert result["data"]["end"] == "2022-01-01"


def test_validate_duration_detects_impossible_timeline():
    result = validate_duration("2025 - 2022", "Education")
    assert result["status"] == "invalid"
    assert "before start date" in result["error"]


def test_duration_payload_to_range_handles_present_token():
    span = duration_payload_to_range({"start": "2020-01-01", "end": "Present"})
    assert span is not None
    start, end = span
    assert start.year == 2020
    assert end >= start


@pytest.mark.asyncio
async def test_url_timeout_returns_grey_in_balanced_mode(monkeypatch):
    monkeypatch.setattr(validators, "URL_POLICY", "balanced")
    with patch("aiohttp.ClientSession._request") as mock_request:
        mock_request.side_effect = asyncio.TimeoutError("simulated timeout")
        result = await _validate_url_async("https://example.com/timeout", "Portfolio")
    assert result["status"] == "grey"
    assert "could not be verified" in result["note"]
    assert mock_request.call_count == 2


@pytest.mark.asyncio
async def test_url_invalid_scheme_fails_fast():
    result = await _validate_url_async("github.com/no-scheme", "GitHub")
    assert result["status"] == "invalid"
    assert "must begin with http://" in result["error"]
