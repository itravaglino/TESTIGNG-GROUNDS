"""Ranked forecasting-model recommendations for one demand series.

Stdlib only. Nothing is fitted here: the function reads the profile, metrics
and findings another stage already computed and returns 3 to 5 options a
demand planner can act on.

Rules are applied in the order below. Each match appends models; later rules
only fill slots that are still free. Names are never repeated.

1. No history, or fewer than 6 observed forecast points: simple baselines.
2. Intermittent or lumpy: Croston SBA, TSB, IMAPA/ADIDA, then an ensemble.
3. Erratic: intermittent methods, a robust ETS, and a quantile/conformal note.
4. Strong seasonality and enough history: Holt-Winters, SARIMA, Theta,
   Prophet only on long monthly series, then a conditional global model.
5. Trend and weak seasonality: Holt linear, ARIMA, Theta, damped trend.
6. Smooth and already tight: SES and ETS, without overselling a change.
7. Loses to naive: seasonal naive and naive move to the front.
8. Short but non-empty history: moving average, naive, conditional MinT.

The naive or seasonal-naive baseline stays on the list unless five stronger
models are already justified and FVA versus naive is above 0.15.
"""

from __future__ import annotations

_FITS = {"alto", "medio", "bajo"}
_MAX_MODELS = 5
_MIN_MODELS = 3
_BASELINES = {"Seasonal Naive", "Naive"}

_UP_TRENDS = {
    "up",
    "alza",
    "alcista",
    "increasing",
    "increase",
    "upward",
    "growth",
    "sube",
    "creciente",
    "creciendo",
    "ascendente",
}
_DOWN_TRENDS = {
    "down",
    "baja",
    "bajista",
    "decreasing",
    "decrease",
    "downward",
    "decreciente",
    "decreciendo",
    "cae",
    "cayendo",
    "descendente",
}
_FLAT_TRENDS = {
    "flat",
    "none",
    "no",
    "estable",
    "sin tendencia",
    "neutral",
    "n/a",
    "na",
    "null",
    "sideways",
    "0",
}
_EXACT_CLASS = {
    "intermittent": "intermittent",
    "intermitente": "intermittent",
    "lumpy": "lumpy",
    "abultada": "lumpy",
    "abultado": "lumpy",
    "irregular": "lumpy",
    "erratic": "erratic",
    "erratica": "erratic",
    "erratico": "erratic",
    "smooth": "smooth",
    "suave": "smooth",
    "estable": "smooth",
}
_CLASS_HINTS = (
    ("intermittent", "intermittent"),
    ("intermitente", "intermittent"),
    ("erratic", "erratic"),
    ("lumpy", "lumpy"),
    ("abultad", "lumpy"),
    ("irregular", "lumpy"),
    ("smooth", "smooth"),
    ("suave", "smooth"),
)
_MONTHLY = {
    "m",
    "ms",
    "me",
    "bm",
    "bms",
    "cbm",
    "cbms",
    "mo",
    "month",
    "monthly",
    "mensual",
    "mensuales",
}
_WEEKLY = {"w", "week", "weekly", "semanal", "semanales"}
_QUARTERLY = {
    "q",
    "qs",
    "qe",
    "bq",
    "bqs",
    "quarter",
    "quarterly",
    "trimestral",
    "trimestrales",
}


class _Ctx:
    """Numbers and flags shared by every recommendation text."""


def recommend_models(profile: dict, metrics: dict, findings: list[dict], frequency: str) -> list[dict]:
    """Return 3 to 5 ranked recommendations.

    Each item has rank, model, alias, family, library, fit, why,
    avoid_when and improves. ``why`` is Spanish and cites this series.
    """

    profile = profile if isinstance(profile, dict) else {}
    metrics = metrics if isinstance(metrics, dict) else {}
    if findings is None:
        findings = []
    elif isinstance(findings, dict):
        findings = [findings]
    frequency = "" if frequency is None else str(frequency)

    ctx = _make_ctx(profile, metrics, findings, frequency)
    if ctx.insufficient:
        keys = []
        if ctx.freq_seasonal:
            keys.append("Seasonal Naive")
        keys.extend(["Naive", "Moving Average"])
        if len(keys) < _MIN_MODELS:
            keys.append("Historical Mean")
        return _emit(ctx, [(key, "bajo", "rule") for key in keys])
    return _emit(ctx, _assemble(_rules(ctx), ctx))


def _make_ctx(profile: dict, metrics: dict, findings, frequency: str) -> _Ctx:
    ctx = _Ctx()
    ctx.demand_raw = _pick_alias(profile, metrics, "demand_class")
    ctx.demand = _demand_class(ctx.demand_raw)
    ctx.n_raw = _pick_alias(profile, metrics, "n_actual")
    ctx.n = _num(ctx.n_raw)
    ctx.n_forecast_raw = _pick_alias(profile, metrics, "n_forecast")
    ctx.n_forecast = _num(ctx.n_forecast_raw)
    ctx.seasonality_raw = _pick_alias(profile, metrics, "seasonality_strength")
    ctx.seasonality = _num(ctx.seasonality_raw)
    ctx.wape_raw = _pick_alias(profile, metrics, "wape")
    ctx.wape = _num(ctx.wape_raw)
    ctx.bias_raw = _pick_alias(profile, metrics, "bias_pct")
    ctx.bias = _num(ctx.bias_raw)
    ctx.flatness_raw = _pick_alias(profile, metrics, "flatness")
    ctx.fva_raw = _pick_alias(profile, metrics, "fva_vs_naive")
    ctx.fva = _num(ctx.fva_raw)
    ctx.zero_raw = _pick_alias(profile, metrics, "zero_actual_pct")
    ctx.zero = _num(ctx.zero_raw)
    ctx.trend_raw = _pick_alias(profile, metrics, "trend_direction")
    ctx.trend = _trend_direction(ctx.trend_raw)
    ctx.frequency = frequency.strip()
    ctx.freq_kind = _freq_kind(ctx.frequency)
    ctx.freq_seasonal = ctx.freq_kind in {"M", "W", "Q"}
    ctx.insufficient = _is_insufficient(ctx.n, ctx.n_forecast)
    ctx.loses = (ctx.fva is not None and ctx.fva < 0) or _has_finding(
        findings, "loses_to_naive"
    )
    ctx.zero_heavy = ctx.zero is not None and ctx.zero > 0.6
    ctx.seasonal_ready = _seasonal_ready(ctx.n, ctx.freq_kind, ctx.seasonality)
    ctx.weak_season = ctx.seasonality is None or ctx.seasonality < 0.35
    ctx.humble = (
        ctx.demand == "smooth"
        and (ctx.wape is None or ctx.wape < 0.25)
        and ctx.fva is not None
        and ctx.fva > 0
        and not ctx.loses
        and not ctx.insufficient
    )
    ctx.short = ctx.n is not None and 0 < ctx.n < 12 and not ctx.insufficient
    ctx.facts = _facts(ctx)
    ctx.baseline = "Seasonal Naive" if ctx.freq_seasonal else "Naive"
    return ctx


def _is_insufficient(n_actual, n_forecast) -> bool:
    if n_actual is not None and n_actual <= 0:
        return True
    if n_forecast is not None and n_forecast < 6:
        return True
    return False


def _seasonal_ready(n_actual, freq_kind, strength) -> bool:
    if strength is None or n_actual is None or strength < 0.35:
        return False
    if freq_kind == "W":
        return n_actual >= 104
    return n_actual >= 24


def _rules(ctx: _Ctx) -> list:
    """Justified models in rule order. The reference baseline is added later."""

    items: list = []
    if ctx.demand in {"intermittent", "lumpy"}:
        fit = _intermittent_fit(ctx)
        secondary = "bajo" if fit == "bajo" else "medio"
        _add(items, "Croston SBA", fit, "rule")
        _add(items, "TSB", fit, "rule")
        _add(items, "IMAPA/ADIDA", secondary, "rule")
        _add(items, "Intermittent Ensemble", secondary, "rule")
    elif ctx.demand == "erratic":
        # Same intermittent order, then robust ETS. The ensemble yields its
        # slot to ETS when a baseline still has to fit in the five.
        fit = "bajo" if ctx.n is not None and ctx.n < 12 else "medio"
        _add(items, "Croston SBA", fit, "rule")
        _add(items, "TSB", fit, "rule")
        _add(items, "IMAPA/ADIDA", fit, "rule")
        _add(items, "Robust ETS", fit, "rule")
        _add(items, "Intermittent Ensemble", fit, "rule")

    if ctx.seasonal_ready:
        _add(items, "Holt-Winters", "alto", "rule")
        sarima_fit = "alto" if ctx.n is not None and ctx.n >= 36 else "medio"
        _add(items, "SARIMA", sarima_fit, "rule")
        _add(items, "Theta", "alto", "rule")
        if ctx.freq_kind == "M" and ctx.n is not None and ctx.n >= 36:
            _add(items, "Prophet", "medio", "rule")
        _add(items, "LightGBM Global", "medio", "rule")

    if ctx.trend in {"up", "down"} and ctx.weak_season:
        _add(items, "Holt Linear", "alto", "rule")
        _add(items, "ARIMA", "medio", "rule")
        _add(items, "Theta", "medio", "rule")
        _add(items, "Damped Trend", "alto", "rule")

    if ctx.demand == "smooth" and (ctx.wape is None or ctx.wape < 0.25):
        mild_season = ctx.seasonality is not None and ctx.seasonality >= 0.2
        first, second = ("ETS", "SES") if mild_season else ("SES", "ETS")
        _add(items, first, "medio", "rule")
        _add(items, second, "medio", "rule")

    if ctx.n is not None and 0 < ctx.n < 12:
        _add(items, "Moving Average", "medio", "rule")
        _add(items, "Naive", "medio", "rule")
        _add(items, "MinT Reconciliation", "medio", "rule")
    return items


def _intermittent_fit(ctx: _Ctx) -> str:
    if ctx.n is not None and ctx.n < 12:
        return "bajo"
    if ctx.n is not None and ctx.n < 18:
        return "medio"
    return "alto"


def _assemble(rules: list, ctx: _Ctx) -> list:
    items: list = []
    if ctx.loses:
        _add(items, "Seasonal Naive", "alto", "anchor")
        _add(items, "Naive", "alto", "anchor")
    for key, fit, origin in rules:
        _add(items, key, fit, origin)

    better = [
        item
        for item in items
        if item[2] == "rule" and item[0] != ctx.baseline and item[0] not in _BASELINES
    ]
    fva_high = ctx.fva is not None and ctx.fva > 0.15
    has_baseline = any(item[0] == ctx.baseline for item in items)
    omit_baseline = (not ctx.loses) and fva_high and len(better) >= _MAX_MODELS
    will_add_baseline = (not omit_baseline) and not has_baseline
    target = 2 if will_add_baseline else _MIN_MODELS
    if len(items) < target:
        for key, fit in _fallbacks(ctx):
            if len(items) >= target:
                break
            if key == ctx.baseline:
                continue
            _add(items, key, fit, "fallback")
    if will_add_baseline:
        _add(items, ctx.baseline, "medio", "baseline")
    return _trim(items, ctx, fva_high)


def _trim(items: list, ctx: _Ctx, fva_high: bool) -> list:
    def is_anchor(item) -> bool:
        return item[2] == "anchor" or (ctx.loses and item[0] in _BASELINES)

    def is_protected_baseline(item) -> bool:
        if is_anchor(item):
            return True
        return item[0] == ctx.baseline or item[2] == "baseline"

    while len(items) > _MAX_MODELS:
        fallback_at = [
            i
            for i, item in enumerate(items)
            if item[2] == "fallback" and not is_anchor(item)
        ]
        if fallback_at:
            items.pop(fallback_at[-1])
            continue
        others = [i for i, item in enumerate(items) if not is_protected_baseline(item)]
        bases = [i for i, item in enumerate(items) if is_protected_baseline(item)]
        if fva_high and not ctx.loses and len(others) >= _MAX_MODELS and bases:
            items.pop(bases[-1])
            continue
        if others:
            items.pop(others[-1])
            continue
        if fva_high and not ctx.loses and bases:
            items.pop(bases[-1])
            continue
        break
    return items


def _fallbacks(ctx: _Ctx) -> list:
    if ctx.demand in {"intermittent", "lumpy", "erratic"}:
        pairs = [
            ("Moving Average", "bajo"),
            ("Historical Mean", "bajo"),
            ("MinT Reconciliation", "bajo"),
            ("Naive", "medio"),
        ]
    elif ctx.trend in {"up", "down"} and not ctx.seasonal_ready:
        pairs = [
            ("Holt Linear", "medio"),
            ("Theta", "medio"),
            ("Damped Trend", "medio"),
            ("Moving Average", "bajo"),
            ("Naive", "medio"),
        ]
    else:
        pairs = [
            ("ETS", "bajo"),
            ("Theta", "bajo"),
            ("Moving Average", "bajo"),
            ("SES", "bajo"),
            ("Historical Mean", "bajo"),
            ("Naive", "medio"),
        ]
    if ctx.freq_seasonal:
        pairs.append(("Seasonal Naive", "medio"))
    return pairs


def _emit(ctx: _Ctx, items: list) -> list[dict]:
    rows = []
    seen = set()
    for key, fit, origin in items:
        if key in seen or key not in _CATALOG:
            continue
        seen.add(key)
        row = _build(ctx, key, fit, origin)
        row["rank"] = len(rows) + 1
        rows.append(row)
        if len(rows) == _MAX_MODELS:
            break
    return rows


def _add(items: list, key: str, fit: str, origin: str) -> None:
    for index, (existing, _fit, old_origin) in enumerate(items):
        if existing != key:
            continue
        if _origin_rank(origin) < _origin_rank(old_origin):
            items[index] = (existing, fit, origin)
        return
    items.append((key, fit, origin))


def _origin_rank(origin: str) -> int:
    return {"anchor": 0, "rule": 1, "baseline": 2, "fallback": 3}.get(origin, 9)


def _build(ctx: _Ctx, key: str, fit: str, origin: str) -> dict:
    spec = _CATALOG[key]
    return {
        "rank": 0,
        "model": spec["model"],
        "alias": spec["alias"],
        "family": spec["family"],
        "library": spec["library"],
        "fit": _final_fit(ctx, key, fit, origin),
        "why": spec["why"](ctx),
        "avoid_when": spec["avoid"],
        "improves": spec["improves"],
    }


def _final_fit(ctx: _Ctx, key: str, fit: str, origin: str) -> str:
    if ctx.insufficient:
        return "bajo"
    if ctx.loses and key in _BASELINES:
        return "alto"
    if ctx.loses and origin != "anchor":
        return "bajo"
    if fit not in _FITS:
        return "medio"
    return fit


def _why(ctx: _Ctx, specific: str) -> str:
    parts = [ctx.facts, " ".join(specific.split())]
    if ctx.zero_heavy and ctx.demand in {"intermittent", "lumpy", "erratic"}:
        parts.append(
            "Con zero_actual_pct=%s (>0.6) hay inflación de ceros: evalúe también "
            "un modelo zero-inflated y no promedie los ceros como si fueran demanda chica."
            % _fmt(ctx.zero_raw)
        )
    if ctx.short and "MinT" not in specific:
        parts.append(
            "Historia corta (n_actual=%s < 12): un ítem análogo o reconciliación "
            "jerárquica MinT solo sirve si existe familia, bodega o SKU parecido "
            "con más datos. Si ese vínculo no existe, no lo invente."
            % _fmt(ctx.n_raw)
        )
    if ctx.demand == "erratic" and "conformal" not in specific.lower():
        parts.append(
            "Nota: publique un intervalo por cuantiles o conformal además del punto. "
            "En demanda erratic el faltante lo marca el cuantil de servicio, no el promedio."
        )
    if (
        not ctx.insufficient
        and not ctx.seasonal_ready
        and ctx.seasonality is not None
        and ctx.seasonality >= 0.35
    ):
        parts.append(
            "La estacionalidad ya se ve (seasonality_strength=%s), pero todavía no "
            "hay muestra para Holt-Winters: hacen falta 24 períodos, o 104 si la "
            "frecuencia es semanal."
            % _fmt(ctx.seasonality_raw)
        )
    if ctx.loses and not ctx.insufficient:
        parts.append(
            "No despliegue un modelo más pesado hasta que le gane a este baseline "
            "en un holdout (período que no se usó para ajustar)."
        )
    if ctx.humble:
        parts.append(
            "Con fva_vs_naive=%s (>0) el pronóstico actual puede bastar. "
            "No cambie de modelo por cambiar; confírmelo en un holdout."
            % _fmt(ctx.fva_raw)
        )
    if ctx.insufficient:
        parts.append(_insufficient_sentence(ctx))
    return " ".join(part.strip() for part in parts if part and part.strip())


def _insufficient_sentence(ctx: _Ctx) -> str:
    if ctx.n is not None and ctx.n <= 0:
        reason = "no hay observaciones reales de demanda (n_actual=%s)" % _fmt(ctx.n_raw)
    elif ctx.n_forecast is not None and ctx.n_forecast < 6:
        reason = (
            "el tramo ya observado del pronóstico es corto (n_forecast=%s < 6)"
            % _fmt(ctx.n_forecast_raw)
        )
    else:
        reason = "la evidencia no alcanza para medir un error"
    return (
        "La precisión no se puede demostrar: %s. Quédese en un baseline simple "
        "y no recomiende deep learning."
        % reason
    )


def _facts(ctx: _Ctx) -> str:
    pairs = (
        ("demand_class", ctx.demand_raw),
        ("n_actual", ctx.n_raw),
        ("seasonality_strength", ctx.seasonality_raw),
        ("wape", ctx.wape_raw),
        ("bias_pct", ctx.bias_raw),
        ("flatness", ctx.flatness_raw),
        ("fva_vs_naive", ctx.fva_raw),
        ("zero_actual_pct", ctx.zero_raw),
        ("n_forecast", ctx.n_forecast_raw),
        ("trend_direction", ctx.trend_raw),
    )
    shown = ["%s=%s" % (label, _fmt(value)) for label, value in pairs if value is not None]
    if not shown:
        return (
            "Cifras de esta serie: no hay demand_class, n_actual, "
            "seasonality_strength, wape, bias_pct ni flatness informados."
        )
    return "Cifras de esta serie: %s." % ", ".join(shown)


def _why_seasonal_naive(ctx: _Ctx) -> str:
    lag = {
        "M": "rezago 12, el mismo mes del año pasado",
        "W": "rezago 52, la misma semana del año pasado",
        "Q": "rezago 4, el mismo trimestre del año pasado",
    }.get(ctx.freq_kind, "el período estacional comparable, no el último período")
    if ctx.insufficient:
        text = (
            "Naive estacional (%s): úselo solo como referencia provisional. "
            "No alcanza para demostrar precisión."
            % lag
        )
    elif ctx.loses:
        text = (
            "Póngalo primero. El pronóstico vigente no le gana al naive estacional "
            "(%s). Copie esa estación y mida ahí el holdout."
            % lag
        )
    else:
        text = (
            "Deje el naive estacional en la comparación (%s). Es el piso que "
            "cualquier modelo de esta frecuencia tiene que superar."
            % lag
        )
    return _why(ctx, text)


def _why_naive(ctx: _Ctx) -> str:
    if ctx.insufficient:
        text = "Naive de último valor: referencia provisional, no un modelo para desplegar."
    elif ctx.loses:
        text = (
            "El pronóstico vigente pierde contra repetir el último valor. "
            "Ese naive va antes que cualquier modelo con parámetros."
        )
    else:
        text = (
            "El naive de último valor es el piso. Si el candidato no lo supera "
            "fuera de muestra, el candidato sobra."
        )
    return _why(ctx, text)


def _why_moving_average(ctx: _Ctx) -> str:
    text = (
        "Media móvil corta (3 a 6 períodos) para quitar un pico aislado sin "
        "inventar tendencia ni estacionalidad. No alargue la ventana: se come "
        "el giro reciente."
    )
    return _why(ctx, text)


def _why_historical_mean(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "Promedio de lo poco que hay. Con esta evidencia un modelo con parámetros "
        "solo memoriza ruido.",
    )


def _why_croston(ctx: _Ctx) -> str:
    if ctx.demand == "lumpy":
        lead = (
            "Croston SBA es la primera opción para clase lumpy: hay rachas de ceros "
            "y el tamaño del pedido cambia mucho. La corrección SBA baja el sesgo "
            "al alza del Croston clásico."
        )
    elif ctx.demand == "erratic":
        lead = (
            "Croston SBA ordena la cadencia, pero la clase erratic además cambia de "
            "tamaño. Úselo como base y no como único número de plan."
        )
    else:
        lead = (
            "Croston SBA es la primera opción para clase intermittent: separa cada "
            "cuánto sale un pedido y de qué tamaño, y la corrección SBA evita inflar "
            "el stock."
        )
    if ctx.demand == "erratic":
        lead += (
            " Si el holdout no separa un ganador, arme un ensamble de Croston SBA, "
            "TSB e IMAPA/ADIDA."
        )
    return _why(ctx, lead)


def _why_tsb(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "TSB (Teunter-Syntetos-Babai) actualiza en cada período la probabilidad de "
        "que haya pedido. Sirve si el SKU se está apagando: Croston SBA seguiría "
        "pronosticando tamaño aunque ya no salga demanda.",
    )


def _why_imapa(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "IMAPA, o la alternativa ADIDA, agrega varios períodos, pronostica el bloque "
        "y lo reparte al grano original. Reduce el ruido de los ceros sin tratar la "
        "serie como demanda continua. Es el tercer paso, después de Croston SBA y TSB.",
    )


def _why_ensemble(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "Ensamble de Croston SBA, TSB e IMAPA/ADIDA. En intermitencia cada método "
        "se equivoca distinto; el promedio suele estabilizar el tamaño de pedido. "
        "No lo use si todavía no hay un holdout para pesarlos.",
    )


def _why_robust_ets(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "ETS robusto, con pérdida menos sensible a picos, acompaña a los métodos "
        "intermitentes cuando la clase es erratic. Un ETS clásico se va detrás del "
        "outlier y no debe ser el modelo principal.",
    )


def _why_holt_winters(ctx: _Ctx) -> str:
    text = (
        "Holt-Winters (ETS con estacionalidad) encaja: seasonality_strength=%s "
        "y la historia alcanza para estimar el ciclo. Capture nivel, tendencia "
        "y estación juntos."
        % _fmt(ctx.seasonality_raw)
    )
    if ctx.demand in {"intermittent", "lumpy"}:
        text += (
            " No lo use como modelo principal: en intermitencia o lumpy, ETS rellena "
            "ceros. Croston SBA, TSB e IMAPA/ADIDA van primero."
        )
    return _why(ctx, text)


def _why_sarima(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "SARIMA explicita el rezago estacional y la autocorrelación. Úselo si "
        "Holt-Winters se queda corto, y elija el orden con holdout, no con el "
        "ajuste dentro de muestra.",
    )


def _why_theta(ctx: _Ctx) -> str:
    if ctx.seasonal_ready:
        lead = (
            "Theta descompone nivel y curvatura y suele competir bien en series "
            "estacionales sin una búsqueda grande de parámetros."
        )
    else:
        lead = (
            "Theta acompaña a Holt cuando hay tendencia y poca estacionalidad: "
            "separa la pendiente de la curvatura local y no exige un ciclo."
        )
    return _why(ctx, lead)


def _why_prophet(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "Prophet queda habilitado con n_actual=%s (>=36) en frecuencia mensual. "
        "Compensa si hay feriados o quiebres de tendencia; si no los hay, "
        "Holt-Winters es más transparente y alcanza."
        % _fmt(ctx.n_raw),
    )


def _why_lightgbm(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "LightGBM global con features de calendario, condicional: si hay muchos "
        "SKU similares. En un solo SKU el modelo memoriza ruido. No lo entrene "
        "hasta confirmar que el portafolio comparte estacionalidad y calendario.",
    )


def _why_holt_linear(ctx: _Ctx) -> str:
    direction = "al alza" if ctx.trend == "up" else "a la baja"
    raw = _fmt(ctx.trend_raw) if ctx.trend_raw is not None else direction
    return _why(
        ctx,
        "Holt lineal (nivel y pendiente) porque la tendencia va %s "
        "(trend_direction=%s) y la estacionalidad es débil. Un promedio se queda "
        "atrás de esa deriva."
        % (direction, raw),
    )


def _why_arima(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "ARIMA recoge la autocorrelación de una serie con tendencia y sin ciclo "
        "fuerte. Fije el orden en un holdout: un ARIMA bonito dentro de muestra "
        "se desploma al pronosticar.",
    )


def _why_damped(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "Tendencia amortiguada (damped trend): la pendiente se apaga hacia adelante "
        "en vez de dibujar una recta hasta el fin del horizonte. Corrige el error "
        "de extrapolar una racha que no es permanente.",
    )


def _why_ses(ctx: _Ctx) -> str:
    if ctx.wape is None:
        error = "No hay WAPE informado. "
    else:
        error = "El wape=%s no justifica un modelo grande. " % _fmt(ctx.wape_raw)
    return _why(
        ctx,
        "La clase es smooth. %sSES solo actualiza el nivel: es el cambio más "
        "chico y auditable. Si el pronóstico vigente ya está sano, no lo reemplace "
        "sin un holdout."
        % error,
    )


def _why_ets(ctx: _Ctx) -> str:
    return _why(
        ctx,
        "ETS elige entre nivel, tendencia y estacionalidad con una regla clara. "
        "En demanda smooth es un paso corto y explicable en el S&OP. "
        "Compare contra SES y contra el naive antes de quedarse con él.",
    )


def _why_mint(ctx: _Ctx) -> str:
    n_txt = _fmt(ctx.n_raw) if ctx.n_raw is not None else "poca"
    return _why(
        ctx,
        "Con n_actual=%s la serie del SKU no sostiene un modelo propio. Use MinT "
        "(reconciliación jerárquica) o un ítem análogo solo si hay familia, bodega "
        "o SKU parecido con historia de verdad. Es condicional: sin esa estructura, "
        "quédese en la media móvil y el naive."
        % n_txt,
    )


def _entry(model, alias, family, library, why, avoid, improves) -> dict:
    return {
        "model": model,
        "alias": alias,
        "family": family,
        "library": library,
        "why": why,
        "avoid": avoid,
        "improves": improves,
    }


_CATALOG = {
    "Seasonal Naive": _entry(
        "Seasonal Naive",
        "Naive estacional",
        "base",
        "statsforecast",
        _why_seasonal_naive,
        "Cuando no existe un ciclo comparable (SKU nuevo, estacionalidad que cambió de forma) o cuando la serie es intermitente y la estación anterior fue un cero aislado.",
        "El error de ignorar el pico de temporada y planear con el último período.",
    ),
    "Naive": _entry(
        "Naive",
        "Naive (último valor)",
        "base",
        "statsforecast",
        _why_naive,
        "Cuando hay estacionalidad marcada o una tendencia sostenida: repetir el último período se queda corto en el pico y largo en el valle.",
        "El piso de error: evita desplegar un modelo que ni siquiera le gana a repetir el último valor.",
    ),
    "Moving Average": _entry(
        "Moving Average",
        "Media móvil",
        "base",
        "statsforecast",
        _why_moving_average,
        "Con tendencia o estacionalidad fuerte: la media se atrasa y aplana el pico que sí va a repetirse.",
        "El ruido de un pedido atípico y los saltos de un solo período.",
    ),
    "Historical Mean": _entry(
        "Historical Mean",
        "Promedio histórico",
        "base",
        "statsforecast",
        _why_historical_mean,
        "Cuando ya se ve tendencia o estacionalidad y hay historia para estimarla. El promedio esconde ese patrón.",
        "El sobreajuste cuando casi no hay datos para estimar parámetros.",
    ),
    "Croston SBA": _entry(
        "Croston SBA",
        "Croston SBA",
        "intermitente",
        "statsforecast",
        _why_croston,
        "Con demanda continua (pocos ceros) o cuando el SKU se está descontinuando: SBA no apaga la probabilidad de pedido.",
        "El sesgo al alza del Croston clásico en series con muchos ceros.",
    ),
    "TSB": _entry(
        "TSB",
        "TSB (Teunter-Syntetos-Babai)",
        "intermitente",
        "statsforecast",
        _why_tsb,
        "Con muy pocos eventos para estimar la probabilidad, o cuando solo importa el tamaño medio por pedido y el ítem sigue activo.",
        "La obsolescencia: deja de empujar stock cuando la probabilidad de pedido cae.",
    ),
    "IMAPA/ADIDA": _entry(
        "IMAPA/ADIDA",
        "IMAPA / ADIDA (agregar y desagregar)",
        "intermitente",
        "statsforecast",
        _why_imapa,
        "Con historia corta: al agregar quedan muy pocos bloques. Tampoco si no hay una regla clara para repartir el bloque al período original.",
        "La varianza que meten los ceros cuando se pronostica en el grano más fino.",
    ),
    "Intermittent Ensemble": _entry(
        "Intermittent Ensemble",
        "Ensamble intermitente (Croston, TSB, ADIDA)",
        "ensamble",
        "statsforecast",
        _why_ensemble,
        "Con un puñado de observaciones: promediar métodos inestables no crea información.",
        "El error de apostar el stock a un solo método intermitente.",
    ),
    "Robust ETS": _entry(
        "Robust ETS",
        "ETS robusto",
        "estadístico",
        "statsmodels",
        _why_robust_ets,
        "Como modelo principal en intermitente o lumpy: un ETS rellena los ceros y suele perder contra Croston. Tampoco con historia muy corta.",
        "La sensibilidad a picos atípicos en demanda erratic.",
    ),
    "Holt-Winters": _entry(
        "Holt-Winters",
        "Holt-Winters (ETS estacional)",
        "estadístico",
        "statsmodels",
        _why_holt_winters,
        "Con menos de dos ciclos, con demanda intermitente como caso principal, o si la estacionalidad cambió (promociones irregulares, quiebre de surtido).",
        "El error de nivel en temporada alta y en temporada baja.",
    ),
    "SARIMA": _entry(
        "SARIMA",
        "SARIMA",
        "estadístico",
        "statsmodels",
        _why_sarima,
        "Con historia corta, muchos ceros, o si nadie va a revisar los órdenes. Un SARIMA mal especificado se ve preciso y no lo es.",
        "La autocorrelación estacional que un suavizado simple no captura.",
    ),
    "Theta": _entry(
        "Theta",
        "Método Theta",
        "estadístico",
        "statsforecast",
        _why_theta,
        "Si la serie está dominada por ceros o si necesita un intervalo de stock muy calibrado: Theta da un buen punto, no un cuantil de servicio.",
        "Tendencia y curvatura sin sobreajustar un modelo grande.",
    ),
    "Prophet": _entry(
        "Prophet",
        "Prophet",
        "estadístico",
        "prophet",
        _why_prophet,
        "Con menos de 36 meses, sin feriados relevantes, en intermitencia, o si el equipo no va a mantener los quiebres.",
        "Quiebres de tendencia y feriados que un ETS de estacionalidad fija no ve.",
    ),
    "LightGBM Global": _entry(
        "LightGBM Global",
        "LightGBM global con calendario",
        "ML",
        "lightgbm",
        _why_lightgbm,
        "Si el portafolio es chico o los SKU no se parecen, o si el calendario de promociones no es confiable. Un modelo global mal agrupado copia el ruido de otro ítem.",
        "Patrones de calendario compartidos entre SKU que la serie sola no muestra.",
    ),
    "Holt Linear": _entry(
        "Holt Linear",
        "Holt lineal",
        "estadístico",
        "statsmodels",
        _why_holt_linear,
        "Si la estacionalidad es fuerte (ahí hace falta Holt-Winters) o si la pendiente es un pico de una sola promoción y no una tendencia.",
        "Quedarse en un nivel plano cuando la demanda sube o baja de forma sostenida.",
    ),
    "ARIMA": _entry(
        "ARIMA",
        "ARIMA",
        "estadístico",
        "statsmodels",
        _why_arima,
        "Con pocos datos, con estacionalidad anual sin modelar, o si el planificador necesita leer nivel y pendiente sin un orden ARIMA.",
        "La dependencia con los períodos recientes y la deriva de corto plazo.",
    ),
    "Damped Trend": _entry(
        "Damped Trend",
        "Tendencia amortiguada (damped Holt)",
        "estadístico",
        "statsmodels",
        _why_damped,
        "Si la tendencia es estructural y debe mantenerse, por ejemplo un lanzamiento que sigue creciendo. Amortiguarla corta el plan de más.",
        "La sobre-proyección de la tendencia en horizontes largos.",
    ),
    "SES": _entry(
        "SES",
        "Suavizado exponencial simple (SES)",
        "estadístico",
        "statsmodels",
        _why_ses,
        "Con tendencia, estacionalidad o intermitencia: SES se queda en un nivel plano y llega tarde al pico.",
        "Un nivel desactualizado cuando la demanda smooth se mueve despacio.",
    ),
    "ETS": _entry(
        "ETS",
        "ETS (suavizado exponencial)",
        "estadístico",
        "statsmodels",
        _why_ets,
        "Como única herramienta en demanda intermitente o lumpy, y cuando no hay holdout para compararlo contra el naive.",
        "Elegir mal, a mano, entre nivel, tendencia y estacionalidad.",
    ),
    "MinT Reconciliation": _entry(
        "MinT Reconciliation",
        "Ítem análogo / reconciliación MinT",
        "jerárquico",
        "sktime",
        _why_mint,
        "Si el SKU no pertenece a una familia, cliente, bodega o ítem análogo con historia. MinT no inventa demanda.",
        "El error de pronosticar un SKU corto sin usar la historia del grupo.",
    ),
}


_ALIASES = {
    "demand_class": (
        "demand_class",
        "demand_type",
        "series_class",
        "demand_pattern",
        "clase_demanda",
    ),
    "n_actual": ("n_actual", "n_actuals", "n_history"),
    "n_forecast": ("n_forecast", "n_forecasts"),
    "seasonality_strength": ("seasonality_strength", "seasonal_strength"),
    "wape": ("wape", "WAPE"),
    "bias_pct": ("bias_pct", "bias_percent", "bias"),
    "flatness": ("flatness", "forecast_flatness"),
    "fva_vs_naive": ("fva_vs_naive", "fva", "fva_naive", "forecast_value_added"),
    "zero_actual_pct": ("zero_actual_pct", "zero_demand_pct"),
    "trend_direction": ("trend_direction", "trend", "trend_dir"),
}


def _pick_alias(profile: dict, metrics: dict, canonical: str):
    for key in _ALIASES[canonical]:
        value = _pick(profile, metrics, key)
        if value is not None:
            return value
    return None


def _pick(profile: dict, metrics: dict, key: str):
    for source in (profile, metrics):
        if not isinstance(source, dict):
            continue
        if key in source and source[key] is not None:
            return source[key]
        for value in source.values():
            if isinstance(value, dict) and key in value and value[key] is not None:
                return value[key]
    return None


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(" ", "")
        if not text:
            return None
        if "," in text and "." in text:
            text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return "nan"
        return format(value, ".12g")
    return str(value).strip()


def _norm_token(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "value") and not isinstance(value, (str, bytes, int, float)):
        value = value.value
    text = str(value).strip().lower()
    return text.translate(str.maketrans("áéíóúüñ", "aeiouun"))


def _demand_class(raw):
    token = _norm_token(raw)
    if not token:
        return None
    if token in _EXACT_CLASS:
        return _EXACT_CLASS[token]
    for hint, label in _CLASS_HINTS:
        if hint in token:
            return label
    return None


def _trend_direction(raw):
    token = _norm_token(raw)
    if not token or token in _FLAT_TRENDS:
        return None
    if token in _UP_TRENDS or token.startswith("up") or "increas" in token or "crecien" in token:
        return "up"
    if "al alza" in token:
        return "up"
    if token in _DOWN_TRENDS or token.startswith("down") or "decreas" in token or "decrecien" in token:
        return "down"
    if "a la baja" in token:
        return "down"
    return None


def _freq_kind(frequency: str) -> str:
    if frequency is None:
        return "other"
    raw = str(frequency).strip().lower().replace("_", "-")
    if not raw:
        return "other"
    if raw in _MONTHLY or "month" in raw or "mensual" in raw:
        return "M"
    if raw in _WEEKLY or raw.startswith("w-") or "week" in raw or "semanal" in raw:
        return "W"
    if raw in _QUARTERLY or "quarter" in raw or "trimestr" in raw:
        return "Q"
    index = 0
    while index < len(raw) and raw[index].isdigit():
        index += 1
    unit = raw[index:]
    if unit in _MONTHLY:
        return "M"
    if unit in _WEEKLY:
        return "W"
    if unit in _QUARTERLY:
        return "Q"
    return "other"


def _has_finding(findings, code: str) -> bool:
    target = code.lower()

    def norm(text) -> str:
        cleaned = []
        for char in str(text).lower():
            cleaned.append(char if char.isalnum() else "_")
        return "".join(cleaned)

    def walk(obj) -> bool:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if target in norm(key) and value not in (False, None, 0, "", [], {}):
                    return True
                if walk(value):
                    return True
            return False
        if isinstance(obj, (list, tuple)):
            return any(walk(item) for item in obj)
        if isinstance(obj, str):
            return target in norm(obj)
        return False

    try:
        return walk(findings)
    except Exception:
        return False
