"""Local-first FastAPI app. Uploaded data stays in memory, not on disk."""
from __future__ import annotations

import io
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .core import CleanOptions, DataDoctorError, analyze, clean, export_table, load_table, MAX_UPLOAD_BYTES
from .storage import history, record

app = FastAPI(title="DataDoctor", version="1.0.0", description="Local-first CSV/Excel quality checker")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


async def read_upload(file: UploadFile):
    try:
        # Read one extra byte to reject oversized uploads before parsing.
        contents = await file.read(MAX_UPLOAD_BYTES + 1)
        return load_table(contents, file.filename or "")
    except DataDoctorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()


@app.post("/api/analyze")
async def analyze_upload(file: UploadFile = File(...)):
    df = await read_upload(file)
    report = analyze(df)
    record("analyze", Path(file.filename or "").suffix.lower(), report["summary"])
    return report


@app.post("/api/clean")
async def clean_upload(
    file: UploadFile = File(...),
    drop_duplicates: bool = Form(True),
    missing_strategy: str = Form("none"),
    cap_outliers: bool = Form(False),
):
    df = await read_upload(file)
    try:
        options = CleanOptions(drop_duplicates, missing_strategy, cap_outliers)
        result, actions = clean(df, options)
        extension = Path(file.filename or "").suffix.lower()
        blob, mime = export_table(result, extension)
    except DataDoctorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    report = analyze(result)
    record("clean", extension, report["summary"])
    return StreamingResponse(
        io.BytesIO(blob), media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="datadoctor-cleaned{extension}"',
            "X-DataDoctor-Removed-Duplicates": str(actions["duplicates_removed"]),
            "X-DataDoctor-Filled-Cells": str(actions["missing_cells_filled"]),
            "X-DataDoctor-Capped-Outliers": str(actions["outliers_capped"]),
            "X-DataDoctor-Dropped-Rows": str(actions["missing_rows_removed"]),
        },
    )


@app.get("/api/history")
def get_history():
    return {"runs": history()}
