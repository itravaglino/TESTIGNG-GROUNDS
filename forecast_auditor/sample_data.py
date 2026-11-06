"""Forecast de demostración con productos buenos, corregibles y descartables."""

from __future__ import annotations

import numpy as np
import pandas as pd


def demo_frame() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    weeks = pd.date_range("2024-11-04", periods=104, freq="W-MON")
    rows: list[dict] = []

    def add(product, dates, forecast, actual, model, lower=None, upper=None):
        for i, date in enumerate(dates):
            row = {
                "producto": product,
                "fecha": pd.Timestamp(date).date().isoformat(),
                "pronostico": None if forecast[i] is None or (isinstance(forecast[i], float) and np.isnan(forecast[i])) else round(float(forecast[i]), 2),
                "real": None if actual is None or actual[i] is None or (isinstance(actual[i], float) and np.isnan(actual[i])) else round(float(actual[i]), 2),
                "modelo": model,
            }
            if lower is not None:
                row["limite_inf"] = round(float(lower[i]), 2)
            if upper is not None:
                row["limite_sup"] = round(float(upper[i]), 2)
            rows.append(row)

    t = np.arange(104)
    leche = 820 + 0.4 * t + rng.normal(0, 12, 104)
    leche_fc = leche * 1.02 + rng.normal(0, 8, 104)
    add("Leche entera 1L", weeks, leche_fc, leche, "SES", leche_fc * 0.9, leche_fc * 1.1)

    yerba = 500 + rng.normal(0, 8, 104)
    add("Yerba 1kg", weeks, yerba * 1.40 + rng.normal(0, 15, 104), yerba, "Holt")

    aceite = 200 + 0.15 * t + rng.normal(0, 6, 104)
    aceite_fc = (t * 37 % 1700) + 40
    add("Aceite girasol 900ml", weeks, aceite_fc, aceite, "Manual")

    arroz = np.zeros(104)
    eventos = np.array(sorted(rng.choice(np.arange(8, 96), size=22, replace=False)))
    arroz[eventos] = 80 + rng.normal(0, 4, eventos.size)
    # Error típico: un ETS continuo pronostica el tamaño del pedido todas las semanas.
    add("Arroz 1kg", weeks, np.full(104, 80.0), arroz, "ETS")

    pan = 300 + rng.normal(0, 8, 104)
    pan_fc = pan * 1.03
    for index in (8, 24, 40, 61, 77, 90):
        pan_fc[index] = -40
    for index in (15, 48, 88):
        pan_fc[index] = 5000
    add("Pan lactal", weeks, pan_fc, pan, "SES")

    fideos_actual = 150 + rng.normal(0, 5, 104)
    fideos_fc = fideos_actual * 1.04
    keep = np.ones(104, dtype=bool)
    keep[[5, 6, 18, 19, 44, 60, 61, 80]] = False
    add("Fideos 500g", weeks[keep], fideos_fc[keep], fideos_actual[keep], "SES")

    azucar = np.clip(100 + 100 * np.sin(2 * np.pi * t / 52) + rng.normal(0, 4, 104), 0, None)
    add("Azúcar 1kg", weeks, np.full(104, 100.0), azucar, "Media")

    cafe_dates = weeks[:6]
    cafe = np.array([40, 42, 39, 41, 44, 43], dtype=float)
    add("Café molido 250g", cafe_dates, cafe * 1.05, cafe, "")

    gaseosa = 600 + rng.normal(0, 10, 96)
    future_dates = weeks[96:]
    hist_dates = weeks[:96]
    add("Gaseosa 2.25L", hist_dates, gaseosa * 1.02, gaseosa, "Holt")
    add("Gaseosa 2.25L", future_dates, np.full(8, 4800.0), np.full(8, np.nan), "Holt")

    agua = 250 + 0.2 * t[:60] + rng.normal(0, 4, 60)
    add("Agua sin gas 2L", weeks[:60], agua, None, "")

    sal_fc = np.array([-80, 20, -40, 30, -200, 10, -15, 25, -90, 5] * 2, dtype=float)
    add("Sal fina 500g", weeks[:20], sal_fc, None, "Manual")

    harina = 90 + rng.normal(0, 3, 40)
    harina_fc = np.full(40, np.nan)
    harina_fc[:6] = harina[:6]
    add("Harina 000 1kg", weeks[:40], harina_fc, harina, "SES")

    miel_idx = np.unique(np.concatenate([np.array([0, 103]), rng.choice(np.arange(1, 103), size=28, replace=False)]))
    miel_actual = 30 + rng.normal(0, 2, miel_idx.size)
    add("Miel 500g", weeks[miel_idx], miel_actual * 1.1, miel_actual, "SES")

    return pd.DataFrame(rows)


def demo_csv() -> str:
    return demo_frame().to_csv(index=False)
