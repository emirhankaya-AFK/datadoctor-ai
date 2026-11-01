"""Pure data loading, auditing and cleaning routines.

No raw input rows are persisted by this module. CSV columns are imported as
strings by default so things like product codes 00123 are not silently damaged.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UNCOMPRESSED_XLSX = 80 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 100
SUPPORTED = {".csv", ".xlsx"}


class DataDoctorError(ValueError):
    """User-facing, safe-to-display input or option error."""


@dataclass(frozen=True)
class CleanOptions:
    drop_duplicates: bool = True
    missing_strategy: str = "none"  # none, drop_rows, fill
    cap_outliers: bool = False

    def __post_init__(self) -> None:
        if self.missing_strategy not in {"none", "drop_rows", "fill"}:
            raise DataDoctorError("missing_strategy must be none, drop_rows or fill")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    if df.columns.duplicated().any():
        raise DataDoctorError("Duplicate column names are not supported")
    # Empty/whitespace-only strings count as missing; preserve other strings.
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].replace(r"^\s*$", pd.NA, regex=True)
    if len(df) > MAX_ROWS or len(df.columns) > MAX_COLUMNS:
        raise DataDoctorError(f"Maximum table size: {MAX_ROWS:,} rows and {MAX_COLUMNS} columns")
    if not len(df.columns):
        raise DataDoctorError("The file has no columns")
    return df


def _csv_delimiter(text: str) -> str:
    try:
        guess = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        return guess.delimiter
    except csv.Error:
        return ","


def load_table(data: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise DataDoctorError("Only .csv and .xlsx files are supported")
    if not data:
        raise DataDoctorError("The uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DataDoctorError("The file exceeds the 10 MiB upload limit")
    try:
        if suffix == ".csv":
            decoded = data.decode("utf-8-sig")
            df = pd.read_csv(
                io.StringIO(decoded), sep=_csv_delimiter(decoded), dtype="string",
                keep_default_na=False, na_values=[""], on_bad_lines="error",
            )
        else:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                uncompressed = sum(f.file_size for f in archive.infolist())
                if uncompressed > MAX_UNCOMPRESSED_XLSX:
                    raise DataDoctorError("XLSX uncompressed size exceeds the 80 MiB safety limit")
            df = pd.read_excel(io.BytesIO(data), sheet_name=0, engine="openpyxl")
    except (UnicodeDecodeError, UnicodeError) as exc:
        raise DataDoctorError("CSV must be encoded as UTF-8") from exc
    except (zipfile.BadZipFile, EOFError) as exc:
        raise DataDoctorError("This XLSX file is damaged or invalid") from exc
    except (pd.errors.ParserError, ValueError, KeyError, ImportError) as exc:
        if isinstance(exc, DataDoctorError):
            raise
        raise DataDoctorError("Unable to read the file; check its formatting") from exc
    return _normalize(df)


def _numeric(series: pd.Series, name: str) -> pd.Series | None:
    """Only treat fully numeric, non-ID columns as numbers; leave originals intact."""
    if re.search(r"(^|[_\s-])(id|uuid|zip|postal|phone|sku|code)([_\s-]|$)", name, re.I):
        return None
    nonmissing = series.dropna()
    if nonmissing.empty:
        return None
    if is_numeric_dtype(series):
        candidate = pd.to_numeric(series, errors="coerce")
    else:
        strings = nonmissing.astype(str).str.strip()
        # Identifiers with leading zeros must remain text, even with all digits.
        if strings.str.match(r"^[+-]?0\d+$").any():
            return None
        candidate = pd.to_numeric(series, errors="coerce")
    if candidate.notna().sum() != nonmissing.shape[0]:
        return None
    # Reject infinite/non-finite values (otherwise JSON reports can break).
    if not np.isfinite(candidate.dropna().to_numpy(dtype="float64")).all():
        return None
    return candidate.astype("float64")


def _iqr_bounds(numbers: pd.Series) -> tuple[float, float] | None:
    nonmissing = numbers.dropna()
    if len(nonmissing) < 4:
        return None
    q1, q3 = nonmissing.quantile([0.25, 0.75]).tolist()
    iqr = q3 - q1
    if not math.isfinite(iqr) or iqr <= 0:
        return None
    return float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)


def _outliers(numbers: pd.Series) -> tuple[int, tuple[float, float] | None]:
    bounds = _iqr_bounds(numbers)
    if bounds is None:
        return 0, None
    return int(((numbers < bounds[0]) | (numbers > bounds[1])).sum()), bounds


def analyze(df: pd.DataFrame) -> dict:
    rows, cols = df.shape
    duplicate_rows = int(df.duplicated().sum())
    missing = int(df.isna().sum().sum())
    columns = []
    outlier_total = 0
    for name in df.columns:
        values = df[name]
        miss = int(values.isna().sum())
        numeric = _numeric(values, name)
        count, bounds = _outliers(numeric) if numeric is not None else (0, None)
        outlier_total += count
        item = {
            "name": name,
            "type": "numeric" if numeric is not None else "text",
            "missing": miss,
            "missing_pct": round(100 * miss / rows, 2) if rows else 0.0,
            "unique": int(values.nunique(dropna=True)),
            "outliers": count,
        }
        if numeric is not None:
            finite = numeric.dropna()
            item["mean"] = round(float(finite.mean()), 3)
            item["min"] = float(finite.min())
            item["max"] = float(finite.max())
            if bounds:
                item["iqr_bounds"] = [round(bounds[0], 3), round(bounds[1], 3)]
        columns.append(item)
    total_cells = max(rows * cols, 1)
    # Illustrative score, not a formal data-quality certification.
    penalty = missing + duplicate_rows * cols + outlier_total
    score = max(0.0, round(100 * (1 - penalty / total_cells), 1))
    return {
        "summary": {
            "rows": rows, "columns": cols, "duplicate_rows": duplicate_rows,
            "missing_cells": missing, "outlier_cells": outlier_total,
            "quality_score": score,
        },
        "columns": columns,
        "preview": json.loads(df.head(8).to_json(orient="records", date_format="iso")),
        "notes": [
            "Quality score is a simple heuristic; overlapping issues may be counted twice.",
            "Outliers use the 1.5 × IQR rule on eligible numeric columns with at least four values.",
            "Only the first worksheet of an XLSX workbook is read.",
        ],
    }


def _replacement_value(series: pd.Series, numeric: pd.Series | None):
    if numeric is not None:
        mid = numeric.median()
        if math.isfinite(mid):
            return mid if is_numeric_dtype(series) else _string_number(mid)
    mode = series.dropna().mode()
    return mode.iloc[0] if not mode.empty else None


def _string_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.12g}"


def clean(df: pd.DataFrame, options: CleanOptions) -> tuple[pd.DataFrame, dict]:
    cleaned = df.copy(deep=True)
    actions = {"duplicates_removed": 0, "missing_rows_removed": 0, "missing_cells_filled": 0, "outliers_capped": 0}
    if options.drop_duplicates:
        prior = len(cleaned)
        cleaned = cleaned.drop_duplicates(ignore_index=True)
        actions["duplicates_removed"] = prior - len(cleaned)
    if options.missing_strategy == "drop_rows":
        prior = len(cleaned)
        cleaned = cleaned.dropna().reset_index(drop=True)
        actions["missing_rows_removed"] = prior - len(cleaned)
    elif options.missing_strategy == "fill":
        for name in cleaned.columns:
            values = cleaned[name]
            if not values.isna().any():
                continue
            substitute = _replacement_value(values, _numeric(values, name))
            if substitute is not None:
                count = int(values.isna().sum())
                cleaned[name] = values.fillna(substitute)
                actions["missing_cells_filled"] += count
    if options.cap_outliers:
        for name in cleaned.columns:
            numeric = _numeric(cleaned[name], name)
            if numeric is None:
                continue
            bounds = _iqr_bounds(numeric)
            if bounds is None:
                continue
            mask = (numeric < bounds[0]) | (numeric > bounds[1])
            count = int(mask.sum())
            if count:
                replacement = numeric.clip(bounds[0], bounds[1])
                if not is_numeric_dtype(cleaned[name]):
                    cleaned.loc[mask, name] = replacement[mask].map(_string_number)
                else:
                    cleaned.loc[mask, name] = replacement[mask]
                actions["outliers_capped"] += count
    return cleaned, actions


def _safe_spreadsheet_cell(value):
    # Prevent spreadsheet formulas when exporting potentially untrusted text.
    # Safe numeric literals like -15.5 are not spreadsheet formulas.
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(("+", "-")):
        try:
            if math.isfinite(float(stripped)):
                return value
        except ValueError:
            pass
    if stripped.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def export_table(df: pd.DataFrame, extension: str) -> tuple[bytes, str]:
    if extension not in SUPPORTED:
        raise DataDoctorError("Unsupported export type")
    safe = df.copy()
    safe.columns = [_safe_spreadsheet_cell(str(name)) for name in safe.columns]
    for name in safe.select_dtypes(include=["object", "string"]).columns:
        safe[name] = safe[name].map(_safe_spreadsheet_cell)
    out = io.BytesIO()
    if extension == ".csv":
        return safe.to_csv(index=False).encode("utf-8-sig"), "text/csv; charset=utf-8"
    safe.to_excel(out, index=False, engine="openpyxl")
    return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
