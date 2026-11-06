import type {
  AccuracyMetrics,
  ForecastIssue,
  ImprovementAction,
  ModelSuggestion,
  SeriesProfile,
} from "./types";

interface Signals {
  demand: SeriesProfile["demandClass"];
  trend: SeriesProfile["trend"];
  n: number;
  seasonal: number;
  hierarchical: boolean;
  freq: SeriesProfile["frequency"];
  intermittent: boolean;
  short: boolean;
  highError: boolean;
}

function clip(n: number): number {
  return Math.max(0, Math.min(100, Math.round(n)));
}

const LIB = {
  stats: ["statsmodels", "sktime"],
  nixtla: ["statsforecast", "nixtla"],
  prophet: ["prophet", "neuralprophet"],
  gbdt: ["lightgbm", "xgboost", "mlforecast"],
  dl: ["darts", "pytorch-forecasting", "neuralforecast"],
  fm: ["chronos", "timesfm", "uni2ts"],
};

export function recommendModels(profile: SeriesProfile, metrics: AccuracyMetrics): ModelSuggestion[] {
  const s: Signals = {
    demand: profile.demandClass,
    trend: profile.trend,
    n: profile.n,
    seasonal: profile.seasonalStrength ?? 0,
    hierarchical: profile.locations.length + profile.channels.length > 2,
    freq: profile.frequency,
    intermittent: profile.demandClass === "intermittent" || profile.demandClass === "lumpy",
    short: profile.n < 16,
    highError: (metrics.wape ?? 0) > 30 || (metrics.mase ?? 0) > 1.2,
  };

  const catalog: ModelSuggestion[] = [
    {
      id: "naive",
      name: "Naive / naive estacional",
      score: clip(s.short ? 88 : 35 + (s.highError ? 10 : 0)),
      why: s.short
        ? "Con poca historia, repetir el último valor o el del mismo periodo del año anterior es el baseline más honesto."
        : "Sirve como piso. Si su modelo no le gana al naive (MASE < 1), no lo ponga en producción.",
      libraries: ["statsmodels", "sktime", "statsforecast"],
      whenToUse: "Series cortas, baseline y auditoría de valor añadido.",
      caveats: "No captura nivel cambiante ni promociones.",
    },
    {
      id: "ses",
      name: "Suavizamiento exponencial simple (SES)",
      score: clip(s.demand === "smooth" && s.trend === "flat" ? 82 : 40),
      why: "Estable cuando el nivel es localmente constante y no hay estacionalidad fuerte.",
      libraries: LIB.stats,
      whenToUse: "Demanda suave, sin tendencia ni estación.",
      caveats: "Falla si hay tendencia o muchos ceros.",
    },
    {
      id: "holt",
      name: "Holt / Holt amortiguado",
      score: clip(s.trend === "up" || s.trend === "down" ? 80 : s.trend === "explosive" ? 25 : 45),
      why:
        s.trend === "explosive"
          ? "La tendencia actual es explosiva: Holt lineal la va a empeorar. Use la versión amortiguada o un techo."
          : "Modela nivel y tendencia con dos ecuaciones simples.",
      libraries: LIB.stats.concat(LIB.nixtla),
      whenToUse: "Tendencia clara, poca estacionalidad.",
      caveats: "Sin amortiguar, explota a horizonte largo.",
    },
    {
      id: "holt_winters",
      name: "Holt-Winters (aditivo/multiplicativo)",
      score: clip(s.seasonal > 0.3 && !s.intermittent ? 90 : 38),
      why: "Es el primer modelo a probar en retail semanal/mensual con estación y demanda continua.",
      libraries: LIB.stats.concat(["darts"]),
      whenToUse: "Estacionalidad semanal o anual y demanda suave.",
      caveats: "Necesita al menos dos ciclos. No sirve con intermitencia.",
    },
    {
      id: "ets",
      name: "ETS (Hyndman)",
      score: clip(!s.intermittent && s.n >= 24 ? 86 : 42),
      why: "Selecciona automáticamente error/tendencia/estación. Suele ser el default robusto univariado.",
      libraries: LIB.nixtla.concat(["forecast (R)", "sktime"]),
      whenToUse: "Cuando no quiere elegir a mano entre SES, Holt y Winters.",
      caveats: "Menos flexible con regresores de promo.",
    },
    {
      id: "croston",
      name: "Croston",
      score: clip(s.intermittent ? 92 : 20),
      why: "Separa tamaño de demanda e intervalo entre ventas. Es el estándar para SKU con muchos ceros.",
      libraries: LIB.nixtla.concat(["croston", "sktime"]),
      whenToUse: "Clase intermitente (ADI ≥ 1.32).",
      caveats: "Sesga un poco hacia arriba; TSB suele corregirlo.",
    },
    {
      id: "tsb",
      name: "Teunter-Syntetos-Babai (TSB)",
      score: clip(s.demand === "lumpy" || s.intermittent ? 88 : 18),
      why: "Mejora Croston cuando hay rachas de ceros y el ítem puede estar muriendo o naciendo.",
      libraries: ["statsforecast", "sktime"],
      whenToUse: "Intermitente o lumpy, catálogo con alta mortalidad.",
      caveats: "Sigue siendo univariado: no ve precio ni quiebres.",
    },
    {
      id: "sba",
      name: "Syntetos-Boylan Approximation",
      score: clip(s.intermittent ? 84 : 16),
      why: "Corrección de sesgo de Croston, útil para stock de seguridad.",
      libraries: ["statsforecast"],
      whenToUse: "Intermitente con objetivo de inventario.",
      caveats: "No modela estacionalidad explícita.",
    },
    {
      id: "arima",
      name: "ARIMA / SARIMA",
      score: clip(!s.intermittent && s.n >= 30 ? 78 : 34),
      why: "Bueno cuando hay autocorrelación persistente y se puede identificar p,d,q.",
      libraries: LIB.stats.concat(LIB.nixtla),
      whenToUse: "Series densas, diagnósticos clásicos, horizonte corto/medio.",
      caveats: "AutoARIMA se vuelve frágil con cambios de régimen.",
    },
    {
      id: "tbats",
      name: "TBATS",
      score: clip(s.freq === "daily" && s.seasonal > 0.25 ? 80 : 36),
      why: "Varias estacionalidades a la vez (semana + año) sin dummy explosion.",
      libraries: ["tbats", "sktime", "darts"],
      whenToUse: "Diario con patrón semanal y anual.",
      caveats: "Lento y opaco. Exceso para pocas observaciones.",
    },
    {
      id: "theta",
      name: "Theta / Dynamic Optimized Theta",
      score: clip(!s.intermittent && s.n >= 16 ? 74 : 40),
      why: "Ganador histórico de M3: simple, difícil de romper.",
      libraries: LIB.nixtla,
      whenToUse: "Baseline fuerte antes de subir a boosting o deep learning.",
      caveats: "Poca capacidad para regresores.",
    },
    {
      id: "prophet",
      name: "Prophet / NeuralProphet",
      score: clip(s.seasonal > 0.25 && s.n >= 40 && !s.intermittent ? 76 : 32),
      why: "Cómodo con feriados, changepoints y estacionalidad múltiple.",
      libraries: LIB.prophet,
      whenToUse: "Retail con calendario (Navidad, Pascuas, Hot Sale) y serie densa.",
      caveats: "Malos en intermitente y en series muy cortas. NeuralProphet pide más datos.",
    },
    {
      id: "lightgbm",
      name: "LightGBM (lags + calendario)",
      score: clip(s.n >= 40 || s.hierarchical ? 85 : 48),
      why: "El caballo de batalla cuando hay precio, promo, stockout y muchos SKU.",
      libraries: LIB.gbdt,
      whenToUse: "Panel de productos, features exógenas, horizonte táctico.",
      caveats: "Hay que construir lags con cuidado para no filtrar el futuro.",
    },
    {
      id: "xgboost",
      name: "XGBoost / CatBoost",
      score: clip(s.n >= 40 ? 80 : 44),
      why: "Similar a LightGBM; CatBoost maneja bien categóricas (tienda, canal).",
      libraries: ["xgboost", "catboost", "mlforecast"],
      whenToUse: "Cuando las categóricas importan más que el volumen de filas.",
      caveats: "Más lento que LightGBM en paneles grandes.",
    },
    {
      id: "nbeats",
      name: "N-BEATS",
      score: clip(s.n >= 80 && !s.intermittent ? 72 : 28),
      why: "Deep learning univariado que a veces gana a ETS en series largas.",
      libraries: LIB.dl,
      whenToUse: "Historia larga, sin features, competencia tipo M4.",
      caveats: "Datos cortos = sobreajuste. Pida GPU y validación rolling.",
    },
    {
      id: "nhits",
      name: "NHITS",
      score: clip(s.n >= 80 ? 74 : 30),
      why: "Más rápido que N-BEATS y suele ir mejor en horizontes largos.",
      libraries: ["neuralforecast", "darts"],
      whenToUse: "Horizontes largos en paneles medianos.",
      caveats: "Sigue pidiendo volumen. No magia en 12 puntos.",
    },
    {
      id: "tft",
      name: "Temporal Fusion Transformer",
      score: clip(s.n >= 100 && s.hierarchical ? 70 : 24),
      why: "Combina estáticos (SKU) y dinámicos (precio) con atención interpretable.",
      libraries: ["pytorch-forecasting", "darts"],
      whenToUse: "Muchos covariables y necesidad de explicar el forecast.",
      caveats: "Pesado de entrenar. Fácil de romper sin tuning.",
    },
    {
      id: "chronos",
      name: "Chronos (foundation model)",
      score: clip(s.short ? 78 : 68),
      why: "Modelo preentrenado: útil cuando cada SKU tiene poca historia pero el catálogo es grande.",
      libraries: LIB.fm,
      whenToUse: "Cold start, SKUs nuevos, poco dato por serie.",
      caveats: "Menos control, y no ve sus promociones a menos que las inyecte.",
    },
    {
      id: "timesfm",
      name: "TimesFM / Moirai",
      score: clip(s.short ? 74 : 66),
      why: "Foundation models de series: buen prior cuando no quiere entrenar desde cero.",
      libraries: ["timesfm", "uni2ts"],
      whenToUse: "Exploración rápida y series heterogéneas.",
      caveats: "Evalúe contra ETS/LightGBM en su holdout. No asuma SOTA en su categoría.",
    },
    {
      id: "mint",
      name: "Reconciliación jerárquica MinT",
      score: clip(s.hierarchical ? 83 : 15),
      why: "Si pronostica tienda y cadena, hay que reconciliar para que la suma coincida.",
      libraries: ["hierarchicalforecast", "scikit-hts"],
      whenToUse: "Producto × ubicación × canal.",
      caveats: "MinT necesita covarianzas de error. Empiece por bottom-up si hay pocos niveles.",
    },
  ];

  return catalog.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
}

export function improvementActions(
  profile: SeriesProfile,
  metrics: AccuracyMetrics,
  issues: ForecastIssue[],
): ImprovementAction[] {
  const actions: ImprovementAction[] = [];
  const codes = new Set(issues.map((i) => i.code));

  if (codes.has("INTERMITTENT_MISMATCH") || profile.demandClass === "intermittent" || profile.demandClass === "lumpy") {
    actions.push({
      priority: "alta",
      title: "Cambiar a un modelo de demanda intermitente",
      detail:
        "Croston, TSB o SBA sobre la serie en unidades. Evalúe con MASE y servicio, no con MAPE (los ceros lo inflan).",
      expectedGain: "Baja el sesgo en ceros y evita forecasts negativos o irreales.",
    });
  }
  if (codes.has("BIAS_SYSTEMATIC") || Math.abs(metrics.biasPct ?? 0) > 15) {
    actions.push({
      priority: "alta",
      title: "Corregir el sesgo de nivel",
      detail: "Calibre un factor media(real)/media(forecast) en el holdout, o pase a Holt amortiguado.",
      expectedGain: "El WAPE suele bajar en la misma magnitud del sesgo de volumen.",
    });
  }
  if (codes.has("SEASONALITY_IGNORED") || (profile.seasonalStrength ?? 0) > 0.35) {
    actions.push({
      priority: "alta",
      title: "Modelar la estacionalidad",
      detail: "Holt-Winters o features de semana del año / mes / feriados AR en LightGBM.",
      expectedGain: "Recupera el ciclo que hoy el modelo aplana.",
    });
  }
  if (codes.has("SCALE_SHIFT") || codes.has("NEGATIVE_FORECAST") || codes.has("SPIKE")) {
    actions.push({
      priority: "alta",
      title: "Limpiar la entrada antes de entrenar",
      detail: "Unidades consistentes, recorte de negativos, winsor de picos y una sola fila por clave.",
      expectedGain: "Evita que un error de carga destruya el modelo de todo el catálogo.",
    });
  }
  if (profile.n < 24) {
    actions.push({
      priority: "media",
      title: "Alargar historia o usar un modelo global",
      detail: "Baje de diario a semanal, o use Chronos/TimesFM/LightGBM de panel.",
      expectedGain: "Estabilidad en SKUs nuevos o de baja rotación.",
    });
  }
  if ((metrics.coverage ?? 100) < 70) {
    actions.push({
      priority: "media",
      title: "Calibrar intervalos de predicción",
      detail: "Quantile regression, conformal prediction o residuales bootstrap. El punto medio no alcanza para stock.",
      expectedGain: "Cobertura cercana al nivel nominal (80/95) y menos quiebres.",
    });
  }
  if (profile.locations.length + profile.channels.length > 2) {
    actions.push({
      priority: "media",
      title: "Reconciliar la jerarquía",
      detail: "Pronostique base y agregados, luego MinT o bottom-up ponderado.",
      expectedGain: "Suma coherente entre tienda, canal y cadena.",
    });
  }
  if ((metrics.mase ?? 0) > 1) {
    actions.push({
      priority: "alta",
      title: "El modelo no le gana al naive",
      detail: "MASE > 1: vuelva al naive estacional o cambie de familia. No agregue complejidad sin holdout temporal.",
      expectedGain: "Deja de perder contra una regla de tres.",
    });
  }
  actions.push({
    priority: "baja",
    title: "Validación temporal, no aleatoria",
    detail: "Use rolling origin (origen móvil) con el mismo horizonte de operación. Reserve las últimas 8-12 semanas.",
    expectedGain: "Métricas que se parecen a lo que va a pasar la semana que viene.",
  });
  return actions;
}
