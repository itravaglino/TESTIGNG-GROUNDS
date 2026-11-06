"""Kalibra: interfaz para auditar un forecast producto por producto."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from forecast_auditor.pipeline import analyze_frame
from forecast_auditor.sample_data import demo_frame
from forecast_auditor.schema import MAX_BYTES, SchemaError, read_table

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Kalibra", version="1.0.0")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/salud")
def salud():
    return {"ok": True, "nombre": "Kalibra"}


@app.get("/api/ejemplo")
def ejemplo():
    return analyze_frame(demo_frame())


@app.post("/api/auditar")
async def auditar(archivo: UploadFile = File(...)):
    chunks = []
    total = 0
    while True:
        chunk = await archivo.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(status_code=413, detail="El archivo supera el límite de 8 MB.")
        chunks.append(chunk)
    content = b"".join(chunks)
    try:
        frame = read_table(archivo.filename or "forecast.csv", content)
        report = analyze_frame(frame)
    except SchemaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="No pude leer ese archivo. Necesito un CSV o XLSX con producto, fecha y pronóstico.",
        ) from exc
    report["archivo"] = archivo.filename
    return report


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
