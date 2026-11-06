import type { ModelRec, SeriesProfile, Metrics } from "./types";

interface Cand {
  id: string;
  name: string;
  whenToUse: string;
  libraries: string;
  hyperparameters: string;
  dataNeeds: string;
  caveats: string;
  score: (p: SeriesProfile, m: Metrics) => number;
  why: (p: SeriesProfile, m: Metrics) => string;
}

const CANDIDATES: Cand[] = [
  {
    id: "naive",
    name: "Naive",
    whenToUse: "Piso de referencia y series muy cortas o casi random walk.",
    libraries: "statsmodels / forecast (R) / simple-statistics",
    hyperparameters: "Ninguno",
    dataNeeds: "1 período",
    caveats: "Ignora estacionalidad y promociones.",
    score: (p) => (p.n < 12 ? 70 : 25) + (p.cv > 1.2 ? 10 : 0),
    why: (p) => p.n < 12 ? "Historia corta: un naive es el baseline honesto." : "Útil solo como benchmark.",
  },
  {
    id: "snaive",
    name: "Seasonal naive",
    whenToUse: "Estacionalidad estable y pocos covariables.",
    libraries: "statsmodels.tsa / forecast::snaive",
    hyperparameters: "period = 7/12/52 según cadencia",
    dataNeeds: "≥ 2 ciclos",
    caveats: "No captura tendencia ni cambios de nivel.",
    score: (p) => (p.seasonalStrength > 0.3 && p.n >= p.seasonalPeriod * 2 ? 80 : 20),
    why: (p) => p.seasonalStrength > 0.3 ? "Hay estacionalidad clara; copiar el ciclo es un piso fuerte." : "Poca estacionalidad detectada.",
  },
  {
    id: "ses",
    name: "Suavizado exponencial simple (SES)",
    whenToUse: "Nivel estable, sin tendencia ni estación.",
    libraries: "statsmodels.tsa.holtwinters / forecast::ets",
    hyperparameters: "alpha ≈ 0.2–0.4, optimized",
    dataNeeds: "≥ 8 períodos",
    caveats: "Sesgado si hay tendencia.",
    score: (p) => (!p.hasTrend && p.seasonalStrength < 0.2 && p.intermittency === "smooth" ? 78 : 30),
    why: (p) => !p.hasTrend ? "Serie de nivel: SES suele ganar a modelos más pesados." : "Hay tendencia; SES se queda corto.",
  },
  {
    id: "holt",
    name: "Holt / Holt amortiguado",
    whenToUse: "Tendencia local, poca estación.",
    libraries: "statsmodels Holt / ets(trend='A', damped=True)",
    hyperparameters: "damped=True, alpha/beta optimizados",
    dataNeeds: "≥ 12 períodos",
    caveats: "Sin dampening explota a largo plazo.",
    score: (p) => (p.hasTrend && p.seasonalStrength < 0.25 ? 82 : 28) + (Math.abs(p.trendSlope) > 0 ? 5 : 0),
    why: (p) => p.hasTrend ? "Mann-Kendall marca tendencia: Holt amortiguado es el primer candidato." : "Sin tendencia significativa.",
  },
  {
    id: "hw",
    name: "Holt-Winters aditivo/multiplicativo",
    whenToUse: "Tendencia + estacionalidad en demanda regular.",
    libraries: "ExponentialSmoothing / forecast::hw",
    hyperparameters: "seasonal='add' si ceros, 'mul' si amplitud crece; period 12/52",
    dataNeeds: "≥ 2–3 ciclos",
    caveats: "Multiplicativo falla con ceros.",
    score: (p) =>
      (p.seasonalStrength > 0.25 && p.intermittency === "smooth" && p.n >= 24 ? 88 : 22) +
      (p.seasonalStrength > 0.4 ? 10 : 0),
    why: (p) => p.seasonalStrength > 0.25 ? "Estacionalidad + demanda suave: Holt-Winters es el trabajo estándar." : "Estación débil para HW.",
  },
  {
    id: "croston",
    name: "Croston",
    whenToUse: "Demanda intermitente (ADI > 1.32).",
    libraries: "statsforecast CrostonClassic / tsintermittent",
    hyperparameters: "alpha ≈ 0.1",
    dataNeeds: "≥ 16 períodos con algunos ceros",
    caveats: "Sesgo positivo; preferir SBA.",
    score: (p) => (p.intermittency === "intermittent" ? 86 : p.intermittency === "lumpy" ? 60 : 10),
    why: (p) => p.intermittency === "intermittent" ? `ADI=${p.adi.toFixed(2)}: Croston es el modelo clásico de recambios.` : "La serie no es intermitente.",
  },
  {
    id: "sba",
    name: "SBA (Syntetos-Boylan)",
    whenToUse: "Intermitente; corrige el sesgo de Croston.",
    libraries: "statsforecast CrostonSBA",
    hyperparameters: "alpha ≈ 0.1, corrección (1 − alpha/2)",
    dataNeeds: "≥ 16 períodos",
    caveats: "Aún débil si hay promociones.",
    score: (p) => (p.intermittency === "intermittent" ? 90 : p.intermittency === "lumpy" ? 70 : 8),
    why: (p) => p.intermittency === "intermittent" || p.intermittency === "lumpy" ? "SBA suele bajar el sesgo frente a Croston puro." : "No aplica.",
  },
  {
    id: "tsb",
    name: "TSB (Teunter-Syntetos-Babai)",
    whenToUse: "Intermitente con riesgo de obsolescencia.",
    libraries: "statsforecast TSB / tsintermittent",
    hyperparameters: "alpha_d, alpha_p ≈ 0.1",
    dataNeeds: "≥ 16 períodos",
    caveats: "Más inestable en series muy cortas.",
    score: (p) => (p.intermittency === "lumpy" ? 88 : p.intermittency === "intermittent" ? 80 : 8),
    why: (p) => p.intermittency === "lumpy" ? "Lumpy (ADI y CV² altos): TSB maneja mejor la probabilidad de demanda." : "Mejor otro modelo.",
  },
  {
    id: "theta",
    name: "Theta",
    whenToUse: "Baseline M3/M4, series mensuales suaves.",
    libraries: "statsforecast Theta / forecast",
    hyperparameters: "theta=2 (clásico)",
    dataNeeds: "≥ 24 períodos",
    caveats: "Estacionalidad se desestacionaliza aparte.",
    score: (p) => (p.intermittency === "smooth" && p.n >= 24 ? 72 : 25),
    why: (p) => p.intermittency === "smooth" ? "Buen compromiso sesgo-varianza como benchmark." : "Poco adecuado a ceros.",
  },
  {
    id: "sarima",
    name: "AutoARIMA / SARIMA",
    whenToUse: "Autocorrelación lineal, cadencia regular, pocos ceros.",
    libraries: "pmdarima / statsforecast AutoARIMA / forecast::auto.arima",
    hyperparameters: "stepwise, seasonal=True, max_p=3, max_q=3, D≤1",
    dataNeeds: "≥ 2 ciclos; sin huecos",
    caveats: "Frágil con promociones y huecos.",
    score: (p) => (p.intermittency === "smooth" && p.n >= 30 && !p.promotionsLikely ? 84 : 24),
    why: (p) => p.intermittency === "smooth" ? "Serie regular: AutoARIMA captura ACF residual que ETS deja." : "Ceros/picos rompen ARIMA.",
  },
  {
    id: "prophet",
    name: "Prophet",
    whenToUse: "Diario/semanal con feriados, quiebres y múltiples estacionalidades.",
    libraries: "prophet / cmdstanr",
    hyperparameters: "changepoint_prior_scale 0.05–0.5, holidays locales",
    dataNeeds: "≥ 6–12 meses",
    caveats: "Pesado; sobreajusta series cortas o intermitentes.",
    score: (p) => (p.cadence !== "month" && p.n >= 40 && p.seasonalStrength > 0.2 && p.intermittency === "smooth" ? 76 : 18),
    why: (p) => p.n >= 40 ? "Calendario y posibles quiebres: Prophet es práctico para el planner." : "Historia corta para Prophet.",
  },
  {
    id: "tbats",
    name: "TBATS",
    whenToUse: "Estacionalidades múltiples (7 y 365, o 13 y 52).",
    libraries: "tbats / forecast::tbats",
    hyperparameters: "use_box_cox=True, seasonal_periods=[7,365] o [13,52]",
    dataNeeds: "≥ 2 ciclos del período largo",
    caveats: "Lento; caja negra para el negocio.",
    score: (p) => (p.seasonalStrength > 0.4 && p.n >= 52 ? 74 : 16),
    why: (p) => p.seasonalStrength > 0.4 ? "Estación fuerte: TBATS modela períodos múltiples sin dummies." : "No justifica el costo.",
  },
  {
    id: "lgbm",
    name: "LightGBM / XGBoost con lags",
    whenToUse: "Muchos SKUs, promociones, precio, stock y calendario.",
    libraries: "lightgbm + mlforecast / skforecast",
    hyperparameters: "lags 1,2,7,12,52; rolling mean 4/13; num_leaves 31; min_data_in_leaf 20",
    dataNeeds: "Panel ≥ 50 series o un SKU con covariables y ≥ 40 puntos",
    caveats: "Hay que evitar leakage y alinear el origin.",
    score: (p) => {
      let s = (p.promotionsLikely || p.cv > 0.8 ? 85 : 40) + (p.n >= 40 ? 8 : -15);
      if (p.intermittency === "intermittent" || p.intermittency === "lumpy") s -= 45;
      return s;
    },
    why: (p) => p.promotionsLikely ? "Picos tipo promo: un árbol con features gana a ETS." : "Candidato de panel si hay más SKUs similares.",
  },
  {
    id: "nbeats",
    name: "N-BEATS / NHITS",
    whenToUse: "Paneles grandes, sin covariables ricas.",
    libraries: "neuralforecast / gluonts / darts",
    hyperparameters: "input_size 2–3 ciclos, n_blocks 3, dropout 0.1",
    dataNeeds: "Cientos de series o una muy larga",
    caveats: "Overkill y opaco para un SKU aislado.",
    score: (p) => (p.n >= 80 && p.intermittency === "smooth" ? 60 : 12),
    why: (p) => p.n >= 80 ? "Historia larga: útil si entrenás un panel." : "No hay datos para deep learning.",
  },
  {
    id: "deepar",
    name: "DeepAR (probabilístico)",
    whenToUse: "Cuantiles para stock de seguridad en panel.",
    libraries: "gluonts DeepAR / amazon-forecast",
    hyperparameters: "context_length = horizonte×4, num_layers=2",
    dataNeeds: "Panel amplio; demanda positiva o zero-inflated",
    caveats: "Caro de tunear; no para 1 producto.",
    score: (p) => (p.n >= 60 ? 50 : 10),
    why: () => "Solo si necesitás P50/P90 a escala y tenés GPU/panel.",
  },
  {
    id: "analog",
    name: "Análogos (producto nuevo)",
    whenToUse: "Lanzamientos con <16 períodos.",
    libraries: "Clustering de curvas + SES; nixts / custom",
    hyperparameters: "k=5 análogos, mix 70% analogía / 30% historia propia",
    dataNeeds: "Catálogo con atributos (categoría, precio, canal)",
    caveats: "Depende de un buen maestro de producto.",
    score: (p) => (p.isNewProduct ? 92 : 5),
    why: (p) => p.isNewProduct ? `Solo ${p.n} puntos: analogía + prior es más seguro que ARIMA.` : "Ya hay historia propia.",
  },
  {
    id: "mint",
    name: "Jerárquico MinT / bottom-up",
    whenToUse: "SKU × depósito × canal que deben cuadrar.",
    libraries: "scikit-hts / hierarchicalforecast MinT",
    hyperparameters: "method=MinT-shrink, bottom-up si ruido alto en la base",
    dataNeeds: "Jerarquía coherente y forecasts base",
    caveats: "Basura en la base se propaga; limpiar primero.",
    score: (p) => (p.n >= 20 ? 35 : 10),
    why: () => "Aplicar después de limpiar cada hoja; no reemplaza el modelo base.",
  },
  {
    id: "ma",
    name: "Media móvil",
    whenToUse: "Comunicación simple a operaciones, nivel estable.",
    libraries: "pandas rolling / Excel",
    hyperparameters: "ventana 4 o 13 semanas",
    dataNeeds: "≥ ventana",
    caveats: "Atrasa picos y cambios de nivel.",
    score: (p) => (!p.hasTrend && p.seasonalStrength < 0.15 && p.intermittency === "smooth" ? 55 : 15),
    why: (p) => !p.hasTrend ? "Puede servir como control gerencial, no como forecast líder." : "La tendencia lo deja atrás.",
  },
];

export function recommendModels(profile: SeriesProfile, metrics: Metrics): ModelRec[] {
  const recs = CANDIDATES.map((c) => {
    const score = Math.max(0, Math.min(100, Math.round(c.score(profile, metrics))));
    return {
      id: c.id,
      name: c.name,
      score,
      whenToUse: c.whenToUse,
      whyThisProduct: c.why(profile, metrics),
      libraries: c.libraries,
      hyperparameters: c.hyperparameters,
      dataNeeds: c.dataNeeds,
      caveats: c.caveats,
    };
  });
  recs.sort((a, b) => b.score - a.score);
  return recs.slice(0, 6);
}

export const EVAL_PROTOCOL = {
  primary: "WAPE (pondera SKUs grandes) + bias % + MASE",
  split: "Origen rodante (rolling origin), horizonte = ciclo de reposición (p.ej. 4–8 semanas)",
  folds: "Mínimo 4 orígenes; no un único train/test aleatorio",
  secondary: "sMAPE para series chicas, RMSSE vs seasonal naive, hit rate ±20%, cobertura P80 si hay intervalos",
  note: "Nunca tunear con el mismo tramo que se reporta al negocio.",
};
