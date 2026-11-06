"""Catálogo de modelos y elección según el patrón de cada producto."""

from __future__ import annotations

from typing import Any

CATALOG: list[dict[str, str]] = [
    {
        "id": "seasonal_naive",
        "nombre": "Naive estacional",
        "familia": "Base",
        "cuando": "Hay estacionalidad clara y todavía poca historia para un modelo más rico.",
        "necesita": "Dos ciclos completos (104 semanas o 24 meses).",
        "evitar": "Demanda intermitente o serie que cambió de régimen.",
    },
    {
        "id": "ses",
        "nombre": "Suavizado exponencial simple (SES)",
        "familia": "Estadístico",
        "cuando": "Demanda suave, sin tendencia ni estacionalidad.",
        "necesita": "Unos 12 períodos.",
        "evitar": "Ceros frecuentes, tendencia o estacionalidad.",
    },
    {
        "id": "holt",
        "nombre": "Holt amortiguado",
        "familia": "Estadístico",
        "cuando": "Hay tendencia y no conviene proyectarla para siempre.",
        "necesita": "Unos 16 períodos.",
        "evitar": "Intermitencia y estacionalidad fuerte sin un componente estacional.",
    },
    {
        "id": "holt_winters",
        "nombre": "Holt-Winters",
        "familia": "Estadístico",
        "cuando": "Demanda suave o errática con estacionalidad estable.",
        "necesita": "Al menos dos ciclos, mejor tres.",
        "evitar": "Muchos ceros. Ahí la estacionalidad aditiva se inventa negativos o nivel falso.",
    },
    {
        "id": "sarima",
        "nombre": "SARIMA",
        "familia": "Estadístico",
        "cuando": "Estacionalidad y autocorrelación, con historia larga y pocos quiebres.",
        "necesita": "36 meses o 156 semanas, y alguien que revise los residuos.",
        "evitar": "Catálogos enormes donde no se puede mirar modelo por modelo.",
    },
    {
        "id": "theta",
        "nombre": "Theta",
        "familia": "Estadístico",
        "cuando": "Serie continua, con o sin tendencia, cuando se busca un método simple que compita bien.",
        "necesita": "Unos 24 períodos.",
        "evitar": "Intermitencia.",
    },
    {
        "id": "prophet",
        "nombre": "Prophet",
        "familia": "Estadístico",
        "cuando": "Estacionalidad semanal y anual, feriados y algún quiebre de nivel.",
        "necesita": "Historia diaria o semanal de dos años o más.",
        "evitar": "Series cortas, intermitentes o catálogos donde el costo de ajustar uno por uno no cierra.",
    },
    {
        "id": "croston",
        "nombre": "Croston",
        "familia": "Intermitente",
        "cuando": "La demanda aparece de tanto en tanto y el tamaño de cada pedido es parecido.",
        "necesita": "Suficientes eventos de demanda, no solo ceros.",
        "evitar": "Demanda suave: Croston aplana de más una serie continua.",
    },
    {
        "id": "sba",
        "nombre": "SBA (Syntetos-Boylan)",
        "familia": "Intermitente",
        "cuando": "Intermitente y el Croston clásico está sesgado hacia arriba.",
        "necesita": "Los mismos eventos que Croston.",
        "evitar": "Demanda que dejó de ser esporádica.",
    },
    {
        "id": "tsb",
        "nombre": "TSB",
        "familia": "Intermitente",
        "cuando": "Puede haber obsolescencia: la chance de demanda tiene que poder caer a cero.",
        "necesita": "Historia con rachas de ceros, no un único hueco.",
        "evitar": "Suave de alto volumen.",
    },
    {
        "id": "adida",
        "nombre": "ADIDA",
        "familia": "Intermitente",
        "cuando": "Demanda irregular, con picos grandes separados. Se agrega en el tiempo, se pronostica y se reparte.",
        "necesita": "Elegir un balde temporal (4 u 8 semanas) con varios eventos adentro.",
        "evitar": "Cuando se necesita el timing fino de cada semana y hay poca demanda.",
    },
    {
        "id": "lightgbm",
        "nombre": "LightGBM con rezagos y calendario",
        "familia": "Machine learning",
        "cuando": "Demanda errática y muchas series que comparten precio, promo, clima o categoría.",
        "necesita": "Decenas de períodos por producto y variables externas limpias. Entrenar global, no un modelo por SKU corto.",
        "evitar": "Un solo producto corto, intermitencia pura o features que no se conocen a futuro.",
    },
    {
        "id": "moving_average",
        "nombre": "Media móvil o naive",
        "familia": "Base",
        "cuando": "Producto nuevo o historia de menos de 8 períodos.",
        "necesita": "Casi nada. Sirve para no inventar un modelo.",
        "evitar": "Dejarlo como modelo definitivo cuando ya hay dos ciclos de historia.",
    },
]


def _entry(model_id: str) -> dict[str, str]:
    for item in CATALOG:
        if item["id"] == model_id:
            return item
    raise KeyError(model_id)


def recommend_models(diag: dict[str, Any], n_actual: int, current_model: str) -> list[dict[str, Any]]:
    clase = diag["demanda"]["clase"]
    seasonal = bool(diag["hay_estacionalidad"])
    trend = bool(diag["tendencia"]["hay_tendencia"])
    freq = diag["frecuencia"]["codigo"]
    ranked: list[tuple[str, str]] = []

    if clase == "sin_demanda":
        ranked.append(("moving_average", "No hay eventos de demanda. No estimés Croston: no hay tamaño de pedido ni intervalo."))
        ranked.append(("ses", "Recién cuando aparezcan ventas repetidas vale la pena un suavizado."))
    elif n_actual < 8 and clase in {"intermitente", "irregular"}:
        ranked.append(("tsb", "Aunque la historia es corta, la serie ya muestra ceros. TSB no pronostica todas las semanas."))
        ranked.append(("croston", "Croston da una tasa simple mientras juntás más eventos."))
        ranked.append(("moving_average", "Con pocos eventos, cualquier modelo grande se aprende el ruido."))
    elif n_actual < 8:
        ranked.append(("moving_average", "Con tan poca historia un modelo más grande se aprende el ruido."))
        ranked.append(("ses", "Cuando llegues a 12 períodos, SES es el siguiente paso si la serie sigue continua."))
    elif clase in {"intermitente", "irregular"}:
        ranked.append(("tsb", "La probabilidad de demanda se actualiza también en los ceros, así que puede apagarse si el producto se frena."))
        if clase == "irregular":
            ranked.append(("adida", "Los picos irregulares se pronostican mejor agregando varias semanas."))
        ranked.append(("sba", "Corrige el sesgo hacia arriba típico de Croston."))
        ranked.append(("croston", "Sirve como referencia simple de tasa de demanda."))
    elif seasonal and clase in {"suave", "erratica"}:
        ranked.append(("holt_winters", "La estacionalidad que mide la serie pide un componente estacional explícito."))
        if n_actual >= int(diag["frecuencia"]["periodo"]) * 3 and freq in {"M", "W", "D"}:
            ranked.append(("sarima", "Hay historia suficiente para un estacional más estricto, si alguien revisa los residuos."))
        if freq in {"W", "D"} and n_actual >= 104:
            ranked.append(("prophet", "La frecuencia y el largo alcanzan para estacionalidad anual y feriados."))
        ranked.append(("seasonal_naive", "Es el piso: cualquier modelo elegido tiene que ganarle en un tramo que no usó para ajustarse."))
        if clase == "erratica":
            ranked.append(("lightgbm", "La parte errática puede venir de promo o precio. Esas variables no están en un Holt-Winters."))
    elif trend and clase == "suave":
        ranked.append(("holt", "Hay tendencia. Holt amortiguado la acompaña sin proyectarla de forma eterna."))
        ranked.append(("theta", "Theta compite bien en series continuas con tendencia y es fácil de operar."))
        ranked.append(("ses", "Dejalo como control: si Holt no le gana a SES en validación, la tendencia no es usable."))
    elif clase == "erratica":
        ranked.append(("lightgbm", "La variación no parece un ciclo limpio. Un modelo global con rezagos y drivers suele rendir más."))
        ranked.append(("theta", "Theta es un buen rival estadístico antes de pasar a un modelo con variables externas."))
        ranked.append(("ses", "Si LightGBM no le gana a SES en validación, la complejidad no se paga."))
    else:
        ranked.append(("ses", "La demanda es continua y sin un ciclo o una tendencia que justifique otra cosa."))
        ranked.append(("theta", "Theta es el candidato siguiente si SES se queda corto."))
        ranked.append(("moving_average", "La media móvil corta sirve de alarma: si SES no la supera, el modelo está de más."))

    if seasonal and clase in {"intermitente", "irregular"}:
        ranked.append(("adida", "Si los eventos se concentran en una época del año, agregá a esa estación antes de usar Croston plano."))

    # Únicos, en orden, máximo 3 recomendaciones principales más el contexto del modelo actual.
    seen: set[str] = set()
    picked: list[dict[str, Any]] = []
    for model_id, why in ranked:
        if model_id in seen:
            continue
        seen.add(model_id)
        item = dict(_entry(model_id))
        item["por_que"] = why
        item["prioridad"] = len(picked) + 1
        picked.append(item)
        if len(picked) == 3:
            break

    current = (current_model or "").strip().lower()
    note = None
    if current:
        mismatch = _current_mismatches(current, clase, seasonal, n_actual)
        if mismatch:
            note = mismatch
    return picked, note


def _current_mismatches(current: str, clase: str, seasonal: bool, n_actual: int) -> str | None:
    intermittent_ok = ("croston", "sba", "tsb", "adida", "intermit")
    seasonal_ok = ("holt-winter", "holt winter", "winter", "sarima", "prophet", "estacional", "seasonal")
    ml_ok = ("lightgbm", "lgbm", "xgboost", "catboost", "random forest", "ml")
    if clase in {"intermitente", "irregular"} and not any(token in current for token in intermittent_ok):
        return (
            f"El modelo declarado ({current}) no es de la familia intermitente. "
            "En esta demanda suele sobrepronosticar los períodos en cero."
        )
    if seasonal and clase in {"suave", "erratica"} and n_actual >= 24:
        if not any(token in current for token in seasonal_ok + ml_ok + ("theta", "ets")):
            if "naive" in current and "estacional" not in current and "season" not in current:
                return f"El modelo declarado ({current}) no tiene componente estacional y la demanda sí."
            if any(token in current for token in ("ses", "media", "promedio", "holt")) and "winter" not in current:
                return f"El modelo declarado ({current}) no explica la estacionalidad que se ve en el histórico."
    if n_actual < 8 and any(token in current for token in ("lightgbm", "prophet", "sarima", "xgboost", "red neuronal", "lstm")):
        return f"El modelo declarado ({current}) pide más historia de la que tiene este producto."
    if clase in {"suave", "erratica"} and any(token in current for token in ("croston", "sba", "tsb", "adida")):
        return (
            f"El modelo declarado ({current}) es de demanda intermitente, y esta serie es continua. "
            "Va a aplanar de más."
        )
    return None
