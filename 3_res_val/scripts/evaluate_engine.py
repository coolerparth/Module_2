import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from src.engine import run_async

STATUS_TO_SECTION = {
    "valid": "validated_sections",
    "invalid": "invalid_sections",
    "grey": "grey_area",
}

STATUS_TO_MESSAGE_FIELD = {
    "valid": "note",
    "invalid": "error",
    "grey": "note",
}


def _evaluate_expectation(output: dict[str, Any], expectation: dict[str, str]) -> tuple[bool, str | None]:
    status = expectation.get("status")
    path = expectation.get("path")
    contains = expectation.get("contains")

    if status not in STATUS_TO_SECTION:
        return False, f"unsupported expected status '{status}'"
    if not path:
        return False, "missing expected path"

    section_name = STATUS_TO_SECTION[status]
    section = output.get(section_name, {})
    if path not in section:
        return False, f"path '{path}' missing in {section_name}"

    if contains:
        msg_field = STATUS_TO_MESSAGE_FIELD[status]
        msg = str(section[path].get(msg_field, ""))
        if contains.lower() not in msg.lower():
            return False, f"path '{path}' does not contain expected text '{contains}'"

    return True, None


async def _run_case(case: dict[str, Any], sem: asyncio.Semaphore) -> dict[str, Any]:
    async with sem:
        return await run_async(case)


async def evaluate(
    input_path: str,
    output_path: str,
    *,
    concurrency: int = 200,
    include_full_output: bool = False,
) -> None:
    input_file = Path(input_path)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with input_file.open("r", encoding="utf-8") as f:
        cases: list[dict[str, Any]] = json.load(f)

    start = time.perf_counter()
    sem = asyncio.Semaphore(concurrency)
    tasks = [asyncio.create_task(_run_case(case, sem)) for case in cases]
    resolved = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.perf_counter() - start

    total_cases = len(cases)
    exceptions = 0
    total_checks = valid = invalid = grey = 0
    expectations_total = expectations_passed = 0
    category_totals: Counter[str] = Counter()
    category_expectations: Counter[str] = Counter()
    category_passed: Counter[str] = Counter()
    category_exceptions: Counter[str] = Counter()
    mismatch_samples: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []

    for case, result in zip(cases, resolved):
        meta = case.get("_meta", {})
        category = str(meta.get("category", "uncategorized"))
        case_id = str(meta.get("id", f"case-{len(outputs)}"))
        expectations = meta.get("expectations", [])
        category_totals[category] += 1

        if isinstance(result, Exception):
            exceptions += 1
            category_exceptions[category] += 1
            outputs.append(
                {
                    "id": case_id,
                    "category": category,
                    "exception": str(result),
                }
            )
            continue

        summary = result.get("summary", {})
        total_checks += int(summary.get("total_checks", 0))
        valid += int(summary.get("validated_count", 0))
        invalid += int(summary.get("invalid_count", 0))
        grey += int(summary.get("grey_area_count", 0))

        passed_for_case = 0
        mismatches_for_case: list[str] = []
        for exp in expectations:
            expectations_total += 1
            category_expectations[category] += 1
            ok, why = _evaluate_expectation(result, exp)
            if ok:
                expectations_passed += 1
                category_passed[category] += 1
                passed_for_case += 1
            else:
                mismatch = why or "unknown mismatch"
                mismatches_for_case.append(mismatch)
                if len(mismatch_samples) < 120:
                    mismatch_samples.append(
                        {
                            "id": case_id,
                            "category": category,
                            "expectation": exp,
                            "reason": mismatch,
                        }
                    )

        payload: dict[str, Any] = {
            "id": case_id,
            "category": category,
            "summary": summary,
            "expectations_total": len(expectations),
            "expectations_passed": passed_for_case,
        }
        if mismatches_for_case:
            payload["mismatches"] = mismatches_for_case[:5]
        if include_full_output:
            payload["output"] = result
        outputs.append(payload)

    semantic_accuracy = (
        round((expectations_passed / expectations_total) * 100, 2) if expectations_total else 0.0
    )
    partition_pass_rate = round((valid / total_checks) * 100, 2) if total_checks else 0.0
    crash_free_rate = round(((total_cases - exceptions) / total_cases) * 100, 2) if total_cases else 0.0
    avg_ms_per_case = round((elapsed / total_cases) * 1000, 3) if total_cases else 0.0

    category_accuracy: list[dict[str, Any]] = []
    for category in sorted(category_totals):
        exp_total = category_expectations[category]
        exp_passed = category_passed[category]
        category_accuracy.append(
            {
                "category": category,
                "cases": category_totals[category],
                "exceptions": category_exceptions[category],
                "expectations_total": exp_total,
                "expectations_passed": exp_passed,
                "assertion_accuracy": round((exp_passed / exp_total) * 100, 2) if exp_total else None,
            }
        )

    report = {
        "summary": {
            "total_cases": total_cases,
            "elapsed_seconds": round(elapsed, 3),
            "avg_ms_per_case": avg_ms_per_case,
            "exceptions": exceptions,
            "crash_free_rate": crash_free_rate,
            "total_checks": total_checks,
            "validated_count": valid,
            "invalid_count": invalid,
            "grey_area_count": grey,
            "partition_pass_rate": partition_pass_rate,
            "expectations_total": expectations_total,
            "expectations_passed": expectations_passed,
            "semantic_accuracy": semantic_accuracy,
        },
        "category_accuracy": category_accuracy,
        "mismatch_samples": mismatch_samples,
        "results": outputs,
    }

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("=" * 68)
    print("RESUME VALIDATION MASSIVE EVALUATION REPORT")
    print("=" * 68)
    print(f"Cases processed      : {total_cases}")
    print(f"Elapsed time         : {elapsed:.3f}s")
    print(f"Avg latency          : {avg_ms_per_case:.3f} ms/case")
    print(f"Exceptions           : {exceptions} (crash-free {crash_free_rate:.2f}%)")
    print("-" * 68)
    print(f"Total checks         : {total_checks}")
    print(f"Validated            : {valid}")
    print(f"Invalid              : {invalid}")
    print(f"Grey                 : {grey}")
    print(f"Partition pass rate  : {partition_pass_rate:.2f}%")
    print("-" * 68)
    print(f"Expectation checks   : {expectations_total}")
    print(f"Expectation passed   : {expectations_passed}")
    print(f"Semantic accuracy    : {semantic_accuracy:.2f}%")
    print("=" * 68)
    print(f"Saved report to {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run massive deterministic evaluation against the validation engine.")
    parser.add_argument("input_path", help="Path to generated massive test case JSON")
    parser.add_argument("output_path", help="Path to write evaluation report JSON")
    parser.add_argument("--concurrency", type=int, default=200, help="Async worker concurrency")
    parser.add_argument(
        "--include-full-output",
        action="store_true",
        help="Store complete engine output for each case in the report",
    )
    args = parser.parse_args()

    asyncio.run(
        evaluate(
            args.input_path,
            args.output_path,
            concurrency=args.concurrency,
            include_full_output=args.include_full_output,
        )
    )


if __name__ == "__main__":
    main()
