"""Árbol de modelos por producto. Prophet, SARIMA y redes se recomiendan y no se entrenan."""

from __future__ import annotations

import math

import numpy as np

from auditor.metrics import adi_cv2, pearson
from auditor.models import acf_lag, mejor_periodo


def _tendencia(y: np.ndarray) -> bool:
    if len(y) < 6:
        return False
    t = np.arange(len(y), dtype=float)
    rho = pearson(y, t)
    return not math.isnan(rho) and abs(rho) >= 0.6


def recomendar(actual, horizonte: int = 4) -> dict:
    y = np.asarray(list(actual), dtype=float)
    y = y[np.isfinite(y)]
    n = len(y)
    adi, cv2, clase = adi_cv2(y) if n else (math.nan, math.nan, "sin_datos")
    periodo, estacional, rho = mejor_periodo(y) if n else (None, False, math.nan)
    ceros = bool(n and np.any(y == 0))
    intermitente = bool(ceros and not math.isnan(adi) and adi >= 1.32)
    eventos = int(np.sum(y > 0)) if n else 0
    tendencia = _tendencia(y) if n else False
    h = horizonte
    cv2_val = 0.0 if math.isnan(cv2) else cv2

    def hoja(codigo, principal, respaldo, por_que, no_usar, mejora):
        return {
            "codigo": codigo,
            "modelo_recomendado": principal,
            "modelo_respaldo": respaldo,
            "por_que": por_que,
            "modelos_que_no": no_usar,
            "mejora_modelo": mejora,
            "periodo": periodo,
            "estacional": estacional,
            "acf": None if isinstance(rho, float) and math.isnan(rho) else rho,
            "tendencia": tendencia,
            "intermitente": intermitente,
            "clase_sbc": clase,
            "adi": adi,
            "cv2": cv2,
        }

    no_deep = "N-BEATS o DeepAR por SKU: con esta historia un modelo global, si hace falta, recién después de agotar los baselines."
    no_mape = "MAPE como métrica de decisión cuando hay ceros."

    if n == 0 or np.all(y == 0):
        return hoja(
            "L0", "Media histórica", "Naive (último valor)",
            "La serie no tiene demanda. No hay señal para extrapolar.",
            ["Croston", "Holt-Winters", no_mape],
            "Dejá el pronóstico en cero hasta que vuelva a haber venta.",
        )
    if n < 4:
        return hoja(
            "L1", "Naive (último valor)", "Media histórica",
            "Con menos de 4 puntos cualquier modelo con parámetros memoriza la muestra.",
            ["SARIMA", "Prophet", "Holt-Winters", no_deep],
            "Alargá la historia antes de cambiar de modelo. No imputes ceros para rellenar.",
        )
    if intermitente:
        if eventos < 2:
            return hoja(
                "L2a", "TSB", "Croston",
                "Hay muy pocos eventos. TSB y Croston son la familia correcta, con poca confianza.",
                ["Holt-Winters", "Prophet", no_mape],
                "Agregá el tiempo si el lead time lo permite y medí con WAPE, no con MAPE.",
            )
        if estacional and adi < 2 and periodo and n >= periodo and cv2_val < 0.49 and eventos >= 4:
            return hoja(
                "L2b", "Naive estacional", "Croston",
                "Hay un ciclo repetible y los tamaños no son erráticos.",
                ["Holt lineal", no_mape],
                "Repetí el último ciclo. Pasá a Croston si el naive estacional pierde el backtest.",
            )
        if adi >= 4 or (cv2_val >= 0.49 and h >= 6):
            return hoja(
                "L2d", "TSB", "Croston SBA",
                "La demanda aparece de vez en cuando. TSB actualiza la probabilidad también en los ceros.",
                ["Suavizado exponencial suave", "Prophet", "Holt-Winters", no_mape],
                "Reemplazá el pronóstico suave por TSB. Si la cola es una racha larga de ceros, el nivel tiene que caer.",
            )
        if cv2_val < 0.49:
            return hoja(
                "L2e", "Croston", "Croston SBA",
                "Demanda intermitente de tamaños estables: intervalo por tamaño.",
                ["Holt-Winters", "Media móvil", no_mape],
                "Cambiá a Croston. Si el sesgo de SBA es menor en el backtest, quedate con SBA.",
            )
        return hoja(
            "L2f", "Croston SBA", "TSB",
            "Demanda irregular. SBA corrige el sesgo positivo del Croston clásico.",
            ["Holt-Winters", "SARIMA por SKU", no_mape],
            "Usá Croston SBA y no le apliques otra corrección de sesgo encima.",
        )

    if estacional and periodo and n >= 2 * periodo:
        if cv2_val >= 0.49:
            return hoja(
                "L3a", "Naive estacional", "Media móvil",
                "Hay estacionalidad, pero los picos rompen un Holt-Winters.",
                ["Holt-Winters", "Un forecast plano", no_mape],
                "Repetí el último ciclo. No uses un pronóstico constante.",
            )
        if n >= 104 and tendencia:
            return hoja(
                "L3p", "Prophet (recomendado, no ajustado aquí)", "Holt-Winters aditivo",
                "Historia larga con tendencia y estación. El número que podés usar ya es Holt-Winters.",
                ["Naive de un solo periodo", no_deep],
                "Publicá Holt-Winters y pasá a Prophet solo si gana en WAPE, MASE y sesgo.",
            )
        if n >= max(36, 3 * periodo) and h <= 2 * periodo:
            return hoja(
                "L3s", "SARIMA (recomendado, no ajustado aquí)", "Holt-Winters aditivo",
                "Hay tres ciclos o más. SARIMA es el candidato; Holt-Winters es el número usable ahora.",
                ["Media histórica", no_deep],
                "Ajustá Holt-Winters y no reemplaces por SARIMA hasta ganar un rolling origin.",
            )
        if tendencia and h <= periodo:
            return hoja(
                "L3c", "Holt-Winters aditivo", "Naive estacional",
                "Tendencia y estación dentro de un ciclo, con al menos dos ciclos de historia.",
                ["Media histórica", "Croston"],
                "Reestimá con estacionalidad aditiva y truncá a cero.",
            )
        if tendencia:
            return hoja(
                "L3d", "Naive estacional", "Holt-Winters aditivo",
                "A más de un ciclo la pendiente se extrapola de más.",
                ["Holt lineal sin estación"],
                "Repetí el patrón estacional. No proyectes la tendencia más allá de un ciclo.",
            )
        if n >= 3 * periodo:
            return hoja(
                "L3e", "Holt-Winters aditivo", "Naive estacional",
                "Estacionalidad estable, sin una tendencia que domine.",
                ["Forecast plano", "Croston"],
                "Sumá la estacionalidad del periodo detectado.",
            )
        return hoja(
            "L3f", "Naive estacional", "Holt-Winters aditivo",
            "Dos ciclos alcanzan para repetir la estación y se quedan cortos para Holt-Winters.",
            ["SARIMA", "Prophet"],
            "Usá el naive estacional hasta cerrar el tercer ciclo.",
        )

    if tendencia:
        if n >= 10 and h <= 6 and cv2_val < 0.49:
            return hoja(
                "L4a", "Holt lineal", "Theta",
                "La pendiente local importa y la muestra ya da para un doble suavizado.",
                ["Media histórica", "Croston"],
                "Reestimá Holt. Si el sesgo crece con el horizonte, pasá a Theta.",
            )
        if n >= 10:
            return hoja(
                "L4b", "Theta", "Drift",
                "Theta frena la recta de Holt cuando el horizonte es largo o hay picos.",
                ["Holt-Winters sin estación clara"],
                "Reestimá Theta y revisá el sesgo multiplicativo.",
            )
        return hoja(
            "L4c", "Drift", "Naive (último valor)",
            "Hay pendiente y falta muestra para Holt o Theta.",
            ["SARIMA", "Prophet", no_deep],
            "Pronosticá con la recta entre el primer y el último punto.",
        )

    if estacional and periodo and periodo <= n < 2 * periodo:
        return hoja(
            "L5a", "Naive estacional", "Media histórica",
            "Se puede repetir el único ciclo observado. Todavía no Holt-Winters.",
            ["Holt-Winters", "SARIMA"],
            "Añadí esa estacionalidad. Con muchos SKU parecidos, el salto siguiente es un modelo global.",
        )
    if cv2_val >= 0.49 and h <= 6:
        return hoja(
            "L5b", "Media móvil", "Naive (último valor)",
            "Serie errática de nivel: la ventana reciente deja afuera los picos viejos.",
            ["Holt-Winters", no_mape],
            "Cambiá a media móvil. No uses MAPE para elegir.",
        )
    if cv2_val >= 0.49:
        return hoja(
            "L5c", "Media histórica", "Media móvil",
            "Sin estructura, a horizonte largo manda la media.",
            ["Naive del último pico"],
            "Reestimá hacia la media y corregí el sesgo.",
        )
    if h <= 3 and n >= 6:
        return hoja(
            "L5d", "Media móvil", "Media histórica",
            "Serie suave y horizonte corto: la ventana sigue un cambio de nivel reciente.",
            ["Croston", no_deep],
            "Reestimá la media móvil. Si el MASE empata a menos del 2%, dejá la media histórica.",
        )
    return hoja(
        "L5e", "Media histórica", "Media móvil",
        "El nivel es estable. No hace falta un modelo con más parámetros.",
        ["Deep learning por SKU", "Croston"],
        "Reestimá la media. Si en todo el catálogo el MASE no baja de 1, pensá en un modelo global.",
    )


def nota_portafolio(productos: list[dict]) -> str | None:
    modelos = {p.get("modelo_origen") for p in productos if p.get("modelo_origen")}
    clases = {}
    for p in productos:
        clase = p.get("clase_sbc")
        if clase in {"suave", "erratica", "intermitente", "lumpy"} and p.get("modelo_origen"):
            clases.setdefault(clase, 0)
            clases[clase] += 1
    if len(modelos) == 1 and len(clases) >= 2 and sum(clases.values()) >= 4:
        modelo = next(iter(modelos))
        return (
            f"El modelo {modelo} se usa en {len(clases)} clases de demanda distintas "
            f"({', '.join(f'{k}: {v}' for k, v in clases.items())}). "
            "Conviene un modelo por tipo de serie, no uno solo para todo el catálogo."
        )
    return None

