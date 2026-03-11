#!/usr/bin/env python3

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

try:
    from src import engine
except ImportError as _exc:
    print(
        f"\n[FATAL] Could not import 'src.engine': {_exc}\n"
        "Make sure src/engine.py is accessible on PYTHONPATH.",
        file=sys.stderr,
    )
    sys.exit(3)

_ANSI = {
    "reset":     "\033[0m",
    "bold":      "\033[1m",
    "dim":       "\033[2m",
    "red":       "\033[91m",
    "green":     "\033[92m",
    "yellow":    "\033[93m",
    "cyan":      "\033[96m",
}

_USE_COLOR: bool = True


def _c(text: str, *styles: str) -> str:
    if not _USE_COLOR:
        return text
    codes = "".join(_ANSI.get(s, "") for s in styles)
    return f"{codes}{text}{_ANSI['reset']}"


def _term_width() -> int:
    return shutil.get_terminal_size((100, 24)).columns


def _hr(char: str = "─", width: int | None = None) -> str:
    return char * (width or min(_term_width(), 100))


def _wrap(text: str, indent: int = 6, width: int | None = None) -> str:
    w = (width or min(_term_width(), 100)) - indent
    prefix = " " * indent
    return textwrap.fill(text, width=w, initial_indent=prefix, subsequent_indent=prefix)


def _rate_label(rate: float) -> str:
    if rate >= 90:
        return _c("EXCELLENT", "bold", "green")
    if rate >= 75:
        return _c("GOOD", "bold", "cyan")
    if rate >= 50:
        return _c("NEEDS WORK", "bold", "yellow")
    return _c("POOR", "bold", "red")


def _print_banner(input_path: Path) -> None:
    w = min(_term_width(), 100)
    print()
    print(_c(_hr("═", w), "cyan"))
    print(_c("   Smart Resume Audit & Verification System", "bold", "cyan"))
    print(_c("   Intelligent Validation Engine  v3.0  ·  Async · Pydantic · +91 Enforced", "dim"))
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
    print(f"   {_c('Validated  :', 'dim')}  {_c(str(valid),   'bold', 'green')}")
    print(f"   {_c('Invalid    :', 'dim')}  {_c(str(invalid), 'bold', 'red'    if invalid else 'green')}")
    print(f"   {_c('Grey Area  :', 'dim')}  {_c(str(grey),   'bold', 'yellow' if grey    else 'green')}")
    print(f"   {_c('Pass Rate     :', 'dim')}  {_c(f'{rate:.1f}%', 'bold')}  {_rate_label(rate)}")
    print()


def _format_data(data: Any, indent: int = 9) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        truncated = data if len(data) <= 80 else data[:77] + "…"
        return f"{' ' * indent}{_c('Data  :', 'dim')}  {truncated}"
    if isinstance(data, list):
        items = data[:6]
        suffix = f"  … (+{len(data)-6} more)" if len(data) > 6 else ""
        return f"{' ' * indent}{_c('Data  :', 'dim')}  [{', '.join(str(x) for x in items)}{suffix}]"
    if isinstance(data, dict):
        if "raw" in data:
            return (
                f"{' ' * indent}{_c('Data  :', 'dim')}  {data['raw']!r}  →  "
                f"{data.get('start') or '?'} – {data.get('end') or '?'}"
            )
        pairs = list(data.items())[:2]
        rendered = ",  ".join(f"{k}={v!r}" for k, v in pairs)
        if len(data) > 2:
            rendered += f"  … (+{len(data)-2} more fields)"
        return f"{' ' * indent}{_c('Data  :', 'dim')}  {{{rendered}}}"
    return f"{' ' * indent}{_c('Data  :', 'dim')}  {data!r}"


def _print_section(output: dict, key: str, color: str, heading: str) -> None:
    sections = output.get(key, {})
    if not sections:
        return
    w = min(_term_width(), 100)
    count = len(sections)
    print(_c(_hr("─", w), color))
    print(_c(f"  {heading}  ({count})", "bold", color))
    print(_c(_hr("─", w), color))
    print()
    msg_key = "error" if key == "invalid_sections" else "note"
    msg_label = "Error" if key == "invalid_sections" else "Note "
    for i, (path, entry) in enumerate(sections.items(), 1):
        print(f"{_c(f'  [{i:02d}]', 'bold', color)}  {_c(path, 'bold')}")
        print(_wrap(f"{msg_label} : {entry.get(msg_key, '')}", indent=9))
        line = _format_data(entry.get("data"))
        if line:
            print(line)
        print()


def _print_footer(output_path: Path, output: dict) -> None:
    w = min(_term_width(), 100)
    s = output.get("summary", {})
    invalid = s.get("invalid_count", 0)
    grey    = s.get("grey_area_count", 0)
    print(_c(_hr("═", w), "cyan"))
    if invalid == 0 and grey == 0:
        print(_c("  All checks passed — resume data is clean.", "bold", "green"))
    elif invalid == 0:
        print(_c(f"  No hard failures. {grey} item(s) need manual review.", "bold", "yellow"))
    else:
        print(_c(f"  {invalid} hard failure(s) found — fix before scoring.", "bold", "red"))
    print(f"\n   {_c('Output :', 'dim')}  {output_path.resolve()}")
    print(_c(_hr("═", w), "cyan"))
    print()


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
              %(prog)s resume.json --quiet
              %(prog)s resume.json --no-color > report.txt
        """),
    )
    parser.add_argument("input", metavar="INPUT_PATH",
        help="Path to a raw resume JSON file or a directory containing JSON files.")
    parser.add_argument("--output", "-o", metavar="OUTPUT_PATH", default=None,
        help="Custom output file/folder path. Default: <file_stem>_validated.json or <folder_name>_output")
    parser.add_argument("--show-valid", action="store_true", default=False,
        help="Also print validated (passing) sections to the console.")
    parser.add_argument("--no-color", action="store_true", default=False,
        help="Disable ANSI color codes (for piped or CI output).")
    parser.add_argument("--quiet", "-q", action="store_true", default=False,
        help="Suppress all output except a single summary line.")
    return parser


def process_file(input_path: Path, output_path: Path, args: argparse.Namespace) -> int:
    if not args.quiet:
        _print_banner(input_path)

    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"\n{'[FATAL]':>9}  Could not read '{input_path}': {exc}\n", file=sys.stderr)
        return 2

    try:
        raw_json = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(
            f"\n{'[FATAL]':>9}  Invalid JSON in '{input_path}':\n{'':>9}  {exc}\n",
            file=sys.stderr,
        )
        return 2

    if not isinstance(raw_json, dict):
        print(
            f"\n{'[FATAL]':>9}  JSON root must be an object (dict), "
            f"got {type(raw_json).__name__}.\n",
            file=sys.stderr,
        )
        return 2

    if not args.quiet:
        print(f"   {_c('Pipeline :', 'dim')}  running async validation …\n")

    try:
        output = engine.run(raw_json)
    except TypeError as exc:
        print(f"\n{'[FATAL]':>9}  Validation engine TypeError: {exc}\n", file=sys.stderr)
        return 3
    except Exception:
        print(f"\n{'[FATAL]':>9}  Unexpected error in validation engine:\n", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 3

    required_keys = {"summary", "validated_sections", "invalid_sections", "grey_area"}
    if not required_keys.issubset(output.keys()):
        missing = required_keys - output.keys()
        print(
            f"\n{'[FATAL]':>9}  Engine output missing keys: {missing}\n"
            "        Version mismatch between run_validation.py and validation_engine.py.\n",
            file=sys.stderr,
        )
        return 3

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"\n{'[ERROR]':>9}  Could not write to '{output_path}': {exc}\n", file=sys.stderr)
    else:
        if not args.quiet:
            print(f"   {_c('Output   :', 'dim')}  {output_path.resolve()}\n")

    if not args.quiet:
        _print_summary(output)
        if args.show_valid:
            _print_section(output, "validated_sections", "green", "VALIDATED SECTIONS")
        _print_section(output, "invalid_sections", "red", "INVALID SECTIONS")
        _print_section(output, "grey_area", "yellow", "GREY AREA")
        _print_footer(output_path, output)
    else:
        s = output["summary"]
        print(
            f"total={s['total_checks']}  valid={s['validated_count']}  "
            f"invalid={s['invalid_count']}  grey={s['grey_area_count']}  "
            f"pass_rate={s['pass_rate']}%"
        )

    return 1 if output.get("summary", {}).get("invalid_count", 0) > 0 else 0


def main() -> None:
    global _USE_COLOR

    args = _build_parser().parse_args()
    _USE_COLOR = not args.no_color and sys.stdout.isatty()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"\n{'[FATAL]':>9}  Input path not found: {input_path.resolve()}\n", file=sys.stderr)
        sys.exit(2)

    if input_path.is_file():
        output_path = (
            Path(args.output)
            if args.output
            else input_path.parent / f"{input_path.stem}_validated.json"
        )
        exit_code = process_file(input_path, output_path, args)
        sys.exit(exit_code)
        
    elif input_path.is_dir():
        output_dir = (
            Path(args.output)
            if args.output
            else input_path.parent / f"{input_path.name}_output"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        
        json_files = sorted(input_path.glob("*.json"))
        if not json_files:
            print(f"\n{'[WARN]':>9}  No JSON files found in directory: {input_path.resolve()}\n")
            sys.exit(0)
            
        print(f"\n{_c('BATCH PROCESSING', 'bold', 'cyan')} : Found {len(json_files)} JSON files in {input_path.name}")
        
        overall_max_exit = 0
        for f in json_files:
            if f.name.endswith("_validated.json"):
                continue  # skip already processed files if in same dir
            
            out_f = output_dir / f"{f.stem}_validated.json"
            if not args.quiet:
                print(f"\n{_c(f'--- Processing {f.name} ---', 'bold')}")
            
            exit_code = process_file(f, out_f, args)
            overall_max_exit = max(overall_max_exit, exit_code)
            
        if not args.quiet:
            print(f"\n{_c('BATCH COMPLETE', 'bold', 'cyan')} : All outputs written to {output_dir.resolve()}\n")
            
        sys.exit(overall_max_exit)
        
    else:
        print(f"\n{'[FATAL]':>9}  Path is neither a file nor a directory: {input_path.resolve()}\n", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()