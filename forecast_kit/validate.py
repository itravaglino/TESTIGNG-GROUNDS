"""Semantic checks on a parsed standard planilla."""

from __future__ import annotations

from forecast_kit.parse import ForecastWorkbook, Issue, parse_forecast_csv
from forecast_kit.schema import (
    FORECAST_END,
    FORECAST_START,
    HISTORY_END,
    HISTORY_START,
    KNOWN_ABC,
    KNOWN_CATEGORIES,
    KNOWN_CLIENTS,
    KNOWN_CLUSTERS,
    KNOWN_DEMAND_TYPES,
    KNOWN_MODELS,
    KNOWN_REGIONS,
    N_FORECAST_MONTHS,
    N_HISTORY_MONTHS,
    REQUIRED_NONEMPTY,
    YES_NO,
)


def validate_workbook(book: ForecastWorkbook) -> list[Issue]:
    issues = list(book.issues)

    if book.months:
        if book.months[0] != HISTORY_START:
            issues.append(
                Issue(
                    "error",
                    "history_start",
                    f"first month must be {HISTORY_START.isoformat()}, got {book.months[0].isoformat()}",
                )
            )
        if book.months[-1] != FORECAST_END:
            issues.append(
                Issue(
                    "error",
                    "forecast_end",
                    f"last month must be {FORECAST_END.isoformat()}, got {book.months[-1].isoformat()}",
                )
            )
        n_hist = sum(1 for m in book.months if m <= HISTORY_END)
        n_fcst = sum(1 for m in book.months if m >= FORECAST_START)
        if n_hist != N_HISTORY_MONTHS:
            issues.append(
                Issue(
                    "error",
                    "history_len",
                    f"expected {N_HISTORY_MONTHS} history months through {HISTORY_END.isoformat()}, got {n_hist}",
                )
            )
        if n_fcst != N_FORECAST_MONTHS:
            issues.append(
                Issue(
                    "error",
                    "forecast_len",
                    f"expected {N_FORECAST_MONTHS} forecast months from {FORECAST_START.isoformat()}, got {n_fcst}",
                )
            )

    for product in book.products:
        meta = product.meta
        row = product.source_row
        pid = product.product_id
        for col in REQUIRED_NONEMPTY:
            if not meta.get(col):
                issues.append(
                    Issue(
                        "error",
                        "required_empty",
                        f"{col} is empty",
                        row=row,
                        product_id=pid,
                        column=col,
                    )
                )
        model = meta.get("Modelo", "")
        if model and model not in KNOWN_MODELS:
            issues.append(
                Issue(
                    "error",
                    "unknown_model",
                    f"Modelo {model!r} is not in the standard set {sorted(KNOWN_MODELS)}",
                    row=row,
                    product_id=pid,
                    column="Modelo",
                )
            )
        demand = meta.get("Tipo de demanda", "")
        if demand and demand not in KNOWN_DEMAND_TYPES:
            issues.append(
                Issue(
                    "warning",
                    "unknown_demand_type",
                    f"Tipo de demanda {demand!r} is not in the observed set",
                    row=row,
                    product_id=pid,
                    column="Tipo de demanda",
                )
            )
        cluster = meta.get("Cluster", "")
        if cluster and cluster not in KNOWN_CLUSTERS:
            issues.append(
                Issue(
                    "warning",
                    "unknown_cluster",
                    f"Cluster {cluster!r} is not in the observed set",
                    row=row,
                    product_id=pid,
                    column="Cluster",
                )
            )
        abc = meta.get("ABC", "")
        if abc and abc not in KNOWN_ABC:
            issues.append(
                Issue(
                    "warning",
                    "unknown_abc",
                    f"ABC {abc!r} is not A/B/C",
                    row=row,
                    product_id=pid,
                    column="ABC",
                )
            )
        region = meta.get("Region", "")
        if region and region not in KNOWN_REGIONS:
            issues.append(
                Issue(
                    "warning",
                    "unknown_region",
                    f"Region {region!r} is not in the observed set",
                    row=row,
                    product_id=pid,
                    column="Region",
                )
            )
        cliente = meta.get("Cliente", "")
        if cliente and cliente not in KNOWN_CLIENTS:
            issues.append(
                Issue(
                    "warning",
                    "unknown_client",
                    f"Cliente {cliente!r} is not MANN-FILTER/WIX",
                    row=row,
                    product_id=pid,
                    column="Cliente",
                )
            )
        categoria = meta.get("Categoria", "")
        if categoria and categoria not in KNOWN_CATEGORIES:
            issues.append(
                Issue(
                    "warning",
                    "unknown_category",
                    f"Categoria {categoria!r} is new; keep it but flag it",
                    row=row,
                    product_id=pid,
                    column="Categoria",
                )
            )
        for flag in ("Reemplazado?", "Descontinuado?"):
            val = meta.get(flag, "")
            if val and val not in YES_NO:
                issues.append(
                    Issue(
                        "warning",
                        "unknown_flag",
                        f"{flag}={val!r} expected Si/No",
                        row=row,
                        product_id=pid,
                        column=flag,
                    )
                )
        for numeric_col in (
            "Error",
            "Promedio",
            "Desviacion Std",
            "Coeficiente",
            "YTD",
            "QTD",
            "MTD",
            "FYTD",
            "YTG",
            "QTG",
            "MTG",
            "FYTG",
            "Precio Unitario",
            "Costo Unitario",
        ):
            raw = meta.get(numeric_col, "")
            if raw == "":
                issues.append(
                    Issue(
                        "warning",
                        "empty_metric",
                        f"{numeric_col} is empty",
                        row=row,
                        product_id=pid,
                        column=numeric_col,
                    )
                )
                continue
            from forecast_kit.parse import parse_es_number

            try:
                parse_es_number(raw)
            except ValueError:
                issues.append(
                    Issue(
                        "error",
                        "bad_metric",
                        f"{numeric_col}={raw!r} is not numeric",
                        row=row,
                        product_id=pid,
                        column=numeric_col,
                    )
                )

        negatives = [m for m, v in product.history.items() if v < 0]
        if negatives:
            issues.append(
                Issue(
                    "warning",
                    "negative_actuals",
                    f"{len(negatives)} negative history months (returns/adjustments)",
                    row=row,
                    product_id=pid,
                )
            )

    book.issues = issues
    return issues


def validate_path(path: str) -> ForecastWorkbook:
    book = parse_forecast_csv(path)
    validate_workbook(book)
    return book
