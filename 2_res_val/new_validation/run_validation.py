#!/usr/bin/env python3
"""
run_validation.py — CLI Entry Point
Smart Resume Audit & Verification System
=========================================
Reads a raw resume JSON file, runs the full validation pipeline from
validation_engine.py, prints a rich console report, and writes the
tri-state output to a JSON file.

Country configuration
---------------------
Country is resolved in this priority order (highest to lowest):
    1. --country flag on the CLI                   python run_validation.py resume.json --country GB
    2. --country-config flag (custom JSON profile) python run_validation.py resume.json --country-config my.json
    3. RESUME_COUNTRY environment variable         RESUME_COUNTRY=GB python run_validation.py resume.json
    4. Module-level default in validation_engine   (default: IN — India)

Usage
-----
    python run_validation.py <input.json>
    python run_validation.py <input.json> --country GB
    python run_validation.py <input.json> --country-config my_country.json
    python run_validation.py <input.json> --output result.json
    python run_validation.py <input.json> --show-valid
    python run_validation.py <input.json> --no-color
    python run_validation.py <input.json> --quiet
    python run_validation.py --list-countries

Exit codes
----------
    0   All checks passed (no invalid sections)
    1   One or more invalid sections found
    2   Bad CLI arguments, file not found, or JSON parse error
    3   Unexpected internal engine error
"""

from __future__ import annotations

import argparse
import json
import os
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
        f"\n  [FATAL]  Could not import 'validation_engine': {_exc}\n"
        "           Make sure validation_engine.py is in the same directory "
        "or on PYTHONPATH.\n",
        file=sys.stderr,
    )
    sys.exit(3)


# ===========================================================================
# TERMINAL STYLING
# ===========================================================================

_ANSI: dict[str, str] = {
    "reset":     "\033[0m",
    "bold":      "\033[1m",
    "dim":       "\033[2m",
    "red":       "\033[91m",
    "green":     "\033[92m",
    "yellow":    "\033[93m",
    "blue":      "\033[94m",
    "cyan":      "\033[96m",
    "white":     "\033[97m",
}

_USE_COLOR: bool = True   # toggled by --no-color or non-TTY stdout


def _c(text: str, *styles: str) -> str:
    """Wrap text in ANSI escape codes if color is enabled."""
    if not _USE_COLOR:
        return text
    code = "".join(_ANSI.get(s, "") for s in styles)
    return f"{code}{text}{_ANSI['reset']}"


def _tw() -> int:
    """Return terminal width capped at 100 columns."""
    return min(shutil.get_terminal_size((100, 24)).columns, 100)


def _hr(char: str = "─") -> str:
    return char * _tw()


def _wrap(text: str, indent: int = 9) -> str:
    """Word-wrap text with a fixed left indent."""
    prefix = " " * indent
    return textwrap.fill(
        text,
        width=max(_tw() - indent, 40),
        initial_indent=prefix,
        subsequent_indent=prefix,
    )


def _rate_label(rate: float) -> str:
    """Human-readable quality label for a pass-rate percentage."""
    if rate >= 90:
        return _c("EXCELLENT", "bold", "green")
    if rate >= 75:
        return _c("GOOD",      "bold", "cyan")
    if rate >= 50:
        return _c("NEEDS WORK","bold", "yellow")
    return     _c("POOR",      "bold", "red")


# ===========================================================================
# CONSOLE SECTION PRINTERS
# ===========================================================================

def _print_banner(input_path: Path, country_code: str, country_name: str) -> None:
    print()
    print(_c(_hr("═"), "cyan"))
    print(_c("   Smart Resume Audit & Verification System", "bold", "cyan"))
    print(_c("   Intelligent Validation Engine  v2.0", "dim"))
    print(_c(_hr("═"), "cyan"))
    print(f"\n   {_c('File    :', 'dim')}  {input_path.resolve()}")
    print(f"   {_c('Country :', 'dim')}  {country_name} ({country_code})")
    print(f"   {_c('Time    :', 'dim')}  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n")


def _print_summary(output: dict) -> None:
    s = output.get("summary", {})
    total   = s.get("total_checks",    0)
    valid   = s.get("validated_count", 0)
    invalid = s.get("invalid_count",   0)
    grey    = s.get("grey_area_count", 0)
    rate    = s.get("pass_rate",       0.0)

    print(_c(_hr(), "dim"))
    print(_c("  VALIDATION SUMMARY", "bold"))
    print(_c(_hr(), "dim"))
    print()
    print(f"   {_c('Total checks  :', 'dim')}  {_c(str(total), 'bold')}")
    print(f"   {_c('Validated  ✅ :', 'dim')}  {_c(str(valid),   'bold', 'green')}")
    print(f"   {_c('Invalid    ❌ :', 'dim')}  "
          f"{_c(str(invalid), 'bold', 'red'    if invalid else 'green')}")
    print(f"   {_c('Grey Area  🟡 :', 'dim')}  "
          f"{_c(str(grey),    'bold', 'yellow' if grey    else 'green')}")
    print(f"   {_c('Pass Rate     :', 'dim')}  "
          f"{_c(f'{rate:.1f}%', 'bold')}  {_rate_label(rate)}")
    print()


def _format_data(data: Any) -> str:
    """
    Format a result node's data payload for display.
    Truncates strings at 80 chars and lists at 6 items to avoid flooding.
    """
    if data is None:
        return ""

    indent = " " * 9

    if isinstance(data, str):
        s = data if len(data) <= 80 else data[:77] + "…"
        return f"{indent}{_c('Data :', 'dim')}  {s}"

    if isinstance(data, list):
        preview = data[:6]
        suffix  = f"  … (+{len(data) - 6} more)" if len(data) > 6 else ""
        return f"{indent}{_c('Data :', 'dim')}  [{', '.join(str(x) for x in preview)}{suffix}]"

    if isinstance(data, dict):
        if "raw" in data:
            start = data.get("start") or "?"
            end   = data.get("end")   or "?"
            return f"{indent}{_c('Data :', 'dim')}  {data['raw']!r}  →  {start} – {end}"
        pairs   = list(data.items())[:2]
        preview = ",  ".join(f"{k}={v!r}" for k, v in pairs)
        suffix  = f"  … (+{len(data) - 2} more)" if len(data) > 2 else ""
        return f"{indent}{_c('Data :', 'dim')}  {{{preview}{suffix}}}"

    return f"{indent}{_c('Data :', 'dim')}  {data!r}"


def _print_invalid_sections(output: dict) -> None:
    sections = output.get("invalid_sections", {})
    if not sections:
        return

    count = len(sections)
    print(_c(_hr(), "red"))
    print(_c(f"  ❌  INVALID SECTIONS  ({count} issue{'s' if count != 1 else ''})", "bold", "red"))
    print(_c(_hr(), "red"))
    print()

    for i, (path, entry) in enumerate(sections.items(), 1):
        print(f"  {_c(f'[{i:02d}]', 'bold', 'red')}  {_c(path, 'bold')}")
        print(_wrap(f"Error : {entry.get('error', 'Validation failed.')}"))
        data_line = _format_data(entry.get("data"))
        if data_line:
            print(data_line)
        print()


def _print_grey_sections(output: dict) -> None:
    sections = output.get("grey_area", {})
    if not sections:
        return

    count = len(sections)
    print(_c(_hr(), "yellow"))
    print(_c(
        f"  🟡  GREY AREA  ({count} item{'s' if count != 1 else ''} need review)",
        "bold", "yellow",
    ))
    print(_c(_hr(), "yellow"))
    print()

    for i, (path, entry) in enumerate(sections.items(), 1):
        print(f"  {_c(f'[{i:02d}]', 'bold', 'yellow')}  {_c(path, 'bold')}")
        print(_wrap(f"Note  : {entry.get('note', 'Ambiguous or incomplete.')}"))
        data_line = _format_data(entry.get("data"))
        if data_line:
            print(data_line)
        print()


def _print_validated_sections(output: dict) -> None:
    """Only shown with --show-valid flag."""
    sections = output.get("validated_sections", {})
    if not sections:
        return

    count = len(sections)
    print(_c(_hr(), "green"))
    print(_c(f"  ✅  VALIDATED SECTIONS  ({count} passed)", "bold", "green"))
    print(_c(_hr(), "green"))
    print()

    for i, (path, entry) in enumerate(sections.items(), 1):
        note = entry.get("note", "")
        note_str = f"  {_c(note, 'dim')}" if note else ""
        print(f"  {_c(f'[{i:02d}]', 'bold', 'green')}  {_c(path, 'bold')}{note_str}")
        data_line = _format_data(entry.get("data"))
        if data_line:
            print(data_line)

    print()


def _print_footer(output_path: Path, output: dict) -> None:
    s       = output.get("summary", {})
    invalid = s.get("invalid_count",   0)
    grey    = s.get("grey_area_count", 0)

    print(_c(_hr("═"), "cyan"))

    if invalid == 0 and grey == 0:
        print(_c("  ✅  All checks passed — resume data is clean.", "bold", "green"))
    elif invalid == 0:
        print(_c(
            f"  🟡  No hard failures — {grey} item(s) need manual review.",
            "bold", "yellow",
        ))
    else:
        print(_c(
            f"  ❌  {invalid} hard failure(s) found — fix invalid sections before scoring.",
            "bold", "red",
        ))

    print(f"\n   {_c('Output :', 'dim')}  {output_path.resolve()}")
    print(_c(_hr("═"), "cyan"))
    print()


def _print_country_list() -> None:
    """Print all registered country profiles (for --list-countries)."""
    countries = engine.list_countries()
    active    = engine.get_active_country()

    print()
    print(_c(_hr("═"), "cyan"))
    print(_c("   Registered Country Profiles", "bold", "cyan"))
    print(_c(_hr("═"), "cyan"))
    print()

    for c in countries:
        marker = _c("  ← active", "green") if c["code"] == active else ""
        print(f"   {_c(c['code'].ljust(10), 'bold')}  {c['name']}{marker}")

    print()
    env_val = os.environ.get(engine._ENV_VAR, "")
    print(f"   {_c('Active profile :', 'dim')}  {active}")
    if env_val:
        print(f"   {_c('(set via env var RESUME_COUNTRY=' + env_val + ')', 'dim')}")
    print()
    print(f"   {_c('Override at runtime :', 'dim')}  --country <CODE>")
    print(f"   {_c('Custom profile      :', 'dim')}  --country-config <file.json>")
    print(f"   {_c('Set for whole app   :', 'dim')}  RESUME_COUNTRY=<CODE> python run_validation.py …")
    print()


# ===========================================================================
# ARGUMENT PARSER
# ===========================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_validation",
        description=(
            "Smart Resume Audit & Verification System — "
            "validates a raw resume JSON through the Intelligent Validation Engine."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            country configuration (priority order):
              1. --country CODE             set for this run only
              2. --country-config FILE      load a custom country profile
              3. RESUME_COUNTRY=CODE        environment variable
              4. engine default (IN)        hard-coded fallback

            built-in country codes:
              IN  India          US  United States     CA  Canada
              GB  United Kingdom AE  UAE               AU  Australia
              DE  Germany        SG  Singapore         CN  China
              GENERIC           (any country, relaxed phone rules)

            exit codes:
              0   all checks passed (no invalid sections)
              1   one or more invalid sections found
              2   bad arguments, file not found, or JSON parse error
              3   unexpected internal engine error

            examples:
              %(prog)s resume.json
              %(prog)s resume.json --country GB
              %(prog)s resume.json --country-config malaysia.json
              %(prog)s resume.json --output audit.json --show-valid
              %(prog)s resume.json --quiet --output result.json
              %(prog)s resume.json --no-color > report.txt
              %(prog)s --list-countries
              RESUME_COUNTRY=US %(prog)s resume.json
        """),
    )

    parser.add_argument(
        "input",
        metavar="INPUT_JSON",
        nargs="?",
        default=None,
        help="Path to the raw resume JSON file.",
    )

    # ── Country options ───────────────────────────────────────────────────────
    country_group = parser.add_mutually_exclusive_group()
    country_group.add_argument(
        "--country", "-c",
        metavar="CODE",
        default=None,
        help=(
            "ISO 3166-1 alpha-2 country code for this run, e.g. GB, US, AE. "
            "Overrides RESUME_COUNTRY env var. "
            "Run --list-countries to see all built-in codes."
        ),
    )
    country_group.add_argument(
        "--country-config",
        metavar="JSON_FILE",
        default=None,
        help=(
            "Path to a custom country profile JSON file. "
            "Loaded and activated before validation runs. "
            "See validation_engine.configure_from_file() for the schema."
        ),
    )

    # ── Output options ────────────────────────────────────────────────────────
    parser.add_argument(
        "--output", "-o",
        metavar="OUTPUT_JSON",
        default=None,
        help=(
            "Path to write the tri-state validation report as JSON. "
            "Defaults to <input_stem>_validated.json in the same directory."
        ),
    )

    # ── Display options ───────────────────────────────────────────────────────
    parser.add_argument(
        "--show-valid",
        action="store_true",
        default=False,
        help="Also print validated (passing) sections to the console.",
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
            "Suppress all console output except one summary line and fatal errors. "
            "The JSON output file is still written."
        ),
    )

    # ── Utility ───────────────────────────────────────────────────────────────
    parser.add_argument(
        "--list-countries",
        action="store_true",
        default=False,
        help="Print all registered country profiles and exit.",
    )

    return parser


# ===========================================================================
# MAIN
# ===========================================================================

def main() -> None:
    global _USE_COLOR

    parser = _build_parser()
    args   = parser.parse_args()

    # ── Color mode ────────────────────────────────────────────────────────────
    _USE_COLOR = not args.no_color and sys.stdout.isatty()

    # ── --list-countries (no input file needed) ───────────────────────────────
    if args.list_countries:
        _print_country_list()
        sys.exit(0)

    # ── Input file is required for all other operations ───────────────────────
    if not args.input:
        parser.error("INPUT_JSON is required unless --list-countries is used.")

    # ── Apply country config ──────────────────────────────────────────────────
    # Priority: --country-config > --country > env var > engine default
    country_arg: str | None = None   # passed to engine.run()

    if args.country_config:
        cfg_path = Path(args.country_config)
        if not cfg_path.exists():
            print(
                f"\n  [FATAL]  Country config file not found: {cfg_path.resolve()}\n",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            engine.configure_from_file(cfg_path)
            # configure_from_file sets module default; country_arg stays None
            # so engine.run() picks up the new default automatically
        except (ValueError, OSError) as exc:
            print(f"\n  [FATAL]  Invalid country config: {exc}\n", file=sys.stderr)
            sys.exit(2)

    elif args.country:
        country_arg = args.country.strip().upper()
        # Validate the code early for a clear error message
        known = {c["code"] for c in engine.list_countries()}
        if country_arg not in known:
            print(
                f"\n  [FATAL]  Unknown country code '{country_arg}'.\n"
                f"           Known codes: {sorted(known)}\n"
                "           Use --country-config to add a custom profile.\n",
                file=sys.stderr,
            )
            sys.exit(2)

    # Resolve display name for the banner
    active_profile_code = country_arg or engine.get_active_country()
    active_profile_name = next(
        (c["name"] for c in engine.list_countries() if c["code"] == active_profile_code),
        "Unknown",
    )

    # ── Resolve paths ─────────────────────────────────────────────────────────
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"\n  [FATAL]  Input file not found: {input_path.resolve()}\n", file=sys.stderr)
        sys.exit(2)
    if not input_path.is_file():
        print(f"\n  [FATAL]  Input path is not a file: {input_path.resolve()}\n", file=sys.stderr)
        sys.exit(2)

    output_path = (
        Path(args.output)
        if args.output
        else input_path.parent / f"{input_path.stem}_validated.json"
    )

    # ── Banner ────────────────────────────────────────────────────────────────
    if not args.quiet:
        _print_banner(input_path, active_profile_code, active_profile_name)
        print(f"   {_c('Loading  :', 'dim')}  {input_path}")

    # ── Load and parse input JSON ─────────────────────────────────────────────
    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"\n  [FATAL]  Could not read '{input_path}': {exc}\n", file=sys.stderr)
        sys.exit(2)

    try:
        raw_json = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(
            f"\n  [FATAL]  Invalid JSON in '{input_path}':\n"
            f"           {exc}\n",
            file=sys.stderr,
        )
        sys.exit(2)

    if not isinstance(raw_json, dict):
        print(
            f"\n  [FATAL]  JSON root must be an object (dict), "
            f"got {type(raw_json).__name__}.\n",
            file=sys.stderr,
        )
        sys.exit(2)

    # ── Run validation pipeline ───────────────────────────────────────────────
    if not args.quiet:
        print(f"   {_c('Pipeline :', 'dim')}  running validation checks …\n")

    try:
        output = engine.run(raw_json, country=country_arg)
    except TypeError as exc:
        print(f"\n  [FATAL]  Validation engine TypeError: {exc}\n", file=sys.stderr)
        sys.exit(3)
    except Exception:  # pylint: disable=broad-except
        print("\n  [FATAL]  Unexpected error in validation engine:\n", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(3)

    # ── Verify output structure (guard against version mismatch) ─────────────
    required_keys = {"meta", "summary", "validated_sections", "invalid_sections", "grey_area"}
    missing_keys  = required_keys - output.keys()
    if missing_keys:
        print(
            f"\n  [FATAL]  Engine output is missing keys: {missing_keys}\n"
            "           This likely indicates a version mismatch between\n"
            "           run_validation.py and validation_engine.py.\n",
            file=sys.stderr,
        )
        sys.exit(3)

    # ── Write output JSON ─────────────────────────────────────────────────────
    write_ok = True
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"\n  [ERROR]  Could not write output '{output_path}': {exc}\n", file=sys.stderr)
        write_ok = False

    if not args.quiet and write_ok:
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
        # --quiet: single summary line to stdout
        s = output["summary"]
        m = output.get("meta", {})
        print(
            f"country={m.get('country','?')}  "
            f"total={s['total_checks']}  "
            f"valid={s['validated_count']}  "
            f"invalid={s['invalid_count']}  "
            f"grey={s['grey_area_count']}  "
            f"pass_rate={s['pass_rate']}%"
        )

    # ── Exit code ─────────────────────────────────────────────────────────────
    sys.exit(1 if output.get("summary", {}).get("invalid_count", 0) > 0 else 0)


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    main()
