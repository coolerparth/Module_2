from __future__ import annotations

from typing import Any, Literal, TypedDict, Union

__all__ = ["ResultNode", "ValidResult", "InvalidResult", "GreyResult", "ok", "fail", "grey"]


class ValidResult(TypedDict):
    status: Literal["valid"]
    data: Any
    note: str


class InvalidResult(TypedDict):
    status: Literal["invalid"]
    data: Any
    error: str


class GreyResult(TypedDict):
    status: Literal["grey"]
    data: Any
    note: str


ResultNode = Union[ValidResult, InvalidResult, GreyResult]


def ok(data: Any, note: str = "") -> ValidResult:
    return {"status": "valid", "data": data, "note": note}


def fail(data: Any, error: str) -> InvalidResult:
    return {"status": "invalid", "data": data, "error": error}


def grey(data: Any, note: str) -> GreyResult:
    return {"status": "grey", "data": data, "note": note}
