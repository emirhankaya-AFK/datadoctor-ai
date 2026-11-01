"""Usage: datadoctor analyze input.csv; datadoctor clean input.xlsx -o fixed.xlsx."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import CleanOptions, DataDoctorError, analyze, clean, export_table, load_table


def _prevent_source_overwrite(source: Path, destination: Path) -> None:
    """Never replace a user's original input, even via an existing hardlink."""
    if source.resolve() == destination.resolve():
        raise DataDoctorError("Output must be different from the original input file")
    if destination.exists() and source.samefile(destination):
        raise DataDoctorError("Output must be different from the original input file")


def main() -> None:
    parser = argparse.ArgumentParser(prog="datadoctor", description="Local CSV/XLSX data quality checker")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = sub.add_parser("analyze", help="Print JSON quality report")
    audit.add_argument("file", type=Path)
    audit.add_argument("--report", type=Path, help="Save JSON report to this path")
    fix = sub.add_parser("clean", help="Write cleaned CSV/XLSX file")
    fix.add_argument("file", type=Path)
    fix.add_argument("-o", "--output", type=Path, required=True)
    fix.add_argument("--keep-duplicates", action="store_true")
    fix.add_argument("--missing", choices=["none", "drop_rows", "fill"], default="none")
    fix.add_argument("--cap-outliers", action="store_true")
    args = parser.parse_args()
    try:
        df = load_table(args.file.read_bytes(), args.file.name)
        if args.command == "analyze":
            report = json.dumps(analyze(df), indent=2, ensure_ascii=False)
            if args.report:
                _prevent_source_overwrite(args.file, args.report)
                args.report.write_text(report + "\n", encoding="utf-8")
            print(report)
        else:
            if args.output.suffix.lower() not in {".csv", ".xlsx"}:
                raise DataDoctorError("Output must be .csv or .xlsx")
            _prevent_source_overwrite(args.file, args.output)
            cleaned, actions = clean(df, CleanOptions(
                not args.keep_duplicates, args.missing, args.cap_outliers))
            data, _ = export_table(cleaned, args.output.suffix.lower())
            args.output.write_bytes(data)
            print(json.dumps({"output": str(args.output), "actions": actions, "summary": analyze(cleaned)["summary"]}, indent=2))
    except (DataDoctorError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
