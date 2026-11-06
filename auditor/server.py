"""Servidor local del auditor."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from auditor.parse import ParseError
from auditor.audit import auditar_bytes, auditar_texto

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
EJEMPLO = ROOT / "fixtures" / "forecasts_largo.csv"

app = FastAPI(title="Auditor de Forecasts", version="1.0.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.exception_handler(ParseError)
async def parse_error(_request, exc: ParseError):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.get("/")
def inicio(ejemplo: int = 0):
    html = (WEB / "index.html").read_text(encoding="utf-8")
    if ejemplo:
        datos = json.dumps(auditar_texto(EJEMPLO.read_text(encoding="utf-8")), ensure_ascii=False)
        html = html.replace("<body>", f"<body>\n<script>window.__PRELOAD = {datos};</script>", 1)
        return HTMLResponse(html)
    return HTMLResponse(html)


@app.get("/api/salud")
def salud():
    return {"ok": True}


@app.get("/api/ejemplo")
def ejemplo():
    return auditar_texto(EJEMPLO.read_text(encoding="utf-8"))


@app.post("/api/auditar")
async def auditar(archivo: UploadFile = File(...)):
    payload = await archivo.read()
    resultado = auditar_bytes(payload)
    resultado["lectura"]["archivo"] = archivo.filename
    return resultado
