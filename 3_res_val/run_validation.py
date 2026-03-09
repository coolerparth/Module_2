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
    from resume_validator import __version__ as _VERSION
    from resume_validator import run as _run
except ImportError as _exc:
    print(
        f"\n[FATAL] Cannot import 'resume_validator': {_exc}\n"
        "Ensure the resume_validator/ package is in the same directory or on PYTHONPATH.\n",
        file=sys.stderr,
    )
    sys.exit(3)

_ANSI: dict[str, str] = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "dim":    "\033[2m",
    "red":    "\033[91m",
    "green":  "\033[92m",
    "yellow": "\033[93m",
    "cyan":   "\033[96m",
}
_COLOR: bool = True


def _c(text: str, *styles: str) -> str:
    if not _COLOR:
        return text
    return "".join(_ANSI.get(s, "") for s in styles) + text + _ANSI["reset"]


def _width() -> int:
    return min(shutil.get_terminal_size((100, 24)).columns, 100)


def _hr(char: str = "─") -> str:
    return char * _width()


def _wrap(text: str, indent: int = 9) -> str:
    pad = " " * indent
    return textwrap.fill(text, width=_width() - indent, initial_indent=pad, subsequent_indent=pad)


def _rate_label(rate: float) -> str:
    if rate >= 90: return _c("EXCELLENT", "bold", "green")
    if rate >= 75: return _c("GOOD",       "bold", "cyan")
    if rate >= 50: return _c("NEEDS WORK", "bold", "yellow")
    return              _c("POOR",       "bold", "red")


def _fmt_data(data: Any, indent: int = 9) -> str:
    pad = " " * indent
    lbl = _c("data:", "dim")
    if data is None:
        return ""
    if isinstance(data, str):
        s = data[:77] + "…" if len(data) > 80 else data
        return f"{pad}{lbl}  {s}"
    if isinstance(data, list):
        items = data[:6]
        tail  = f" …(+{len(data)-6})" if len(data) > 6 else ""
        return f"{pad}{lbl}  [{', '.join(str(x) for x in items)}{tail}]"
    if isinstance(data, dict):
        if "raw" in data:
            return f"{pad}{lbl}  {data['raw']!r}  →  {data.get('start') or '?'} – {data.get('end') or '?'}"
        pairs    = list(data.items())[:2]
        rendered = ",  ".join(f"{k}={v!r}" for k, v in pairs)
        if len(data) > 2: rendered += f"  …(+{len(data)-2})"
        return f"{pad}{lbl}  {{{rendered}}}"
    return f"{pad}{lbl}  {data!r}"


def _banner(path: Path) -> None:
    print()
    print(_c(_hr("═"), "cyan"))
    print(_c("   Smart Resume Audit & Verification System", "bold", "cyan"))
    print(_c(f"   Engine v{_VERSION}  ·  Async · Pydantic · +91 Enforced · Typo Detection", "dim"))
    print(_c(_hr("═"), "cyan"))
    print(f"\n   {_c('File :', 'dim')}  {path.resolve()}")
    print(f"   {_c('Time :', 'dim')}  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n")


def _summary(output: dict) -> None:
    s       = output.get("summary", {})
    total   = s.get("total_checks",    0)
    valid   = s.get("validated_count", 0)
    invalid = s.get("invalid_count",   0)
    grey    = s.get("grey_area_count", 0)
    rate    = s.get("pass_rate",       0.0)
    print(_c(_hr(), "dim"))
    print(_c("  VALIDATION SUMMARY", "bold"))
    print(_c(_hr(), "dim"))
    print()
    print(f"   {_c('Total checks :', 'dim')}  {_c(str(total),   'bold')}")
    print(f"   {_c('Validated  :', 'dim')}  {_c(str(valid),   'bold', 'green')}")
    print(f"   {_c('Invalid    :', 'dim')}  {_c(str(invalid), 'bold', 'red'    if invalid else 'green')}")
    print(f"   {_c('Grey Area  :', 'dim')}  {_c(str(grey),   'bold', 'yellow' if grey    else 'green')}")
    print(f"   {_c('Pass Rate     :', 'dim')}  {_c(f'{rate:.1f}%', 'bold')}  {_rate_label(rate)}")
    print()


def _section(output: dict, key: str, title: str) -> None:
    sections = output.get(key, {})
    if not sections:
        return
    is_inv   = key == "invalid_sections"
    msg_key  = "error" if is_inv else "note"
    msg_lbl  = "Error" if is_inv else "Note "
    count    = len(sections)
    plural   = "s" if count != 1 else ""
    
    if key == "validated_sections":
        color = "green"
    elif key == "invalid_sections":
        color = "red"
    else:
        color = "yellow"

    print(_c(_hr(), color))
    print(_c(f"  {title}  ({count} item{plural})", "bold", color))
    print(_c(_hr(), color))
    print()
    for i, (path, entry) in enumerate(sections.items(), 1):
        print(f"{_c(f'  [{i:02d}]', 'bold', color)}  {_c(path, 'bold')}")
        msg = entry.get(msg_key, "")
        if msg:
            print(_wrap(f"{msg_lbl} : {msg}"))
        line = _fmt_data(entry.get("data"))
        if line:
            print(line)
        print()


def _footer(out_path: Path, output: dict) -> None:
    s       = output.get("summary", {})
    invalid = s.get("invalid_count",   0)
    grey    = s.get("grey_area_count", 0)
    print(_c(_hr("═"), "cyan"))
    if invalid == 0 and grey == 0:
        print(_c("  All checks passed — resume data is clean.", "bold", "green"))
    elif invalid == 0:
        print(_c(f"  No hard failures — {grey} item(s) flagged for manual review.", "bold", "yellow"))
    else:
        print(_c(f"  {invalid} hard failure(s) — must be resolved before scoring.", "bold", "red"))
    print(f"\n   {_c('Output :', 'dim')}  {out_path.resolve()}")
    print(_c(_hr("═"), "cyan"))
    print()


def _load_json(path: Path) -> tuple[dict | None, int]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"\n{'[FATAL]':>9}  Cannot read '{path}': {exc}\n", file=sys.stderr)
        return None, 2

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"\n{'[FATAL]':>9}  Invalid JSON in '{path}': {exc}\n", file=sys.stderr)
        return None, 2

    if not isinstance(data, dict):
        print(
            f"\n{'[FATAL]':>9}  JSON root must be an object — got {type(data).__name__}.\n",
            file=sys.stderr,
        )
        return None, 2

    return data, 0


def _write(output: dict, out_path: Path) -> None:
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"\n{'[ERROR]':>9}  Cannot write '{out_path}': {exc}\n", file=sys.stderr)


def _check_output(output: dict) -> bool:
    required = {"summary", "validated_sections", "invalid_sections", "grey_area"}
    missing  = required - output.keys()
    if missing:
        print(
            f"\n{'[FATAL]':>9}  Engine output missing keys: {missing}\n"
            "        Version mismatch — ensure run_validation.py and resume_validator/ are in sync.\n",
            file=sys.stderr,
        )
        return False
    return True


def process_file(in_path: Path, out_path: Path, args: argparse.Namespace) -> int:
    if not args.quiet:
        _banner(in_path)

    raw_json, err = _load_json(in_path)
    if raw_json is None:
        return err

    if not args.quiet:
        print(f"   {_c('Pipeline :', 'dim')}  running async validation …\n")

    try:
        output = _run(raw_json)
    except TypeError as exc:
        print(f"\n{'[FATAL]':>9}  Engine TypeError: {exc}\n", file=sys.stderr)
        return 3
    except Exception:
        print(f"\n{'[FATAL]':>9}  Unexpected engine error:\n", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 3

    if not _check_output(output):
        return 3

    _write(output, out_path)

    if not args.quiet:
        print(f"   {_c('Output   :', 'dim')}  {out_path.resolve()}\n")
        _summary(output)
        if args.show_valid:
            _section(output, "validated_sections", "VALIDATED SECTIONS")
        _section(output, "invalid_sections", "INVALID SECTIONS")
        _section(output, "grey_area", "GREY AREA")
        _footer(out_path, output)
    else:
        s = output["summary"]
        prefix = f"file={in_path.name}  " if args.input and Path(args.input).is_dir() else ""
        print(
            f"{prefix}total={s['total_checks']}  valid={s['validated_count']}  "
            f"invalid={s['invalid_count']}  grey={s['grey_area_count']}  "
            f"pass_rate={s['pass_rate']}%"
        )

    return 1 if output.get("summary", {}).get("invalid_count", 0) > 0 else 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_validation",
        description=(
            "Smart Resume Audit & Verification System v3.0 — "
            "validates a raw resume JSON (or a directory of JSONs) through the "
            "Intelligent Validation Engine."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            exit codes:
              0   all checks passed
              1   one or more INVALID sections found
              2   bad arguments / file not found / malformed JSON
              3   unexpected internal engine error

            examples:
              %(prog)s resume.json
              %(prog)s resume.json --output audit.json --show-valid
              %(prog)s ./resumes/  --output ./results/
              %(prog)s resume.json --quiet
              %(prog)s resume.json --no-color > report.txt
        """),
    )
    p.add_argument("input", metavar="INPUT",
        help="Resume JSON file or directory of JSON files.")
    p.add_argument("--output", "-o", metavar="OUTPUT", default=None,
        help="Output file (single) or directory (batch). "
             "Default: <stem>_validated.json or <folder>_output/")
    p.add_argument("--show-valid", action="store_true", default=False,
        help="Also print validated (passing) sections to the console.")
    p.add_argument("--no-color", action="store_true", default=False,
        help="Disable ANSI colour codes (CI / piped output).")
    p.add_argument("--quiet", "-q", action="store_true", default=False,
        help="Print one summary line per file (machine-readable).")
    return p


def main() -> None:
    global _COLOR

    args   = _build_parser().parse_args()
    _COLOR = not args.no_color and sys.stdout.isatty()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"\n{'[FATAL]':>9}  Path not found: {in_path.resolve()}\n", file=sys.stderr)
        sys.exit(2)

    if in_path.is_file():
        out_path = (
            Path(args.output) if args.output
            else in_path.parent / f"{in_path.stem}_validated.json"
        )
        sys.exit(process_file(in_path, out_path, args))

    if in_path.is_dir():
        out_dir = (
            Path(args.output) if args.output
            else in_path.parent / f"{in_path.name}_output"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        files = sorted(
            f for f in in_path.glob("*.json")
            if not f.name.endswith("_validated.json")
        )
        if not files:
            print(f"\n{'[WARN]':>9}  No JSON files found in {in_path.resolve()}\n")
            sys.exit(0)

        if not args.quiet:
            print()
            print(_c(_hr("═"), "cyan"))
            print(_c(f"  BATCH MODE  ·  {len(files)} file(s)  ·  {in_path.resolve()}", "bold", "cyan"))
            print(_c(_hr("═"), "cyan"))
            print()

        worst = 0
        for f in files:
            code  = process_file(f, out_dir / f"{f.stem}_validated.json", args)
            worst = max(worst, code)

        if not args.quiet:
            print(_c(_hr("═"), "cyan"))
            print(_c(f"  BATCH COMPLETE  ·  outputs → {out_dir.resolve()}", "bold", "cyan"))
            print(_c(_hr("═"), "cyan"))
            print()

        sys.exit(worst)

    print(
        f"\n{'[FATAL]':>9}  Path is neither a file nor directory: {in_path.resolve()}\n",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
