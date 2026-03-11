import json

import pytest

from scripts.evaluate_engine import evaluate
from scripts.generate_massive_tests import generate_massive_cases


def test_massive_generator_shapes_cases():
    cases = generate_massive_cases(count=300, seed=11)
    assert len(cases) == 300
    assert all("_meta" in case for case in cases)
    assert all(case["_meta"]["expectations"] for case in cases)


@pytest.mark.asyncio
async def test_massive_evaluation_reaches_high_semantic_accuracy(tmp_path):
    input_path = tmp_path / "massive_cases.json"
    output_path = tmp_path / "massive_report.json"

    cases = generate_massive_cases(count=400, seed=13)
    input_path.write_text(json.dumps(cases, indent=2), encoding="utf-8")

    await evaluate(str(input_path), str(output_path), concurrency=80, include_full_output=False)

    report = json.loads(output_path.read_text(encoding="utf-8"))
    summary = report["summary"]
    assert summary["exceptions"] == 0
    assert summary["semantic_accuracy"] >= 95.0
