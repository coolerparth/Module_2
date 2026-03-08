#!/usr/bin/env python3
"""
run_validation.py — CLI Entry Point
Smart Resume Audit & Verification System
=========================================
Reads a raw resume JSON file, runs the full validation pipeline from
validation_engine.py, prints a rich console report, and writes the
tri-state output to a JSON file.

Usage
-----
    python run_validation.py <input.json>
    python run_validation.py <input.json> --output <output.json>
    python run_validation.py <input.json> --show-valid
    python run_validation.py <input.json> --no-color
    python run_validation.py <input.json> --quiet

Exit codes
----------
    0   All checks passed (no invalid sections)
    1   One or more invalid sections found
    2   Bad CLI arguments or file-not-found / JSON parse error
    3   Unexpected internal error (bug in engine or environment)

Examples
--------
    python run_validation.py resume.json
    python run_validation.py resume.json --output audit.json
    python run_validation.py resume.json --show-valid --no-color > report.txt
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import textwrap
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Import the validation engine
# ---------------------------------------------------------------------------
try:
    import validation_engine as engine
except ImportError as _exc:
    print(
        f"\n[FATAL] Could not import 'validation_engine': {_exc}\n"
        "Make sure validation_engine.py is in the same directory or on PYTHONPATH.",
        file=sys.stderr,
    )
    sys.exit(3)


# ---------------------------------------------------------------------------
# Terminal styling
# ---------------------------------------------------------------------------

# ANSI codes — stripped automatically when stdout is not a TTY
_ANSI = {
    "reset":     "\033[0m",
    "bold":      "\033[1m",
    "dim":       "\033[2m",
    "red":       "\033[91m",
    "green":     "\033[92m",
    "yellow":    "\033[93m",
    "blue":      "\033[94m",
    "magenta":   "\033[95m",
    "cyan":      "\033[96m",
    "white":     "\033[97m",
    "bg_red":    "\033[41m",
    "bg_green":  "\033[42m",
    "bg_yellow": "\033[43m",
    "bg_blue":   "\033[44m",
}

_USE_COLOR: bool = True   # set to False by --no-color or when not a TTY


def _c(text: str, *styles: str) -> str:
    """Wrap text in ANSI styles if color is enabled."""
    if not _USE_COLOR:
        return text
    codes = "".join(_ANSI.get(s, "") for s in styles)
    return f"{codes}{text}{_ANSI['reset']}"


def _term_width() -> int:
    """Return terminal width, defaulting to 100 for piped output."""
    return shutil.get_terminal_size((100, 24)).columns


def _hr(char: str = "─", width: int | None = None) -> str:
    """Return a horizontal rule."""
    return char * (width or min(_term_width(), 100))


def _wrap(text: str, indent: int = 6, width: int | None = None) -> str:
    """Word-wrap text with a left indent."""
    w = (width or min(_term_width(), 100)) - indent
    prefix = " " * indent
    return textwrap.fill(text, width=w, initial_indent=prefix, subsequent_indent=prefix)


# ---------------------------------------------------------------------------
# Pass-rate label
# ---------------------------------------------------------------------------

def _rate_label(rate: float) -> str:
    """Return a human-readable quality label for a pass rate percentage."""
    if rate >= 90:
        return _c("EXCELLENT", "bold", "green")
    if rate >= 75:
        return _c("GOOD", "bold", "cyan")
    if rate >= 50:
        return _c("NEEDS WORK", "bold", "yellow")
    return _c("POOR", "bold", "red")


# ---------------------------------------------------------------------------
# Console output helpers
# ---------------------------------------------------------------------------

def _print_banner(input_path: Path) -> None:
    w = min(_term_width(), 100)
    print()
    print(_c(_hr("═", w), "cyan"))
    print(_c("   Smart Resume Audit & Verification System", "bold", "cyan"))
    print(_c("   Intelligent Validation Engine  v2.0", "dim"))
    print(_c(_hr("═", w), "cyan"))
    print(f"\n   {_c('File :', 'dim')}  {input_path.resolve()}")
    print(f"   {_c('Time :', 'dim')}  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n")


def _print_summary(output: dict) -> None:
    s = output.get("summary", {})
    total   = s.get("total_checks", 0)
    valid   = s.get("validated_count", 0)
    invalid = s.get("invalid_count", 0)
    grey    = s.get("grey_area_count", 0)
    rate    = s.get("pass_rate", 0.0)

    w = min(_term_width(), 100)
    print(_c(_hr("─", w), "dim"))
    print(_c("  VALIDATION SUMMARY", "bold"))
    print(_c(_hr("─", w), "dim"))
    print()
    print(f"   {_c('Total checks  :', 'dim')}  {_c(str(total), 'bold')}")
    print(f"   {_c('✅ Validated  :', 'dim')}  {_c(str(valid),   'bold', 'green')}")
    print(f"   {_c('❌ Invalid    :', 'dim')}  {_c(str(invalid), 'bold', 'red'   if invalid else 'green')}")
    print(f"   {_c('🟡 Grey Area  :', 'dim')}  {_c(str(grey),   'bold', 'yellow' if grey   else 'green')}")
    print(f"   {_c('Pass Rate     :', 'dim')}  {_c(f'{rate:.1f}%', 'bold')}  {_rate_label(rate)}")
    print()


def _format_data(data: Any, indent: int = 9) -> str:
    """
    Format the data payload of a result node for display.
    Truncates long strings and lists to avoid flooding the terminal.
    """
    if data is None:
        return ""

    if isinstance(data, str):
        truncated = data if len(data) <= 80 else data[:77] + "…"
        return f"{' ' * indent}{_c('Data  :', 'dim')}  {truncated}"

    if isinstance(data, list):
        items = data[:6]
        suffix = f"  … (+{len(data)-6} more)" if len(data) > 6 else ""
        rendered = ", ".join(str(x) for x in items) + suffix
        return f"{' ' * indent}{_c('Data  :', 'dim')}  [{rendered}]"

    if isinstance(data, dict):
        # Show raw duration string if present, otherwise first 2 key-value pairs
        if "raw" in data:
            raw = data["raw"]
            start = data.get("start") or "?"
            end   = data.get("end")   or "?"
            return f"{' ' * indent}{_c('Data  :', 'dim')}  {raw!r}  →  {start} – {end}"
        pairs = list(data.items())[:2]
        rendered = ",  ".join(f"{k}={v!r}" for k, v in pairs)
        if len(data) > 2:
            rendered += f"  … (+{len(data)-2} more fields)"
        return f"{' ' * indent}{_c('Data  :', 'dim')}  {{{rendered}}}"

    return f"{' ' * indent}{_c('Data  :', 'dim')}  {data!r}"


def _print_invalid_sections(output: dict) -> None:
    sections = output.get("invalid_sections", {})
    if not sections:
        return

    w = min(_term_width(), 100)
    count = len(sections)
    heading = f"  ❌  INVALID SECTIONS  ({count} issue{'s' if count != 1 else ''})"
    print(_c(_hr("─", w), "red"))
    print(_c(heading, "bold", "red"))
    print(_c(_hr("─", w), "red"))
    print()

    for i, (path, entry) in enumerate(sections.items(), 1):
        prefix = _c(f"  [{i:02d}]", "bold", "red")
        print(f"{prefix}  {_c(path, 'bold')}")
        error = entry.get("error", "Validation failed.")
        print(_wrap(f"Error : {error}", indent=9))
        data_line = _format_data(entry.get("data"))
        if data_line:
            print(data_line)
        print()


def _print_grey_sections(output: dict) -> None:
    sections = output.get("grey_area", {})
    if not sections:
        return

    w = min(_term_width(), 100)
    count = len(sections)
    heading = f"  🟡  GREY AREA  ({count} item{'s' if count != 1 else ''} need review)"
    print(_c(_hr("─", w), "yellow"))
    print(_c(heading, "bold", "yellow"))
    print(_c(_hr("─", w), "yellow"))
    print()

    for i, (path, entry) in enumerate(sections.items(), 1):
        prefix = _c(f"  [{i:02d}]", "bold", "yellow")
        print(f"{prefix}  {_c(path, 'bold')}")
        note = entry.get("note", "Ambiguous or incomplete.")
        print(_wrap(f"Note  : {note}", indent=9))
        data_line = _format_data(entry.get("data"))
        if data_line:
            print(data_line)
        print()


def _print_validated_sections(output: dict) -> None:
    """Print validated sections — only shown with --show-valid flag."""
    sections = output.get("validated_sections", {})
    if not sections:
        return

    w = min(_term_width(), 100)
    count = len(sections)
    heading = f"  ✅  VALIDATED SECTIONS  ({count} passed)"
    print(_c(_hr("─", w), "green"))
    print(_c(heading, "bold", "green"))
    print(_c(_hr("─", w), "green"))
    print()

    for i, (path, entry) in enumerate(sections.items(), 1):
        prefix = _c(f"  [{i:02d}]", "bold", "green")
        note = entry.get("note", "")
        note_str = f"  {_c(note, 'dim')}" if note else ""
        print(f"{prefix}  {_c(path, 'bold')}{note_str}")
        data_line = _format_data(entry.get("data"))
        if data_line:
            print(data_line)

    print()


def _print_footer(output_path: Path, output: dict) -> None:
    w = min(_term_width(), 100)
    invalid = output.get("summary", {}).get("invalid_count", 0)
    grey    = output.get("summary", {}).get("grey_area_count", 0)

    print(_c(_hr("═", w), "cyan"))

    if invalid == 0 and grey == 0:
        verdict = _c("  ✅  All checks passed — resume data is clean.", "bold", "green")
    elif invalid == 0:
        verdict = _c(
            f"  🟡  No hard failures. {grey} item(s) need manual review.", "bold", "yellow"
        )
    else:
        verdict = _c(
            f"  ❌  {invalid} hard failure(s) found — fix invalid sections before scoring.",
            "bold", "red",
        )

    print(verdict)
    print(f"\n   {_c('Output :', 'dim')}  {output_path.resolve()}")
    print(_c(_hr("═", w), "cyan"))
    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_validation",
        description=(
            "Smart Resume Audit & Verification System — "
            "validates a raw resume JSON through the Intelligent Validation Engine."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            exit codes:
              0   all checks passed (no invalid sections)
              1   one or more invalid sections found
              2   bad arguments, file not found, or JSON parse error
              3   unexpected internal engine error

            examples:
              %(prog)s resume.json
              %(prog)s resume.json --output audit.json
              %(prog)s resume.json --show-valid
              %(prog)s resume.json --quiet --output result.json
              %(prog)s resume.json --no-color > report.txt
        """),
    )

    parser.add_argument(
        "input",
        metavar="INPUT_JSON",
        help="Path to the raw resume JSON file produced by the extraction stage.",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="OUTPUT_JSON",
        default=None,
        help=(
            "Path to write the tri-state validation report as JSON. "
            "Defaults to <input_stem>_validated.json in the same directory."
        ),
    )
    parser.add_argument(
        "--show-valid",
        action="store_true",
        default=False,
        help="Also print the validated (passing) sections to the console.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI color codes (useful for piped output or CI logs).",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help=(
            "Suppress console output except for the final summary counts and "
            "any fatal errors.  The JSON output file is still written."
        ),
    )

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _USE_COLOR

    parser = _build_parser()
    args = parser.parse_args()

    # ── Resolve color mode ────────────────────────────────────────────────────
    # Disable color if: --no-color flag, stdout is not a TTY, or Windows legacy console
    _USE_COLOR = (
        not args.no_color
        and sys.stdout.isatty()
    )

    # ── Resolve paths ─────────────────────────────────────────────────────────
    input_path = Path(args.input)

    if not input_path.exists():
        print(
            f"\n{'[FATAL]':>9}  Input file not found: {input_path.resolve()}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    if not input_path.is_file():
        print(
            f"\n{'[FATAL]':>9}  Input path is not a file: {input_path.resolve()}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    output_path = (
        Path(args.output)
        if args.output
        else input_path.parent / f"{input_path.stem}_validated.json"
    )

    # ── Banner ────────────────────────────────────────────────────────────────
    if not args.quiet:
        _print_banner(input_path)

    # ── Load and parse input JSON ─────────────────────────────────────────────
    if not args.quiet:
        print(f"   {_c('Loading  :', 'dim')}  {input_path}")

    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"\n{'[FATAL]':>9}  Could not read '{input_path}': {exc}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        raw_json = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(
            f"\n{'[FATAL]':>9}  Invalid JSON in '{input_path}':\n"
            f"{'':>9}  {exc}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    if not isinstance(raw_json, dict):
        print(
            f"\n{'[FATAL]':>9}  JSON root must be an object (dict), "
            f"got {type(raw_json).__name__}.\n",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── Run validation pipeline ───────────────────────────────────────────────
    if not args.quiet:
        print(f"   {_c('Pipeline :', 'dim')}  running validation checks …\n")

    try:
        output = engine.run(raw_json)
    except TypeError as exc:
        # validate_resume() raises TypeError on non-dict input (caught above,
        # but guard here in case engine internals raise one unexpectedly)
        print(
            f"\n{'[FATAL]':>9}  Validation engine raised TypeError: {exc}\n",
            file=sys.stderr,
        )
        sys.exit(3)
    except Exception as exc:  # pylint: disable=broad-except
        print(
            f"\n{'[FATAL]':>9}  Unexpected error in validation engine:\n",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        sys.exit(3)

    # ── Validate output structure ─────────────────────────────────────────────
    required_keys = {"summary", "validated_sections", "invalid_sections", "grey_area"}
    if not required_keys.issubset(output.keys()):
        missing = required_keys - output.keys()
        print(
            f"\n{'[FATAL]':>9}  Engine output is missing required keys: {missing}\n"
            "        This indicates a version mismatch between run_validation.py "
            "and validation_engine.py.\n",
            file=sys.stderr,
        )
        sys.exit(3)

    # ── Write output JSON ─────────────────────────────────────────────────────
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        print(
            f"\n{'[ERROR]':>9}  Could not write output to '{output_path}': {exc}\n",
            file=sys.stderr,
        )
        # Non-fatal: we still print the console report and exit with correct code
    else:
        if not args.quiet:
            print(f"   {_c('Output   :', 'dim')}  {output_path.resolve()}\n")

    # ── Console report ────────────────────────────────────────────────────────
    if not args.quiet:
        _print_summary(output)

        if args.show_valid:
            _print_validated_sections(output)

        _print_invalid_sections(output)
        _print_grey_sections(output)
        _print_footer(output_path, output)

    else:
        # --quiet mode: only print the one-line summary to stdout
        s = output["summary"]
        print(
            f"total={s['total_checks']}  "
            f"valid={s['validated_count']}  "
            f"invalid={s['invalid_count']}  "
            f"grey={s['grey_area_count']}  "
            f"pass_rate={s['pass_rate']}%"
        )

    # ── Exit code ─────────────────────────────────────────────────────────────
    # 0 = clean, 1 = has invalid sections (signals downstream not to proceed)
    invalid_count = output.get("summary", {}).get("invalid_count", 0)
    sys.exit(1 if invalid_count > 0 else 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()