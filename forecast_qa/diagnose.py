from __future__ import annotations

from dataclasses import dataclass

from forecast_qa.split import SplitSeries

INTERMITTENT_MODELS = ("croston", "tsb", "sba")
TREND_MODELS = ("holt", "holt-winters", "damped_holt", "auto_sarima")
ERRATIC_MODELS = ("croston", "tsb", "robust_ses")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # info | warn | error
    message: str


@dataclass(frozen=True)
class ProductAudit:
    product_id: str
    sku: str
    verdict: str
    findings: tuple[Finding, ...]
    recommended_models: tuple[str, ...]
    vendor_model: str | None
    vendor_error: float | None
    demand_type: str | None


def _finite(xs: tuple[float | None, ...]) -> list[float]:
    return [x for x in xs if x is not None]


def recommend_models(demand_type: str | None) -> tuple[str, ...]:
    t = (demand_type or "").strip().lower()
    if "intermit" in t:
        return ("croston", "tsb", "sba")
    if "errat" in t:
        return ("croston", "tsb", "ses_robusto")
    if "tendenc" in t:
        return ("holt_winters", "auto_sarima", "damped_holt")
    if "variable" in t:
        return ("ets", "auto_sarima", "prophet")
    return ("ses", "holt_winters", "auto_sarima")


def audit_product(split: SplitSeries) -> ProductAudit:
    p = split.product
    hist = _finite(split.history)
    fcst = _finite(split.forecast)
    findings: list[Finding] = []
    verdict = "MANTENER"

    if not hist or all(v == 0 for v in hist):
        findings.append(
            Finding("SERIE_NULA", "error", "Histórico vacío o todo cero: no hay demanda para modelar.")
        )
        verdict = "DESCARTAR"
    if any(v < 0 for v in hist):
        findings.append(
            Finding("DEMANDA_NEGATIVA", "warn", "Hay unidades negativas en el histórico; recortar a 0.")
        )
        if verdict == "MANTENER":
            verdict = "CORREGIR"
    if any(v < 0 for v in fcst):
        findings.append(
            Finding("FORECAST_NEGATIVO", "warn", "El pronóstico futuro tiene valores negativos.")
        )
        if verdict != "DESCARTAR":
            verdict = "CORREGIR"

    vendor_error = p.meta.get("Error")
    if isinstance(vendor_error, (int, float)) and vendor_error >= 99.5:
        findings.append(
            Finding(
                "ERROR_VENDOR_100",
                "warn",
                "La planilla trae Error=100: el modelo actual no explica la serie.",
            )
        )
        if verdict == "MANTENER":
            verdict = "REVISAR"

    if hist:
        recent = hist[-12:] if len(hist) >= 12 else hist
        mean_h = sum(recent) / len(recent)
        mean_f = (sum(fcst) / len(fcst)) if fcst else 0.0
        if mean_h > 1 and mean_f > 5 * mean_h:
            findings.append(
                Finding(
                    "SALTO_DE_NIVEL",
                    "error",
                    "El pronóstico futuro está >5× el nivel reciente: posible error de escala.",
                )
            )
            verdict = "DESCARTAR"
        zeros = sum(1 for v in hist if v == 0)
        if zeros / len(hist) >= 0.7 and verdict != "DESCARTAR":
            findings.append(
                Finding(
                    "HISTORICO_ESPARSO",
                    "info",
                    "Más del 70% del histórico es cero; conviene modelo intermitente.",
                )
            )
            if verdict == "MANTENER":
                verdict = "REVISAR"

    demand_type = str(p.meta.get("Tipo de demanda") or "") or None
    vendor_model = str(p.meta.get("Modelo") or "") or None
    return ProductAudit(
        product_id=p.product_id,
        sku=p.sku,
        verdict=verdict,
        findings=tuple(findings),
        recommended_models=recommend_models(demand_type),
        vendor_model=vendor_model,
        vendor_error=vendor_error if isinstance(vendor_error, (int, float)) else None,
        demand_type=demand_type,
    )
