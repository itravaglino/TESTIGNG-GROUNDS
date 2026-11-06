"""Reglas de formato y de calidad sobre una planilla de forecast."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from planilla.schema import (
    ABC_A_MIN,
    ABC_B_MIN,
    ABCS,
    CATEGORIAS_CANONICAS,
    CLIENTES,
    CLUSTERS,
    META_COLUMNS,
    MODELOS,
    NUMERIC_META,
    PROMEDIO_TOLERANCE,
    REGIONES,
    SI_NO,
    STDEV_TOLERANCE,
    TIPOS_DEMANDA,
    TRAILING_MONTHS,
)
from planilla.sheet import (
    EXPECTED_MONTHS,
    FORECAST_COUNT,
    HISTORY_COUNT,
    Sheet,
    forecast_slice,
    history_slice,
    is_integer_token,
    parse_number,
)


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    count: int
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "count": self.count,
            "examples": self.examples,
        }


@dataclass
class Report:
    path: str
    encoding: str
    rows: int
    errors: list[Finding]
    warnings: list[Finding]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "encoding": self.encoding,
            "rows": self.rows,
            "ok": self.ok,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
        }


def _finding(
    code: str,
    severity: str,
    message: str,
    examples: list[str],
) -> Finding | None:
    if not examples:
        return None
    return Finding(
        code=code,
        severity=severity,
        message=message,
        count=len(examples),
        examples=examples[:8],
    )


def expected_abc(promedio: float) -> str:
    if promedio >= ABC_A_MIN:
        return "A"
    if promedio >= ABC_B_MIN:
        return "B"
    return "C"


def population_stdev(values: list[float]) -> float:
    """Desvío con divisor n, que es el que trae la columna Desviacion Std."""
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    return math.sqrt(variance)


def validate(sheet: Sheet) -> Report:
    errors: list[Finding] = []
    warnings: list[Finding] = []

    def add(bucket: list[Finding], finding: Finding | None) -> None:
        if finding is not None:
            bucket.append(finding)

    width = len(META_COLUMNS) + len(EXPECTED_MONTHS)
    header_errors: list[str] = []
    if sheet.header[: len(META_COLUMNS)] != META_COLUMNS:
        header_errors.append(
            "las primeras "
            f"{len(META_COLUMNS)} columnas no coinciden con el contrato"
        )
    if len(sheet.header) != width:
        header_errors.append(
            f"hay {len(sheet.header)} columnas y el contrato pide {width}"
        )
    else:
        for label, month in zip(sheet.month_labels, EXPECTED_MONTHS):
            expected = month.strftime("%d/%m/%Y")
            if label != expected:
                header_errors.append(
                    f"columna de mes {label!r} donde iba {expected}"
                )
                break
    add(
        errors,
        _finding("schema", "error", "El encabezado no cumple el contrato.", header_errors),
    )

    short_rows: list[str] = []
    duplicate_ids: list[str] = []
    duplicate_skus: list[str] = []
    blank_keys: list[str] = []
    bad_region: list[str] = []
    bad_cliente: list[str] = []
    bad_tipo: list[str] = []
    bad_cluster: list[str] = []
    bad_abc: list[str] = []
    bad_modelo: list[str] = []
    bad_flag: list[str] = []
    bad_categoria: list[str] = []
    bad_number: list[str] = []
    history_not_int: list[str] = []
    negative_forecast: list[str] = []
    stdev_off: list[str] = []
    abc_off: list[str] = []
    zero_forecast: list[str] = []
    zero_with_demand: list[str] = []
    promedio_off: list[str] = []
    mojibake: list[str] = []
    zero_history: list[str] = []
    negative_history: list[str] = []
    empty_familia: list[str] = []

    seen_ids: set[str] = set()
    seen_skus: set[str] = set()
    id_at = META_COLUMNS.index("product_id")
    sku_at = META_COLUMNS.index("SKU")
    indexes = {name: META_COLUMNS.index(name) for name in META_COLUMNS}

    structure_broken = bool(header_errors)

    for row_number, row in enumerate(sheet.rows, start=2):
        label = f"fila {row_number}"
        if len(row) != width:
            short_rows.append(f"{label} tiene {len(row)} campos")
            continue
        product_id = row[id_at].strip()
        sku = row[sku_at].strip()
        label = product_id or f"fila {row_number}"
        if product_id == "" or sku == "":
            blank_keys.append(f"fila {row_number}")
        if product_id in seen_ids:
            duplicate_ids.append(product_id)
        seen_ids.add(product_id)
        if sku in seen_skus:
            duplicate_skus.append(sku)
        seen_skus.add(sku)

        if row[indexes["Region"]] not in REGIONES:
            bad_region.append(f"{label} Region={row[indexes['Region']]!r}")
        if row[indexes["Cliente"]] not in CLIENTES:
            bad_cliente.append(f"{label} Cliente={row[indexes['Cliente']]!r}")
        if row[indexes["Tipo de demanda"]] not in TIPOS_DEMANDA:
            bad_tipo.append(f"{label} tipo={row[indexes['Tipo de demanda']]!r}")
        if row[indexes["Cluster"]] not in CLUSTERS:
            bad_cluster.append(f"{label} cluster={row[indexes['Cluster']]!r}")
        if row[indexes["ABC"]] not in ABCS:
            bad_abc.append(f"{label} ABC={row[indexes['ABC']]!r}")
        if row[indexes["Modelo"]] not in MODELOS:
            bad_modelo.append(f"{label} modelo={row[indexes['Modelo']]!r}")
        if row[indexes["Reemplazado?"]] not in SI_NO or row[indexes["Descontinuado?"]] not in SI_NO:
            bad_flag.append(label)
        if row[indexes["Categoria"]] not in CATEGORIAS_CANONICAS:
            bad_categoria.append(f"{label} Categoria={row[indexes['Categoria']]!r}")
        if row[indexes["Familia"]].strip() == "":
            empty_familia.append(label)

        text = row[indexes["Subcategoria"]] + row[indexes["Descripcion"]]
        if any(ord(char) > 127 for char in text) or "A¡" in text or "Aƒ" in text:
            mojibake.append(f"{label} subcategoria={row[indexes['Subcategoria']]!r}")

        numbers: dict[str, float] = {}
        numeric_ok = True
        for name in NUMERIC_META:
            try:
                numbers[name] = parse_number(row[indexes[name]])
            except ValueError:
                bad_number.append(f"{label} {name}={row[indexes[name]]!r}")
                numeric_ok = False

        history_values: list[float] = []
        history_ok = True
        for cell in history_slice(row):
            if not is_integer_token(cell):
                history_not_int.append(f"{label} historia={cell!r}")
                history_ok = False
                break
            history_values.append(float(cell))
        if any(value < 0 for value in history_values):
            negative_history.append(label)

        forecast_values: list[float] = []
        forecast_ok = True
        for cell in forecast_slice(row):
            try:
                forecast_values.append(parse_number(cell))
            except ValueError:
                bad_number.append(f"{label} pronostico={cell!r}")
                forecast_ok = False
                break
        if forecast_ok and any(value < 0 for value in forecast_values):
            negative_forecast.append(label)

        if not (numeric_ok and history_ok and forecast_ok and len(history_values) == HISTORY_COUNT):
            continue
        if len(forecast_values) != FORECAST_COUNT:
            continue

        trailing = history_values[-TRAILING_MONTHS:]
        mean = sum(trailing) / TRAILING_MONTHS
        stdev = population_stdev(trailing)
        if abs(numbers["Desviacion Std"] - stdev) > STDEV_TOLERANCE:
            stdev_off.append(
                f"{label} std={numbers['Desviacion Std']} calculada={stdev:.2f}"
            )
        if abs(numbers["Promedio"] - mean) > PROMEDIO_TOLERANCE:
            promedio_off.append(
                f"{label} promedio={numbers['Promedio']} media12={mean:.2f}"
            )
        if row[indexes["ABC"]] != expected_abc(numbers["Promedio"]):
            abc_off.append(
                f"{label} ABC={row[indexes['ABC']]} promedio={numbers['Promedio']}"
            )
        if all(value == 0 for value in history_values):
            zero_history.append(label)
        if all(value == 0 for value in forecast_values):
            zero_forecast.append(label)
            if sum(trailing) > 0:
                zero_with_demand.append(
                    f"{label} SKU={sku} suma12={sum(trailing):.0f}"
                )

    if not structure_broken:
        add(errors, _finding("row_width", "error", "Hay filas con otra cantidad de campos.", short_rows))
    add(errors, _finding("product_id", "error", "product_id duplicado.", duplicate_ids))
    add(errors, _finding("sku", "error", "SKU duplicado.", duplicate_skus))
    add(errors, _finding("claves", "error", "Falta product_id o SKU.", blank_keys))
    add(errors, _finding("region", "error", "Region fuera del catálogo.", bad_region))
    add(errors, _finding("cliente", "error", "Cliente fuera del catálogo.", bad_cliente))
    add(errors, _finding("tipo_demanda", "error", "Tipo de demanda fuera del catálogo.", bad_tipo))
    add(errors, _finding("cluster", "error", "Cluster fuera del catálogo.", bad_cluster))
    add(errors, _finding("abc_valor", "error", "ABC fuera de A, B o C.", bad_abc))
    add(errors, _finding("modelo", "error", "Modelo fuera del catálogo.", bad_modelo))
    add(errors, _finding("flags", "error", "Reemplazado? o Descontinuado? no es Sí/No.", bad_flag))
    add(errors, _finding("numero", "error", "Hay métricas o meses que no son numéricos.", bad_number))
    add(
        errors,
        _finding(
            "historia_entera",
            "error",
            "La historia (ene-2017 a oct-2026) tiene que ser unidades enteras.",
            history_not_int,
        ),
    )
    add(
        errors,
        _finding(
            "pronostico_negativo",
            "error",
            "El horizonte nov-2026 a dic-2027 tiene cantidades negativas.",
            negative_forecast,
        ),
    )
    add(
        errors,
        _finding(
            "desviacion",
            "error",
            "Desviacion Std no es el desvío poblacional (divisor n) de los últimos 12 meses de historia.",
            stdev_off,
        ),
    )
    add(
        warnings,
        _finding(
            "abc_corte",
            "warning",
            "ABC no respeta los cortes de este escenario (A ≥ 466.08, B ≥ 106.67, resto C).",
            abc_off,
        ),
    )
    add(
        warnings,
        _finding(
            "pronostico_cero",
            "warning",
            "Los 14 meses de pronóstico están en cero.",
            zero_forecast,
        ),
    )
    add(
        warnings,
        _finding(
            "pronostico_cero_con_demanda",
            "warning",
            "Pronóstico en cero para todo el horizonte, con ventas en los últimos 12 meses.",
            zero_with_demand,
        ),
    )
    add(
        warnings,
        _finding(
            "promedio",
            "warning",
            "Promedio no cierra con la media de los últimos 12 meses de historia.",
            promedio_off,
        ),
    )
    add(
        warnings,
        _finding(
            "texto",
            "warning",
            "Texto con bytes que no son UTF-8 limpio (tildes rotas en el export).",
            mojibake,
        ),
    )
    add(
        warnings,
        _finding(
            "categoria",
            "warning",
            "Categoria fuera de la lista canónica (ojo con 'PICK UP' contra 'Pick up').",
            bad_categoria,
        ),
    )
    add(
        warnings,
        _finding(
            "historia_cero",
            "warning",
            "Historia completa en cero.",
            zero_history,
        ),
    )
    add(
        warnings,
        _finding(
            "historia_negativa",
            "warning",
            "La historia tiene unidades negativas.",
            negative_history,
        ),
    )
    add(
        warnings,
        _finding(
            "familia_vacia",
            "warning",
            "Familia viene vacía.",
            empty_familia,
        ),
    )

    return Report(
        path=str(sheet.path),
        encoding=sheet.encoding,
        rows=len(sheet.rows),
        errors=errors,
        warnings=warnings,
    )
