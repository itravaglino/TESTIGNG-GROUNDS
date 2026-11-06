import type { ModelRec, SeriesFeatures } from "./types";

export function recommendModels(features: SeriesFeatures, flags: { id: string }[]): { primary: ModelRec; challengers: ModelRec[] } {
  const recs: ModelRec[] = [];

  if (features.n < 3) {
    recs.push({
      id: "analog",
      name: "Análogo de producto nuevo",
      reason: "Sin ventas suficientes no hay modelo: copie un lanzamiento parecido y ajústelo a tiendas y precio.",
      fallback: "Tasa de la familia × distribución esperada",
      ensemble: false,
    });
    return pack(recs);
  }

  if (flags.some((f) => f.id === "DISC_01")) {
    recs.push({
      id: "zero",
      name: "No pronosticar (descontinuado)",
      reason: "Descatalogada: la previsión de reposición es 0. La última compra es otra decisión.",
      ensemble: false,
    });
    return pack(recs);
  }

  if (features.nPos <= 1) {
    recs.push({
      id: "naive",
      name: "Ingenuo (último valor)",
      reason: "Con un solo dato, ese dato manda. Pregunte si fue promo, rotura o carga inicial.",
      fallback: "Media móvil de 3 si hay tres puntos",
      ensemble: false,
    });
    return pack(recs);
  }

  if ((features.demandClass === "intermittent" || features.demandClass === "lumpy") && features.nPos < 5) {
    recs.push({
      id: "pz",
      name: "Probabilidad × tamaño medio",
      reason: "Menos de cinco pedidos no dan para Croston. Use probabilidad por tamaño medio y revíselo a mano.",
      ensemble: false,
    });
    return pack(recs);
  }

  if (features.demandClass === "lumpy") {
    recs.push({
      id: "sba",
      name: "SBA (Croston corregido)",
      reason: "Pedido gordo y esporádico: no suba el punto de previsión al último pedido. El colchón va en stock de seguridad.",
      fallback: "TSB si la referencia se está apagando",
      ensemble: false,
    });
    recs.push({
      id: "tsb",
      name: "TSB",
      reason: "Actualiza la probabilidad de demanda en cada periodo, incluso en ceros, y puede dejar morir el SKU.",
      ensemble: false,
    });
    return pack(recs);
  }

  if (features.demandClass === "intermittent") {
    recs.push({
      id: "sba",
      name: "SBA (Croston corregido)",
      reason: "Si el mes casi siempre es cero, no use Holt ni ARIMA. Agrupe el tiempo o use un modelo intermitente.",
      fallback: "TSB si los ceros se alargan",
      ensemble: false,
    });
    recs.push({
      id: "tsb",
      name: "TSB",
      reason: "Útil cuando la ocurrencia está cayendo.",
      ensemble: false,
    });
    recs.push({
      id: "croston",
      name: "Croston clásico (solo referencia)",
      reason: "Croston clásico sobrestima. Queda como baseline, no como publicación.",
      ensemble: false,
    });
    return pack(recs);
  }

  if (features.demandClass === "erratic") {
    recs.push({
      id: "ses",
      name: "Suavizado exponencial simple",
      reason: "Vende casi siempre, pero a saltos. Quite los picos de promo antes de alisar.",
      fallback: "Media móvil de 3 o 6",
      ensemble: false,
    });
    recs.push({
      id: "ma",
      name: "Media móvil",
      reason: "Fallback corto si hay poca historia.",
      ensemble: false,
    });
    return pack(recs);
  }

  if (features.seasonal && features.n >= 24) {
    recs.push({
      id: "holt_winters",
      name: "Holt-Winters (amortiguado si hay tendencia)",
      reason: features.trend
        ? "Hay estacionalidad y además sube. Freno de tendencia: después de temporada el modelo no puede seguir escalando."
        : "Con dos temporadas parecidas, el mismo mes del año pasado es el rival a batir.",
      fallback: "Ingenuo estacional",
      ensemble: true,
    });
    recs.push({
      id: "seasonal_naive",
      name: "Ingenuo estacional",
      reason: "Siempre se calcula. Si gana el backtest, no publique un modelo más rico.",
      ensemble: true,
    });
    recs.push({
      id: "theta",
      name: "Theta",
      reason: "Candidato mensual sólido junto a ETS amortiguado.",
      ensemble: true,
    });
    recs.push({
      id: "stl_ets",
      name: "STL robusto + ETS",
      reason: "Si un pico de promo deforma la estacionalidad, limpie con descomposición robusta y pronostique encima.",
      ensemble: false,
    });
    return pack(recs);
  }

  if (features.trend && features.n >= 10) {
    recs.push({
      id: "damped_holt",
      name: "Holt amortiguado",
      reason: "Una rampa de alta no es una tendencia eterna. Sin más puntos de venta, frene.",
      fallback: "SES si hay menos de 18 periodos",
      ensemble: false,
    });
    recs.push({
      id: "holt",
      name: "Holt lineal (solo con causa estructural)",
      reason: "Sin amortiguar solo si hay listing o distribución nueva confirmada.",
      ensemble: false,
    });
    return pack(recs);
  }

  recs.push({
    id: "ses",
    name: "Suavizado exponencial simple",
    reason: "Referencia estable: alisado simple. No cambie de modelo porque un mes se movió.",
    fallback: "Media móvil si hay menos de 8 periodos",
    ensemble: false,
  });
  recs.push({
    id: "naive",
    name: "Ingenuo",
    reason: "Benchmark obligatorio de un paso.",
    ensemble: false,
  });
  if (features.n >= 24 && (features.zerosShare ?? 1) < 0.25) {
    recs.push({
      id: "arima",
      name: "Auto ARIMA (retador)",
      reason: "Solo con histórico largo y demanda continua. Con pocos meses se ajusta al ruido.",
      ensemble: false,
    });
  }
  recs.push({
    id: "lightgbm",
    name: "Modelo global (LightGBM) si hay panel",
    reason: "Ayuda en la cola larga y en altas. En las referencias A, que se gane el puesto contra el modelo local.",
    ensemble: false,
  });
  return pack(recs);
}

function pack(recs: ModelRec[]): { primary: ModelRec; challengers: ModelRec[] } {
  return { primary: recs[0], challengers: recs.slice(1, 4) };
}
