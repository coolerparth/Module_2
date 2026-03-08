#!/usr/bin/env python3
"""
run_validation.py — CLI Entry Point
Smart Resume Audit & Verification System
=========================================
Usage:
    python run_validation.py <input.json> [--output <output.json>]

Example:
    python run_validation.py sample_input.json --output result.json
    python run_validation.py sample_output.json
"""

import argparse
import json
import sys
from pathlib import Path

import validator


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _print_banner():
    print("\n" + "=" * 60)
    print("   Smart Resume Audit & Verification System")
    print("   Intelligent Validation Engine  v1.0")
    print("=" * 60 + "\n")


def _print_summary(output: dict):
    s = output.get("summary", {})
    total = s.get("total_checks", 0)
    valid = s.get("validated_count", 0)
    invalid = s.get("invalid_count", 0)
    grey = s.get("grey_area_count", 0)

    print("\n── Validation Summary ──────────────────────────────────────")
    print(f"   Total checks   : {total}")
    print(f"   ✅ Validated   : {valid}")
    print(f"   ❌ Invalid     : {invalid}")
    print(f"   🟡 Grey Area   : {grey}")
    print("────────────────────────────────────────────────────────────\n")

    if invalid > 0:
        print("── ❌ Invalid Sections ──────────────────────────────────────")
        for path, entry in output.get("invalid_sections", {}).items():
            print(f"   [{path}]")
            print(f"      Error : {entry.get('error', 'Unknown error')}")
            data = entry.get("data")
            if data is not None:
                print(f"      Data  : {data}")
        print()

    if grey > 0:
        print("── 🟡 Grey Area Sections ────────────────────────────────────")
        for path, entry in output.get("grey_area", {}).items():
            print(f"   [{path}]")
            print(f"      Note  : {entry.get('note', '')}")
            data = entry.get("data")
            if data is not None:
                print(f"      Data  : {data}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    _print_banner()

    parser = argparse.ArgumentParser(
        description="Validate a raw resume JSON through the Intelligent Validation Engine."
    )
    parser.add_argument("input", help="Path to the raw resume JSON file.")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Path to write the tri-state output JSON. Defaults to <input_stem>_validated.json",
    )
    args = parser.parse_args()

    # ── Load input ────────────────────────────────────────────────
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌  File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"📄  Loading input  : {input_path.resolve()}")
    with open(input_path, "r", encoding="utf-8") as f:
        try:
            raw_json = json.load(f)
        except json.JSONDecodeError as exc:
            print(f"❌  Invalid JSON in '{input_path}': {exc}", file=sys.stderr)
            sys.exit(1)

    # ── Run validation pipeline ───────────────────────────────────
    print("🔍  Running validation pipeline …\n")
    output = validator.run(raw_json)

    # ── Determine output path ─────────────────────────────────────
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_validated.json"

    # ── Write output ──────────────────────────────────────────────
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"✅  Output written : {output_path.resolve()}")

    # ── Print console summary ─────────────────────────────────────
    _print_summary(output)


if __name__ == "__main__":
    main()
