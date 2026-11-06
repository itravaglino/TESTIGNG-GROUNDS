"""Dictamen por producto: mantener, corregir o descartar, y con qué modelo rehacerlo."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from auditor.metrics import calcular_metricas, calidad_forecast, catalogo, cv
from auditor.models import baseline_en_muestra, croston_nivel, pronosticar
from auditor.parse import ParseError, parse_bytes, parse_texto
from auditor.recommend import nota_portafolio, recomendar


def _finite(value) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def _median(values: list[float]) -> float:
    if not values:
        return math.nan
    xs = sorted(values)
    n = len(xs)
    mid = n // 2
    if n % 2:
        return xs[mid]
    return 0.5 * (xs[mid - 1] + xs[mid])


def _escala_volumen(actual: np.ndarray, forecast: np.ndarray) -> float:
    mask = np.isfinite(actual) & np.isfinite(forecast)
    a = actual[mask]
    f = forecast[mask]
    if len(a) == 0:
        return math.nan
    suma_a = float(np.sum(a))
    suma_f = float(np.sum(f))
    ceros = float(np.mean(a == 0))
    if ceros >= 0.4 and abs(suma_a) > 1e-12:
        return suma_f / suma_a
    positivos = a > 0
    if int(np.sum(positivos)) >= 1:
        return _median((f[positivos] / a[positivos]).tolist())
    if abs(suma_a) > 1e-12:
        return suma_f / suma_a
    return math.nan


def _factor_nivel(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Multiplicador sobre el forecast para acercarlo al nivel de la venta."""
    mask = np.isfinite(actual) & np.isfinite(forecast)
    a = actual[mask]
    f = forecast[mask]
    if len(a) == 0 or float(np.sum(np.abs(f))) < 1e-12:
        return math.nan
    if float(np.mean(a == 0)) >= 0.4:
        return float(np.sum(a) / np.sum(f))
    if np.all(f > 0):
        return _median((a / f).tolist())
    return float(np.sum(a) / np.sum(f))


def _picos(actual: np.ndarray, forecast: np.ndarray) -> list[int]:
    mask = np.isfinite(actual) & np.isfinite(forecast)
    if int(mask.sum()) < 4:
        return []
    a = actual[mask]
    f = forecast[mask]
    med_f = float(np.median(forecast[np.isfinite(forecast)]))
    techo = max(float(np.max(a)) * 3, float(np.mean(a) + 8 * np.std(a, ddof=1 if len(a) > 1 else 0)))
    indices = []
    for i, (es, valor) in enumerate(zip(mask, forecast)):
        if not es or not np.isfinite(valor):
            continue
        if valor > techo and valor > med_f * 5:
            indices.append(i)
    return indices


def _cap(actual: np.ndarray) -> float:
    a = actual[np.isfinite(actual)]
    if len(a) == 0:
        return math.inf
    std = float(np.std(a, ddof=1)) if len(a) > 1 else 0.0
    return max(float(np.max(a)) * 1.25, float(np.mean(a) + 4 * std))


def _fechas_futuras(ultima: date, pasos: int, delta: timedelta) -> list[date]:
    return [ultima + delta * (k + 1) for k in range(pasos)]


def _delta_fechas(fechas: list[date]) -> timedelta:
    if len(fechas) < 2:
        return timedelta(days=7)
    deltas = [(b - a).days for a, b in zip(fechas, fechas[1:]) if (b - a).days > 0]
    if not deltas:
        return timedelta(days=7)
    med = int(_median(deltas))
    return timedelta(days=med or 7)


def _clave(fila: dict) -> str:
    loc = fila.get("location") or ""
    base = fila["product_id"]
    return f"{base} · {loc}" if loc else base


def _num(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    if isinstance(value, float):
        return round(value, 6)
    return value


def _json_metricas(metricas: dict) -> dict:
    limpio = {}
    for key, value in metricas.items():
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            limpio[key] = None
        elif isinstance(value, (np.floating, np.integer)):
            limpio[key] = value.item()
        else:
            limpio[key] = value
    return limpio


def _auditar_grupo(nombre: str, filas: list[dict], horizonte: int) -> dict:
    filas = sorted(filas, key=lambda r: r["date"])
    fechas = [r["date"] for r in filas]
    actual = np.array([r["actual"] if _finite(r["actual"]) else np.nan for r in filas], dtype=float)
    forecast = np.array([r["forecast"] if _finite(r["forecast"]) else np.nan for r in filas], dtype=float)
    lower = np.array([r["lower"] if _finite(r["lower"]) else np.nan for r in filas], dtype=float)
    upper = np.array([r["upper"] if _finite(r["upper"]) else np.nan for r in filas], dtype=float)
    overlap = np.isfinite(actual) & np.isfinite(forecast)
    n_ov = int(overlap.sum())
    metricas = calcular_metricas(actual[overlap], forecast[overlap], lower[overlap], upper[overlap]) if n_ov else calcular_metricas([], [])
    calidad = calidad_forecast(forecast)
    adi = metricas.get("adi")
    clase = metricas.get("clase_sbc") or "sin_datos"
    hallazgos = []
    estado = "MANTENER"
    corregido = np.array(forecast, dtype=float)
    toco = False

    def hallazgo(regla, severidad, mensaje):
        hallazgos.append({"regla": regla, "severidad": severidad, "mensaje": mensaje})

    if n_ov >= 8:
        a_ov, f_ov = actual[overlap], forecast[overlap]
        if np.std(a_ov) > 0 and np.std(f_ov) > 0:
            rho = metricas.get("pearson")
            media_abs = float(np.mean(np.abs(a_ov)))
            if rho is not None and not (isinstance(rho, float) and math.isnan(rho)) and rho > 0.995 and metricas["mae"] <= 0.01 * max(media_abs, 1e-12):
                hallazgo("fuga", "alta", "El forecast copia la venta real (correlación por encima de 0.995 y error casi nulo). No se corrige: hay que reentrenar sin la venta del mismo periodo.")
                estado = "DESCARTAR"

    if estado != "DESCARTAR" and n_ov >= 4:
        ratio = _escala_volumen(actual, forecast)
        if not math.isnan(ratio) and (ratio > 5 or ratio < 0.2):
            hallazgo(
                "escala",
                "alta",
                f"La escala del forecast no coincide con la venta (factor {ratio:.2f}, fuera de 0.2 a 5). No se reescala solo: hay que reentrenar la unidad o el modelo.",
            )
            estado = "DESCARTAR"

    if estado != "DESCARTAR" and n_ov >= 4:
        cv_a = cv(actual[overlap])
        cv_f = cv(forecast[overlap])
        if not math.isnan(cv_a) and not math.isnan(cv_f) and cv_a > 0.30 and cv_f < 0.05:
            hallazgo(
                "plano",
                "alta",
                "El forecast está plano y la venta se mueve. Un factor o un recorte no reconstruye la forma: hay que rehacerlo con un modelo que siga el ciclo.",
            )
            estado = "DESCARTAR"

    if estado != "DESCARTAR":
        picos = _picos(actual, forecast)
        if picos:
            if len(picos) <= 3 and len(picos) / max(int(np.isfinite(forecast).sum()), 1) <= 0.10:
                techo = _cap(actual)
                for i in picos:
                    corregido[i] = techo
                toco = True
                hallazgo("pico", "media", f"Se recortaron {len(picos)} picos imposibles al tope {techo:.4g}, por encima de la venta observada.")
            else:
                hallazgo("pico", "alta", "Hay demasiados picos imposibles. Recortarlos reescribiría el plan.")
                estado = "DESCARTAR"
                toco = False
                corregido = np.array(forecast, dtype=float)

    if estado != "DESCARTAR":
        negativos = [i for i, v in enumerate(corregido) if np.isfinite(v) and v < 0]
        if negativos:
            masa_neg = float(np.sum(np.abs(corregido[negativos])))
            masa_pos = float(np.sum(corregido[np.isfinite(corregido) & (corregido > 0)]))
            fraccion = len(negativos) / max(int(np.isfinite(corregido).sum()), 1)
            if fraccion > 0.25 or (masa_pos > 0 and masa_neg / masa_pos > 0.20):
                hallazgo("negativo", "alta", "Una parte grande del forecast es negativa. Ponerla en cero cambiaría el plan.")
                estado = "DESCARTAR"
                toco = False
                corregido = np.array(forecast, dtype=float)
            else:
                for i in negativos:
                    corregido[i] = 0.0
                toco = True
                hallazgo("negativo", "media", f"Se llevaron a cero {len(negativos)} pronósticos negativos. La demanda de unidades no puede vender por debajo de cero.")

    intermitente = (
        n_ov >= 8
        and isinstance(adi, float)
        and not math.isnan(adi)
        and adi >= 1.32
        and float(np.mean(actual[overlap] == 0)) >= 0.40
        and float(np.mean(forecast[overlap] == 0)) < 0.10
    )
    if estado != "DESCARTAR" and intermitente:
        ratio_vol = _escala_volumen(actual, forecast)
        if math.isnan(ratio_vol) or 0.5 <= ratio_vol <= 2:
            nivel = croston_nivel(actual[overlap])
            if math.isnan(nivel):
                positivos = actual[overlap]
                positivos = positivos[positivos > 0]
                nivel = float(np.sum(actual[overlap]) / len(actual[overlap])) if n_ov else 0.0
            for i, v in enumerate(corregido):
                if np.isfinite(forecast[i]):
                    corregido[i] = max(0.0, nivel)
            toco = True
            hallazgo(
                "intermitente",
                "media",
                "La demanda es intermitente y el forecast es una serie suave. Se reemplazó por el nivel de Croston, que es la tasa esperada por periodo.",
            )
        elif ratio_vol > 5 or ratio_vol < 0.2:
            pass
        else:
            factor = _factor_nivel(actual, corregido)
            if not math.isnan(factor) and (factor < 0.9 or factor > 1.1):
                for i, v in enumerate(corregido):
                    if np.isfinite(v):
                        corregido[i] = max(0.0, v * factor)
                toco = True
                hallazgo("sesgo", "media", f"Se multiplicó el forecast por {factor:.4g} para corregir el nivel, y el modelo a usar pasa a ser de demanda intermitente.")

    elif estado != "DESCARTAR" and n_ov >= 4:
        factor = _factor_nivel(actual[overlap], corregido[overlap])
        aplica_multiplicativo = (
            not math.isnan(factor)
            and (factor < 0.9 or factor > 1.1)
            and np.all(corregido[overlap][np.isfinite(corregido[overlap])] > 0)
        )
        if aplica_multiplicativo:
            for i, v in enumerate(corregido):
                if np.isfinite(v):
                    corregido[i] = max(0.0, v * factor)
            toco = True
            sentido = "se pasa" if factor < 1 else "se queda corto"
            hallazgo("sesgo", "media", f"Sesgo de nivel: el forecast {sentido}. Se multiplicó por {factor:.4g} para alinearlo a la venta.")
        else:
            err = corregido[overlap] - actual[overlap]
            me = float(np.mean(err))
            media_a = float(np.mean(np.abs(actual[overlap])))
            signos = err[np.abs(err) > 1e-9]
            concordancia = float(np.mean(np.sign(signos) == np.sign(me))) if len(signos) else 0
            if abs(me) > 0.20 * max(media_a, 1e-12) and concordancia > 0.70 and abs(me) <= 0.50 * max(media_a, 1e-12):
                for i, v in enumerate(corregido):
                    if np.isfinite(v):
                        corregido[i] = max(0.0, v - me)
                toco = True
                hallazgo("sesgo", "media", f"Se restó el sesgo medio ({me:.4g}). Positivo quiere decir que el forecast se pasaba.")

    if estado != "DESCARTAR" and n_ov >= 4 and not toco:
        wape = metricas.get("wape")
        mase = metricas.get("mase")
        wape_malo = isinstance(wape, float) and not math.isnan(wape) and wape > 0.50
        mase_malo = isinstance(mase, float) and not math.isnan(mase) and mase > 1.50
        if wape_malo or mase_malo:
            hallazgo(
                "peor_que_naive",
                "alta",
                "El error es alto y no hay una corrección segura (ni sesgo, ni un pico, ni negativos). Conviene descartar este número y rehacer el pronóstico.",
            )
            estado = "DESCARTAR"

    if n_ov < 8 and estado != "DESCARTAR":
        hallazgo(
            "historia",
            "baja",
            f"Solo hay {n_ov} periodos con venta real (hacen falta 8 para una validación firme). El dictamen es provisorio.",
        )

    if calidad.get("n", 0) == 0:
        hallazgo("vacio", "alta", "El forecast no tiene ningún valor finito.")
        estado = "DESCARTAR"

    if estado == "DESCARTAR":
        toco = False
    elif toco:
        estado = "CORREGIR"
    else:
        estado = "MANTENER"

    if estado == "MANTENER" and not hallazgos:
        hallazgo("ok", "baja", "Sin problemas materiales. El error, el sesgo y la escala están dentro de banda.")

    historia = actual[np.isfinite(actual)]
    rec = recomendar(historia, horizonte=horizonte)
    modelo = rec["modelo_recomendado"]
    # En intermitente el árbol manda, aunque el nombre del archivo diga otra cosa.
    futuro = pronosticar(modelo, historia, horizonte, rec.get("periodo"))
    baseline = baseline_en_muestra(modelo, actual, rec.get("periodo"))
    # baseline_en_muestra recorta NaN. Reconstruimos sobre el índice original.
    baseline_full: list[float | None] = [None] * len(filas)
    hist_positions = [i for i, v in enumerate(actual) if np.isfinite(v)]
    base_hist = baseline_en_muestra(modelo, historia, rec.get("periodo"))
    for pos, valor in zip(hist_positions, base_hist):
        baseline_full[pos] = valor

    serie = []
    for i, fila in enumerate(filas):
        corr = None
        if estado == "CORREGIR" and np.isfinite(corregido[i]):
            corr = _num(float(corregido[i]))
        serie.append({
            "fecha": fila["date"].isoformat(),
            "actual": _num(float(actual[i])) if np.isfinite(actual[i]) else None,
            "forecast": _num(float(forecast[i])) if np.isfinite(forecast[i]) else None,
            "forecast_corregido": corr,
            "baseline": _num(baseline_full[i]) if baseline_full[i] is not None else None,
        })

    delta = _delta_fechas(fechas)
    sugerido = []
    if futuro and fechas:
        for paso, valor in enumerate(_fechas_futuras(fechas[-1], len(futuro), delta)):
            sugerido.append({"fecha": valor.isoformat(), "valor": _num(futuro[paso])})

    problema = next((h["mensaje"] for h in hallazgos if h["severidad"] == "alta"), None)
    if problema is None:
        problema = next((h["mensaje"] for h in hallazgos if h["severidad"] == "media"), hallazgos[-1]["mensaje"])

    if estado == "DESCARTAR":
        accion = "Descartar este número y rehacer el pronóstico con el modelo recomendado."
    elif estado == "CORREGIR":
        accion = "Usar el forecast corregido y, en la próxima corrida, el modelo recomendado."
    else:
        accion = "Mantener el forecast y seguir midiéndolo contra el naive."

    mejora = rec["mejora_modelo"]
    if estado == "DESCARTAR":
        como = problema + " " + mejora
    elif estado == "CORREGIR":
        como = problema + " " + mejora
    else:
        como = "El forecast actual se puede usar. " + mejora

    wape_corr = None
    if estado == "CORREGIR" and n_ov:
        met_c = calcular_metricas(actual[overlap], corregido[overlap])
        wape_corr = met_c.get("wape")

    return {
        "producto": nombre,
        "categoria": filas[0].get("category"),
        "ubicacion": filas[0].get("location"),
        "modelo_origen": filas[0].get("model"),
        "estado": estado,
        "clase_sbc": clase,
        "adi": _num(adi) if isinstance(adi, float) else adi,
        "cv2": _num(metricas.get("cv2")) if isinstance(metricas.get("cv2"), float) else metricas.get("cv2"),
        "problema_principal": problema,
        "accion": accion,
        "como_mejorarlo": como,
        "modelo_recomendado": modelo,
        "modelo_respaldo": rec["modelo_respaldo"],
        "por_que_modelo": rec["por_que"],
        "modelos_que_no": rec["modelos_que_no"],
        "hoja_modelo": rec["codigo"],
        "periodo_estacional": rec.get("periodo"),
        "hallazgos": hallazgos,
        "metricas": _json_metricas(metricas),
        "catalogo": [
            {**item, "valor": _num(item["valor"]) if isinstance(item["valor"], float) else item["valor"]}
            for item in catalogo(metricas)
        ],
        "wape": _num(metricas.get("wape")) if isinstance(metricas.get("wape"), float) else None,
        "mase": _num(metricas.get("mase")) if isinstance(metricas.get("mase"), float) else None,
        "sesgo": _num(metricas.get("pbias")) if isinstance(metricas.get("pbias"), float) else None,
        "me": _num(metricas.get("me")) if isinstance(metricas.get("me"), float) else None,
        "mae": _num(metricas.get("mae")) if isinstance(metricas.get("mae"), float) else None,
        "smape": _num(metricas.get("smape")) if isinstance(metricas.get("smape"), float) else None,
        "wape_corregido": _num(wape_corr) if isinstance(wape_corr, float) else None,
        "serie": serie,
        "sugerido_futuro": sugerido,
        "calidad_forecast": {k: _num(v) if isinstance(v, float) else v for k, v in calidad.items()},
    }


def _portafolio(productos: list[dict]) -> dict:
    conteos = {"MANTENER": 0, "CORREGIR": 0, "DESCARTAR": 0}
    sum_abs = 0.0
    sum_vol = 0.0
    sum_err = 0.0
    sum_naive = 0.0
    sum_model = 0.0
    n_naive = 0
    for p in productos:
        conteos[p["estado"]] = conteos.get(p["estado"], 0) + 1
        met = p.get("metricas") or {}
        n = met.get("n") or 0
        if not n or met.get("wape") is None or met.get("media_actual") is None:
            continue
        vol = abs(met["media_actual"]) * n
        sum_vol += vol
        sum_abs += met["wape"] * vol
        if met.get("me") is not None:
            sum_err += met["me"] * n
        if met.get("mase") is not None and met.get("mae") is not None and met["mase"] not in (0, None):
            # MAE naive ≈ MAE / MASE
            mae_naive = met["mae"] / met["mase"] if met["mase"] else None
            if mae_naive:
                sum_naive += mae_naive * n
                sum_model += met["mae"] * n
                n_naive += n
    wape = sum_abs / sum_vol if sum_vol else None
    sesgo = sum_err / sum_vol if sum_vol else None
    fva = (sum_naive - sum_model) / sum_naive if sum_naive else None
    util_abs = 0.0
    util_vol = 0.0
    for p in productos:
        if p["estado"] == "DESCARTAR":
            continue
        met = p.get("metricas") or {}
        n = met.get("n") or 0
        if not n or met.get("media_actual") is None:
            continue
        vol = abs(met["media_actual"]) * n
        wape_p = p.get("wape_corregido") if p["estado"] == "CORREGIR" and p.get("wape_corregido") is not None else p.get("wape")
        if wape_p is None:
            continue
        util_vol += vol
        util_abs += wape_p * vol
    wape_usable = util_abs / util_vol if util_vol else None
    return {
        "mantener": conteos["MANTENER"],
        "corregir": conteos["CORREGIR"],
        "descartar": conteos["DESCARTAR"],
        "productos": len(productos),
        "wape": _num(wape) if isinstance(wape, float) else None,
        "wape_usable": _num(wape_usable) if isinstance(wape_usable, float) else None,
        "sesgo": _num(sesgo) if isinstance(sesgo, float) else None,
        "fva_vs_naive": _num(fva) if isinstance(fva, float) else None,
    }


def _ordenar(productos: list[dict]) -> list[dict]:
    peso = {"DESCARTAR": 0, "CORREGIR": 1, "MANTENER": 2}

    def clave(p):
        wape = p.get("wape")
        wape_key = -(wape if isinstance(wape, (int, float)) else -1)
        return (peso.get(p["estado"], 9), wape_key, p["producto"])

    return sorted(productos, key=clave)


def _limpiar(obj):
    if isinstance(obj, dict):
        return {k: _limpiar(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_limpiar(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def auditar_filas(filas: list[dict], avisos: list[str] | None = None, columnas: dict | None = None, horizonte: int = 8) -> dict:
    if not filas:
        raise ParseError("El archivo está vacío: no hay datos para auditar.")
    grupos: dict[str, list[dict]] = {}
    for fila in filas:
        grupos.setdefault(_clave(fila), []).append(fila)
    productos = [_auditar_grupo(nombre, grupo, horizonte) for nombre, grupo in grupos.items()]
    nota = nota_portafolio(productos)
    if nota:
        for p in productos:
            if p.get("modelo_origen") and p["clase_sbc"] in {"suave", "erratica", "intermitente", "lumpy"}:
                p["hallazgos"].append({"regla": "portafolio", "severidad": "baja", "mensaje": nota})
    productos = _ordenar(productos)
    fechas = [f["date"] for f in filas]
    resultado = {
        "lectura": {
            "filas": len(filas),
            "productos": len(productos),
            "fecha_min": min(fechas).isoformat(),
            "fecha_max": max(fechas).isoformat(),
            "columnas": columnas or {},
            "avisos": avisos or [],
            "tiene_actual": any(f["actual"] is not None for f in filas),
        },
        "portafolio": _portafolio(productos),
        "productos": productos,
        "nota_portafolio": nota,
    }
    return _limpiar(resultado)


def auditar_texto(text: str, horizonte: int = 8) -> dict:
    parsed = parse_texto(text)
    return auditar_filas(parsed["filas"], parsed["avisos"], parsed["columnas"], horizonte)


def auditar_bytes(payload: bytes, horizonte: int = 8) -> dict:
    parsed = parse_bytes(payload)
    return auditar_filas(parsed["filas"], parsed["avisos"], parsed["columnas"], horizonte)


def filas_dictamen(resultado: dict) -> list[dict]:
    filas = []
    for p in resultado["productos"]:
        filas.append({
            "producto": p["producto"],
            "categoria": p.get("categoria") or "",
            "clase_sbc": p.get("clase_sbc") or "",
            "dictamen": p["estado"],
            "modelo_recomendado": p.get("modelo_recomendado") or "",
            "modelo_respaldo": p.get("modelo_respaldo") or "",
            "wape": p.get("wape") if p.get("wape") is not None else "",
            "mase": p.get("mase") if p.get("mase") is not None else "",
            "sesgo": p.get("sesgo") if p.get("sesgo") is not None else "",
            "problema_principal": p.get("problema_principal") or "",
            "accion": p.get("accion") or "",
            "como_mejorarlo": p.get("como_mejorarlo") or "",
        })
    return filas


def filas_forecast_corregido(resultado: dict) -> list[dict]:
    filas = []
    for p in resultado["productos"]:
        for punto in p["serie"]:
            usable = p["estado"] == "CORREGIR" and punto["forecast_corregido"] is not None
            filas.append({
                "producto": p["producto"],
                "fecha": punto["fecha"],
                "forecast": punto["forecast"] if punto["forecast"] is not None else "",
                "forecast_corregido": punto["forecast_corregido"] if usable else "",
                "dictamen": p["estado"],
            })
    return filas
