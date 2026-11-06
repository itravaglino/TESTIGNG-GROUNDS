"""Lee la planilla ancha (;) o un candidato en formato largo."""

from __future__ import annotations

import csv
import io
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


def parse_numero(texto: str) -> float | None:
    """Acepta coma decimal, punto decimal y miles con el separador contrario."""
    if texto is None:
        return None
    s = str(texto).strip().replace(" ", "").replace("\u00a0", "")
    if s == "" or s.upper() in {"NA", "N/A", "NULL", "-"}:
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    s = s.replace("$", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def parse_fecha(texto: str) -> date | None:
    s = (texto or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _normalizar_nombre(nombre: str) -> str:
    s = unicodedata.normalize("NFD", nombre.strip())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.lower().replace(" ", "").replace("_", "")


ALIASES_FECHA = {"fecha", "date", "periodo", "mes"}
ALIASES_FORECAST = {
    "forecast",
    "pronostico",
    "fcst",
    "yhat",
    "pred",
    "unidades",
    "valor",
}


@dataclass
class Fila:
    product_id: str
    sku: str
    atributos: dict[str, str]
    serie: dict[date, float]


@dataclass
class Planilla:
    origen: str
    columnas_meta: list[str]
    meses: list[date]
    filas: list[Fila]
    formato: str  # "ancho" | "largo"
    avisos: list[str] = field(default_factory=list)

    def por_sku(self) -> dict[str, Fila]:
        return {fila.sku: fila for fila in self.filas}

    def por_product_id(self) -> dict[str, Fila]:
        return {fila.product_id: fila for fila in self.filas}


def _leer_texto(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _sniff(texto: str) -> str:
    primera = texto.splitlines()[0] if texto else ""
    conteos = {sep: primera.count(sep) for sep in (";", "\t", ",")}
    return max(conteos, key=conteos.get)


def cargar(path: str | Path) -> Planilla:
    path = Path(path)
    texto = _leer_texto(path)
    if not texto.strip():
        raise ValueError("El archivo está vacío.")
    sep = _sniff(texto)
    lector = csv.reader(io.StringIO(texto), delimiter=sep)
    try:
        encabezado = next(lector)
    except StopIteration:
        raise ValueError("El archivo no tiene encabezado.") from None
    encabezado = [c.strip() for c in encabezado]
    if len(encabezado) < 2:
        raise ValueError(
            "No se pudo separar columnas. La planilla estándar usa ';'."
        )
    filas_crudas = [fila for fila in lector if any(c.strip() for c in fila)]
    fechas = [(i, parse_fecha(nombre)) for i, nombre in enumerate(encabezado)]
    indices_fecha = [(i, f) for i, f in fechas if f is not None]
    if len(indices_fecha) >= 3:
        return _cargar_ancho(path, encabezado, filas_crudas, indices_fecha)
    return _cargar_largo(path, encabezado, filas_crudas)


def _cargar_ancho(path, encabezado, filas_crudas, indices_fecha) -> Planilla:
    indices = [i for i, _ in indices_fecha]
    meses = [f for _, f in indices_fecha]
    meta_idx = [i for i in range(len(encabezado)) if i not in set(indices)]
    columnas_meta = [encabezado[i] for i in meta_idx]
    nombres = {nombre: i for i, nombre in enumerate(encabezado)}
    if "SKU" not in nombres and "product_id" not in nombres:
        raise ValueError("Falta la columna SKU o product_id.")
    filas: list[Fila] = []
    avisos: list[str] = []
    for n, cruda in enumerate(filas_crudas, start=2):
        if len(cruda) < len(encabezado):
            cruda = cruda + [""] * (len(encabezado) - len(cruda))
        sku = cruda[nombres["SKU"]].strip() if "SKU" in nombres else ""
        pid = cruda[nombres["product_id"]].strip() if "product_id" in nombres else sku
        if not sku:
            sku = pid
        if not pid:
            pid = sku
        if not sku:
            avisos.append(f"Fila {n}: sin SKU ni product_id.")
            continue
        serie: dict[date, float] = {}
        for i, mes in indices_fecha:
            valor = parse_numero(cruda[i] if i < len(cruda) else "")
            if valor is None:
                avisos.append(f"Fila {n} ({sku}): mes {mes.isoformat()} vacío.")
                continue
            serie[mes] = valor
        atributos = {
            encabezado[i]: cruda[i].strip() if i < len(cruda) else ""
            for i in meta_idx
        }
        filas.append(Fila(pid, sku, atributos, serie))
    return Planilla(str(path), columnas_meta, meses, filas, "ancho", avisos)


def _cargar_largo(path, encabezado, filas_crudas) -> Planilla:
    norm = {_normalizar_nombre(c): i for i, c in enumerate(encabezado)}

    def buscar(aliases: set[str]) -> int | None:
        for alias in aliases:
            if alias in norm:
                return norm[alias]
        return None

    i_sku = buscar({"sku"})
    i_pid = buscar({"productid"})
    i_fecha = buscar(ALIASES_FECHA)
    i_valor = buscar(ALIASES_FORECAST)
    if i_fecha is None or i_valor is None or (i_sku is None and i_pid is None):
        raise ValueError(
            "Formato largo ilegible: hacen falta columnas de SKU (o product_id), "
            "fecha y pronóstico."
        )
    grupos: dict[str, Fila] = {}
    meses: set[date] = set()
    avisos: list[str] = []
    for n, cruda in enumerate(filas_crudas, start=2):
        def celda(i: int | None) -> str:
            if i is None or i >= len(cruda):
                return ""
            return cruda[i].strip()

        sku = celda(i_sku) or celda(i_pid)
        pid = celda(i_pid) or sku
        mes = parse_fecha(celda(i_fecha))
        if mes is None:
            avisos.append(f"Fila {n}: fecha inválida '{celda(i_fecha)}'.")
            continue
        valor = parse_numero(celda(i_valor))
        if valor is None:
            avisos.append(f"Fila {n} ({sku}): pronóstico vacío.")
            continue
        fila = grupos.get(sku)
        if fila is None:
            fila = Fila(pid, sku, {}, {})
            grupos[sku] = fila
        if mes in fila.serie:
            avisos.append(f"SKU {sku}: fecha duplicada {mes.isoformat()}.")
        fila.serie[mes] = valor
        meses.add(mes)
    return Planilla(
        str(path),
        [],
        sorted(meses),
        list(grupos.values()),
        "largo",
        avisos,
    )
