"""Validación del contrato de la planilla (rápida, para CI y otros modelos)."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import schema
from .parse import ParsedWorkbook, parse_month_header


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def validate_workbook(book: ParsedWorkbook, *, strict_vocab: bool = True) -> ValidationResult:
    result = ValidationResult(ok=True)

    missing_meta = [c for c in schema.META_COLUMNS if c not in book.headers]
    if missing_meta:
        result.fail(f"faltan columnas meta: {missing_meta}")

    if book.headers and book.headers[0] != "product_id":
        result.fail(f"primera columna debe ser product_id, es {book.headers[0]!r}")

    if not book.month_headers:
        result.fail("no hay columnas de mes DD/MM/YYYY")
    else:
        months = [parse_month_header(h) for h in book.month_headers]
        if any(m is None for m in months):
            result.fail("hay headers de mes inválidos")
        elif months != sorted(months):  # type: ignore[type-var]
            result.fail("los meses no están en orden cronológico")

    if len(book.forecast_months) == 0:
        result.warn("no se detectó horizonte de forecast (ningún mes con mayoría decimal)")
    if len(book.history_months) == 0:
        result.warn("no se detectó historia")

    seen: set[str] = set()
    for product in book.products:
        if not product.product_id:
            result.fail("hay filas sin product_id")
            continue
        if product.product_id in seen:
            result.fail(f"product_id duplicado: {product.product_id}")
        seen.add(product.product_id)
        if not product.sku:
            result.fail(f"{product.product_id}: SKU vacío")

        demand = product.meta.get("Tipo de demanda", "")
        cluster = product.meta.get("Cluster", "")
        abc = product.meta.get("ABC", "")
        model = product.meta.get("Modelo", "")
        region = product.meta.get("Region", "")

        if strict_vocab:
            if demand not in schema.DEMAND_TYPES:
                result.fail(f"{product.product_id}: Tipo de demanda desconocido {demand!r}")
            if cluster not in schema.CLUSTERS:
                result.fail(f"{product.product_id}: Cluster desconocido {cluster!r}")
            if abc not in schema.ABC_CLASSES:
                result.fail(f"{product.product_id}: ABC desconocido {abc!r}")
            if model not in schema.MODELS:
                result.fail(f"{product.product_id}: Modelo desconocido {model!r}")
            if region and region not in schema.REGIONS:
                result.fail(f"{product.product_id}: Region desconocida {region!r}")

        err = product.numbers.get("Error")
        if err is not None and not (0 <= err <= 100):
            result.warn(f"{product.product_id}: Error fuera de 0-100 ({err})")

        cv = product.numbers.get("Coeficiente")
        promedio = product.numbers.get("Promedio")
        std = product.numbers.get("Desviacion Std")
        if cv is not None and promedio not in (None, 0) and std is not None:
            expected = abs(std / promedio)
            if abs(expected - cv) > 0.05:
                result.warn(
                    f"{product.product_id}: Coeficiente {cv} != std/promedio {expected:.2f}"
                )

    if book.issues:
        for issue in book.issues:
            result.fail(issue)

    return result
