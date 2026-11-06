"""Servidor local del auditor de pronósticos.

Uso:
    python -m auditor
    python -m auditor serve --port 8765
    python -m auditor analyze serie.csv --out informe.json
    python -m auditor corregir serie.csv --out serie_corregida.csv
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from email import message_from_bytes
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from auditor.fixtures import build_fixtures
from auditor.parser import canonical_template_csv, load_bytes
from auditor.report import analyze_frame, corrected_long_csv

STATIC = Path(__file__).resolve().parent / "static" / "index.html"
MAX_BYTES = 25 * 1024 * 1024
_SAMPLE: dict | None = None


def analyze_upload(filename: str, data: bytes) -> dict:
    loaded = load_bytes(filename, data)
    return analyze_frame(
        loaded["frame"],
        loaded["frequency"],
        loaded.get("source_name") or filename,
        list(loaded.get("warnings") or []),
    )


def correct_upload(filename: str, data: bytes) -> str:
    loaded = load_bytes(filename, data)
    return corrected_long_csv(loaded["frame"], loaded["frequency"])


def sample_report() -> dict:
    global _SAMPLE
    if _SAMPLE is None:
        raw = build_fixtures()["portfolio"]
        report = analyze_upload("portfolio.csv", raw)
        report["source_name"] = "ejemplo: cartera de 8 productos"
        advice = list(report.get("portfolio_advice") or [])
        advice.insert(0, "Esto es una demostración con datos sintéticos, no su archivo.")
        report["portfolio_advice"] = advice
        _SAMPLE = report
    return _SAMPLE


def _json_bytes(payload: dict, status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def _error(message: str, status: int = 400) -> tuple[int, bytes, str]:
    return _json_bytes({"error": message}, status)


def _extract_upload(content_type: str, body: bytes) -> tuple[str, bytes]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in {"text/plain", "text/csv", "application/csv"}:
        if not body.strip():
            raise ValueError("El texto pegado está vacío.")
        return "serie_pegada.csv", body
    if ctype.startswith("multipart/"):
        header = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        )
        msg = message_from_bytes(header + body, policy=default)
        if not msg.is_multipart():
            raise ValueError("No se pudo leer el archivo enviado.")
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name not in {None, "file"}:
                continue
            filename = part.get_filename() or "serie.csv"
            data = part.get_payload(decode=True) or b""
            if data:
                return filename, data
        raise ValueError("Falta el archivo en el campo «file».")
    if body.strip() and not ctype:
        return "serie.csv", body
    raise ValueError("Envíe un CSV o un Excel en el campo «file», o pegue el texto del archivo.")


class Handler(BaseHTTPRequestHandler):
    server_version = "ForecastAuditor/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or "0")
        if length > MAX_BYTES:
            raise ValueError("El archivo supera el límite de 25 MB.")
        return self.rfile.read(length) if length else b""

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in {"/", "/index.html"}:
                page = STATIC.read_bytes()
                self._send(200, page, "text/html; charset=utf-8")
                return
            if path == "/api/template":
                data = canonical_template_csv().encode("utf-8")
                self._send(200, data, "text/csv; charset=utf-8", "plantilla_pronosticos.csv")
                return
            if path == "/api/sample-report":
                status, body, ctype = _json_bytes(sample_report())
                self._send(status, body, ctype)
                return
            if path == "/api/health":
                status, body, ctype = _json_bytes({"ok": True})
                self._send(status, body, ctype)
                return
            self._send(404, b'{"error":"Ruta no encontrada."}', "application/json; charset=utf-8")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            status, body, ctype = _error(str(exc) or "Error interno.", 500)
            self._send(status, body, ctype)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_body()
            filename, data = _extract_upload(self.headers.get("Content-Type", ""), body)
            if path == "/api/analyze":
                report = analyze_upload(filename, data)
                status, payload, ctype = _json_bytes(report)
                self._send(status, payload, ctype)
                return
            if path == "/api/corrected":
                csv_text = correct_upload(filename, data)
                raw = csv_text.encode("utf-8")
                if not raw.strip():
                    status, payload, ctype = _error("La serie corregida quedó vacía.")
                    self._send(status, payload, ctype)
                    return
                self._send(200, raw, "text/csv; charset=utf-8", "serie_corregida.csv")
                return
            self._send(404, b'{"error":"Ruta no encontrada."}', "application/json; charset=utf-8")
        except ValueError as exc:
            status, payload, ctype = _error(str(exc), 400)
            self._send(status, payload, ctype)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            message = str(exc).strip() or "No se pudo analizar el archivo."
            status, payload, ctype = _error(message, 400 if isinstance(exc, (KeyError, UnicodeError)) else 500)
            self._send(status, payload, ctype)


def serve(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Auditor de pronósticos en http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.", flush=True)
    finally:
        httpd.server_close()


def _cmd_analyze(path: Path, out: Path | None) -> None:
    report = analyze_upload(path.name, path.read_bytes())
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if out:
        out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")
    summary = report.get("summary") or {}
    print(
        f"{path.name}: {summary.get('products')} productos · "
        f"aprobar {summary.get('aprobar')} · corregir {summary.get('corregir')} · "
        f"descartar {summary.get('descartar')} · puntaje medio {summary.get('avg_score')}",
        file=sys.stderr,
    )


def _cmd_correct(path: Path, out: Path) -> None:
    text = correct_upload(path.name, path.read_bytes())
    out.write_text(text, encoding="utf-8")
    print(f"Serie corregida escrita en {out}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Auditor de pronósticos por producto.")
    sub = parser.add_subparsers(dest="cmd")

    serve_p = sub.add_parser("serve", help="Abre la aplicación web local.")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8765)

    analyze_p = sub.add_parser("analyze", help="Analiza un CSV o Excel y escribe el informe JSON.")
    analyze_p.add_argument("file", type=Path)
    analyze_p.add_argument("--out", type=Path)

    correct_p = sub.add_parser("corregir", help="Escribe el CSV con el pronóstico corregido.")
    correct_p.add_argument("file", type=Path)
    correct_p.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    cmd = args.cmd or "serve"
    if cmd == "serve":
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8765)
        serve(host, port)
    elif cmd == "analyze":
        _cmd_analyze(args.file, args.out)
    elif cmd == "corregir":
        _cmd_correct(args.file, args.out)
    else:
        parser.error(f"Comando desconocido: {cmd}")


if __name__ == "__main__":
    main()
