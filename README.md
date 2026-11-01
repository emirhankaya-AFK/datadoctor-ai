# 🩺 DataDoctor — Data Quality Studio

[![CI](https://github.com/emirhankaya-AFK/datadoctor-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/emirhankaya-AFK/datadoctor-ai/actions/workflows/ci.yml)

**Open-source, local-first CSV and Excel data auditor.** Upload a spreadsheet, inspect missing cells, duplicate rows and statistical outliers, then export a clean copy. No paid AI API, hosted database or token required.

> **Privacy:** Dataset contents are not deliberately saved by DataDoctor. FastAPI/Starlette may temporarily spool multipart uploads to operating-system temporary files during processing; these uploads are closed when the request finishes. The local SQLite audit log stores only counts and file type (no filenames or input rows). This MVP is intended for local/trusted use: it does **not** include user authentication or rate limiting. Don't expose it on the public internet without adding those controls.

## Features

- Responsive browser dashboard (`/`) and interactive OpenAPI docs (`/docs`)
- CSV (`UTF-8`, including common `;` delimiters) and `.xlsx` input
- Missing-cell counts per column, row deduplication and IQR outlier detection
- Configurable missing strategy: leave unchanged (default), drop incomplete rows, or fill numeric median / text mode (opt-in)
- Outliers are reported but **never deleted or modified by default**. Optional IQR capping replaces values outside 1.5×IQR bounds with the nearest bound (opt-in)
- CSV or XLSX export, with spreadsheet formula injection mitigations
- **Preserves CSV identifiers with leading zeros**, such as `00123`
- Lightweight SQLite history with *metadata only*: `GET /api/history`
- CLI support and automated `pytest` test suite + GitHub Actions
- Upload limits: 10 MiB, 100k rows, 100 columns, 80 MiB uncompressed Excel content

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e '.[dev]'
uvicorn datadoctor.api:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. API docs: **http://127.0.0.1:8000/docs**.

### CLI

```bash
datadoctor analyze examples/sample.csv --report quality.json
datadoctor clean examples/sample.csv -o cleaned.csv --missing fill --cap-outliers
datadoctor clean examples/sample.csv -o cleaned.xlsx --missing drop_rows
python -m pytest
```

### API

```bash
curl -F "file=@examples/sample.csv" http://127.0.0.1:8000/api/analyze
curl -F "file=@examples/sample.csv" -F "drop_duplicates=true" -F "missing_strategy=fill" -F "cap_outliers=false" http://127.0.0.1:8000/api/clean -o cleaned.csv
curl http://127.0.0.1:8000/api/history
curl http://127.0.0.1:8000/health
```

### Sample output

**Data privacy warning:** The JSON report includes a preview of up to eight original rows and may therefore contain personal or confidential data; never commit generated reports to GitHub. SQLite run history does not include these previews. Report JSON includes `summary`, `columns`, `preview`, and `notes`. The `quality_score` is a **heuristic indicator**, *not* a guarantee of data correctness or an ML model. Outliers are defined by the 1.5×IQR rule and require >=4 observations with nonzero IQR. Columns that look like IDs are intentionally excluded from numeric modification.

## Safety and limitations

- Only first worksheet in `.xlsx` is processed. `.xls` and non-UTF8 CSV are not supported.
- Blank/whitespace-only cells count as missing. CSV source data is parsed as text; Excel preserves inferred types. Some spreadsheet formatting, formulas and other worksheets are not preserved by export.
- CSV/XLSX exports neutralize text fields that could execute as spreadsheet formulas (`=`, `+`, `-`, `@`, including leading whitespace) by prefixing an apostrophe; this intentionally changes potentially dangerous strings. Safe numeric negatives remain numeric. Check exports when preserving exact textual values is essential.
- CLI refuses to overwrite the input file (including existing hardlinks), for both cleaning output and JSON analysis reports. The original upload is never modified by the web API.
- `drop_duplicates` is enabled by default on export; disable it when every source record must remain. `fill` uses column-wise median for clearly numeric columns and mode for text columns; if every value is missing the column remains missing. Outliers are not deleted under any option.
- Original Excel formulas/macros, formatting and other worksheets are **not** preserved in exported workbooks. Review results before using them downstream.
- Limits reduce resource risk but are not a complete sandbox for untrusted files. Use local/trusted environments and keep dependencies updated.
- Large XLSX files may still use considerable RAM; 80 MiB is an uncompressed ZIP-header check, not a hard memory cap.
- Do not commit sensitive datasets, database contents, credentials, or generated exports. The default SQLite location is `data/datadoctor.sqlite3`; override with `DATADOCTOR_DB_PATH`.

## Technology

Python · FastAPI · pandas · openpyxl · SQLite · HTML/CSS/JavaScript · GitHub Actions.

## License

MIT — see [LICENSE](LICENSE).

### Windows one-click launcher

After installing Python 3.11+, you can double-click `start_windows.bat` to prepare a virtual environment and start the app. Open `http://127.0.0.1:8000` in your browser. The first run needs internet access to install packages; subsequent runs reuse the virtual environment.
