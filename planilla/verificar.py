"""Comprueba el contrato de la planilla y compara pronósticos candidatos."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from planilla.contrato import (
    ABC,
    CATEGORIAS,
    CLIENTES,
    CLUSTERS,
    COLUMNAS_META,
    HISTORIA_DESDE,
    HISTORIA_HASTA,
    MODELOS,
    N_FILAS,
    N_MESES,
    PRONOSTICO_DESDE,
    PRONOSTICO_HASTA,
    REGIONES,
    TIPOS_DEMANDA,
    TOLERANCIA_PRONOSTICO,
    TOLERANCIA_STD,
)
from planilla.parser import Planilla, cargar


def meses_entre(desde: date, hasta: date) -> list[date]:
    salida: list[date] = []
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        salida.append(date(anio, mes, 1))
        mes += 1
        if mes == 13:
            mes = 1
            anio += 1
    return salida


MESES_HISTORIA = meses_entre(HISTORIA_DESDE, HISTORIA_HASTA)
MESES_PRONOSTICO = meses_entre(PRONOSTICO_DESDE, PRONOSTICO_HASTA)
MESES_TODOS = meses_entre(HISTORIA_DESDE, PRONOSTICO_HASTA)


def _pstdev(valores: list[float]) -> float:
    n = len(valores)
    media = sum(valores) / n
    return math.sqrt(sum((v - media) ** 2 for v in valores) / n)


@dataclass
class Resultado:
    ok: bool
    titulo: str
    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    metricas: dict[str, float | int | str] = field(default_factory=dict)

    def texto(self) -> str:
        estado = "OK" if self.ok else "FALLA"
        lineas = [f"{estado} — {self.titulo}"]
        if self.metricas:
            for clave, valor in self.metricas.items():
                lineas.append(f"  {clave}: {valor}")
        for aviso in self.avisos[:12]:
            lineas.append(f"  aviso: {aviso}")
        if len(self.avisos) > 12:
            lineas.append(f"  aviso: … y {len(self.avisos) - 12} más")
        for error in self.errores[:30]:
            lineas.append(f"  error: {error}")
        if len(self.errores) > 30:
            lineas.append(f"  error: … y {len(self.errores) - 30} más")
        return "\n".join(lineas)


def verificar(path: str, *, completa: bool | None = None) -> Resultado:
    """Valida esquema, enums y la desviación estándar de los últimos 12 meses."""
    try:
        planilla = cargar(path)
    except (OSError, ValueError, UnicodeError) as exc:
        return Resultado(False, f"No se pudo leer {path}", [str(exc)])

    if planilla.formato != "ancho":
        return Resultado(
            False,
            "La planilla estándar es ancha",
            ["El archivo se leyó como formato largo, no como la planilla de meses en columnas."],
        )

    errores: list[str] = []
    avisos = list(planilla.avisos)
    faltan = [c for c in COLUMNAS_META if c not in planilla.columnas_meta]
    if faltan:
        errores.append("Faltan columnas: " + ", ".join(faltan))

    meses = planilla.meses
    if meses != sorted(meses):
        errores.append("Las columnas de fecha no están en orden cronológico.")
    esperados = set(MESES_TODOS)
    presentes = set(meses)
    if esperados - presentes:
        muestra = ", ".join(d.isoformat() for d in sorted(esperados - presentes)[:6])
        errores.append(f"Faltan meses del contrato ({muestra}).")
    if presentes - esperados:
        errores.append("Hay meses fuera de ene-2017 a dic-2027.")
    if len(meses) != len(set(meses)):
        errores.append("Hay columnas de fecha duplicadas.")

    es_completa = len(planilla.filas) == N_FILAS if completa is None else completa
    if completa and len(planilla.filas) != N_FILAS:
        errores.append(f"Se esperaban {N_FILAS} filas y hay {len(planilla.filas)}.")

    vistos_sku: set[str] = set()
    vistos_id: set[str] = set()
    std_mal = 0
    pronostico_negativo = 0
    for fila in planilla.filas:
        if fila.sku in vistos_sku:
            errores.append(f"SKU duplicado: {fila.sku}")
        vistos_sku.add(fila.sku)
        if fila.product_id in vistos_id:
            errores.append(f"product_id duplicado: {fila.product_id}")
        vistos_id.add(fila.product_id)
        attrs = fila.atributos
        for campo, permitidos in (
            ("Modelo", MODELOS),
            ("Tipo de demanda", TIPOS_DEMANDA),
            ("Cluster", CLUSTERS),
            ("ABC", ABC),
        ):
            if campo in attrs:
                _enum(errores, fila.sku, campo, attrs.get(campo, ""), permitidos)
        if "Region" in attrs and attrs["Region"] not in REGIONES:
            errores.append(f"{fila.sku}: Region '{attrs['Region']}' fuera de catálogo.")
        if "Cliente" in attrs and attrs["Cliente"] not in CLIENTES:
            errores.append(f"{fila.sku}: Cliente '{attrs['Cliente']}' fuera de catálogo.")
        if "Categoria" in attrs and attrs["Categoria"] not in CATEGORIAS:
            errores.append(f"{fila.sku}: Categoria '{attrs['Categoria']}' fuera de catálogo.")
        if attrs.get("Familia", "") != "":
            errores.append(f"{fila.sku}: Familia debería venir vacía en este extracto.")
        for mes in MESES_PRONOSTICO:
            valor = fila.serie.get(mes)
            if valor is None:
                continue
            if valor < 0:
                pronostico_negativo += 1
        historia = [fila.serie.get(mes) for mes in MESES_HISTORIA[-12:]]
        if all(v is not None for v in historia):
            numeros = [float(v) for v in historia]
            desvio = _pstdev(numeros)
            declarado = _numero_attr(attrs.get("Desviacion Std", ""))
            if declarado is not None and abs(desvio - declarado) > TOLERANCIA_STD:
                std_mal += 1
                if std_mal <= 5:
                    errores.append(
                        f"{fila.sku}: Desviacion Std {declarado} != pstdev 12 meses {desvio:.2f}."
                    )
    if std_mal > 5:
        errores.append(f"Desviacion Std no cierra en {std_mal} SKU.")
    if pronostico_negativo:
        errores.append(
            f"Hay {pronostico_negativo} celdas de pronóstico (nov-2026 en adelante) negativas."
        )

    metricas: dict[str, float | int | str] = {
        "filas": len(planilla.filas),
        "meses": len(meses),
        "meses_contrato": N_MESES,
        "formato": planilla.formato,
    }
    if es_completa and not errores:
        metricas["cobertura"] = "completa"
    return Resultado(
        ok=not errores,
        titulo=f"Contrato de {path}",
        errores=errores,
        avisos=avisos,
        metricas=metricas,
    )


def _enum(errores: list[str], sku: str, campo: str, valor: str, permitidos: frozenset[str]) -> None:
    if valor not in permitidos:
        errores.append(f"{sku}: {campo} '{valor}' fuera de catálogo.")


def _numero_attr(texto: str) -> float | None:
    from planilla.parser import parse_numero

    try:
        return parse_numero(texto)
    except ValueError:
        return None


@dataclass
class Diferencia:
    sku: str
    mes: date
    estandar: float
    candidato: float

    @property
    def absoluto(self) -> float:
        return abs(self.candidato - self.estandar)


def comparar(
    estandar_path: str,
    candidato_path: str,
    *,
    tolerancia: float = TOLERANCIA_PRONOSTICO,
) -> Resultado:
    """Compara el horizonte nov-2026..dic-2027 del candidato contra la planilla."""
    try:
        estandar = cargar(estandar_path)
        candidato = cargar(candidato_path)
    except (OSError, ValueError, UnicodeError) as exc:
        return Resultado(False, "No se pudo comparar", [str(exc)])

    base = estandar.por_sku()
    # El candidato puede identificar por SKU o, si copió product_id en la columna SKU, por id.
    por_id = estandar.por_product_id()
    errores: list[str] = list(candidato.avisos)
    faltan: list[str] = []
    extra: list[str] = []
    diferencias: list[Diferencia] = []
    puntos = 0
    vistos: set[str] = set()

    for fila in candidato.filas:
        ref = base.get(fila.sku) or por_id.get(fila.sku) or por_id.get(fila.product_id)
        if ref is None:
            extra.append(fila.sku)
            continue
        vistos.add(ref.sku)
        for mes in MESES_PRONOSTICO:
            if mes not in fila.serie:
                continue
            if mes not in ref.serie:
                errores.append(f"{ref.sku}: el estándar no tiene {mes.isoformat()}.")
                continue
            puntos += 1
            got = fila.serie[mes]
            exp = ref.serie[mes]
            if abs(got - exp) > tolerancia:
                diferencias.append(Diferencia(ref.sku, mes, exp, got))

    for sku in base:
        if sku not in vistos:
            faltan.append(sku)

    avisos: list[str] = []
    if extra:
        errores.append(
            f"{len(extra)} SKU fuera de la planilla (ej. {', '.join(extra[:5])})."
        )
    if faltan:
        avisos.append(f"Sin comparar: {len(faltan)} SKU de la planilla no vienen en el candidato.")

    # WAPE sobre todos los puntos comparados, no solo los que exceden tolerancia.
    suma_abs_todos = 0.0
    suma_err_todos = 0.0
    suma_estandar = 0.0
    for fila in candidato.filas:
        ref = base.get(fila.sku) or por_id.get(fila.sku) or por_id.get(fila.product_id)
        if ref is None:
            continue
        for mes in MESES_PRONOSTICO:
            if mes in fila.serie and mes in ref.serie:
                suma_abs_todos += abs(fila.serie[mes] - ref.serie[mes])
                suma_err_todos += fila.serie[mes] - ref.serie[mes]
                suma_estandar += abs(ref.serie[mes])
    wape = suma_abs_todos / suma_estandar if suma_estandar else 0.0
    mae = suma_abs_todos / puntos if puntos else 0.0
    sesgo = suma_err_todos / puntos if puntos else 0.0

    if puntos == 0:
        errores.append(
            "No hay intersección entre el candidato y el horizonte "
            f"{PRONOSTICO_DESDE.isoformat()} .. {PRONOSTICO_HASTA.isoformat()}."
        )
    if diferencias:
        peores = sorted(diferencias, key=lambda d: d.absoluto, reverse=True)[:8]
        for d in peores:
            errores.append(
                f"{d.sku} {d.mes.isoformat()}: estándar {d.estandar:.2f} "
                f"candidato {d.candidato:.2f} (Δ {d.candidato - d.estandar:.2f})."
            )
        if len(diferencias) > 8:
            errores.append(
                f"{len(diferencias)} puntos superan la tolerancia {tolerancia}."
            )

    return Resultado(
        ok=not errores,
        titulo=f"Candidato contra {estandar_path}",
        errores=errores,
        avisos=avisos,
        metricas={
            "sku_candidato": len(candidato.filas),
            "sku_estandar": len(base),
            "sku_comparados": len(vistos),
            "sku_faltantes": len(faltan),
            "puntos": puntos,
            "puntos_distintos": len(diferencias),
            "mae": round(mae, 4),
            "sesgo_me": round(sesgo, 4),
            "wape": round(wape, 6),
            "tolerancia": tolerancia,
        },
    )
