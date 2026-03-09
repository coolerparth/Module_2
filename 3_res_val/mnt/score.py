import json
from pathlib import Path

out_dir = Path("Test cases_output")
if not out_dir.exists():
    out_dir = Path("/Users/devagarwal/Desktop/modular resume validation/Test cases_output")

files = sorted(out_dir.glob("*_validated.json"))
total_checks = 0
total_valid = 0
total_invalid = 0
total_grey = 0

print(f"{'File':<40} | {'Pass %':<8} | {'Valid':<5} | {'Invalid':<7} | {'Grey':<5}")
print("-" * 75)

for f in files:
    with open(f, "r") as p:
        data = json.load(p)
        s = data.get("summary", {})
        total_checks += s.get("total_checks", 0)
        total_valid += s.get("validated_count", 0)
        total_invalid += s.get("invalid_count", 0)
        total_grey += s.get("grey_area_count", 0)
        pr = s.get("pass_rate", 0)
        print(f"{f.name[:38]:<40} | {pr:>6.1f}% | {s.get('validated_count', 0):<5} | {s.get('invalid_count', 0):<7} | {s.get('grey_area_count', 0):<5}")

print("-" * 75)
overall_rate = (total_valid / total_checks * 100) if total_checks else 0
print(f"{'Overall (Accuracy Metric)':<40} | {overall_rate:>6.1f}% | {total_valid:<5} | {total_invalid:<7} | {total_grey:<5}")
