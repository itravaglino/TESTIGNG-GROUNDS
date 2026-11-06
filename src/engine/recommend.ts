import type { DemandClass, ModelRec, Point, Verdict } from "./types";
import { pairs, wapeOf } from "./metrics";

export function recommendModels(opts: {
  demandClass: DemandClass;
  n: number;
  seasonalLag: number | null;
  hasTrend: boolean;
  hasActuals: boolean;
  constantForecast: boolean;
  leakage: boolean;
}): ModelRec[] {
  const { demandClass, n, seasonalLag, hasTrend, hasActuals, constantForecast, leakage } = opts;
  const recs: ModelRec[] = [];

  const add = (r: ModelRec) => recs.push(r);

  if (n < 8) {
    add({
      id: "naive",
      name: "Naive / media móvil corta",
      fit: "alta",
      why: "Hay muy poca historia. Cualquier modelo rico va a sobreajustar.",
      howToStart: "Usar el último valor o el promedio de 3 períodos. Completar historia antes de ETS/ARIMA.",
      caution: "No uses Prophet ni boosting con menos de 8–12 puntos.",
      libs: ["statsforecast", "pandas"],
    });
    return recs;
  }

  if (demandClass === "intermittent" || demandClass === "lumpy") {
    add({
      id: "croston",
      name: "Croston / SBA / TSB",
      fit: "alta",
      why: "La demanda es intermitente o grumosa (ADI/CV²). Los modelos de series continuas suavizan de más y sesgan.",
      howToStart: "statsforecast CrostonClassic, CrostonSBA o TSB. Evaluar con MASE/RMSSE, no con MAPE.",
      caution: "MAPE explota con ceros. No uses MAPE como KPI de este SKU.",
      libs: ["statsforecast", "croston", "nixtla"],
    });
    add({
      id: "lightgbm_zero",
      name: "LightGBM con lags + flag de cero",
      fit: "media",
      why: "Si hay muchos SKUs parecidos, un modelo global captura rareza mejor que Croston aislado.",
      howToStart: "Features: lags, rolling ADI, mes, canal. Pérdida Tweedie o dos etapas (ocurrencia × tamaño).",
      caution: "Necesita pooling entre productos. En un SKU solo suele perder contra Croston.",
      libs: ["lightgbm", "mlforecast"],
    });
  }

  if (demandClass === "smooth" || demandClass === "erratic") {
    if (seasonalLag && hasTrend) {
      add({
        id: "ets",
        name: "ETS / Holt-Winters",
        fit: "alta",
        why: "Serie relativamente densa, con tendencia y estacionalidad detectada.",
        howToStart: "statsforecast AutoETS o statsmodels ExponentialSmoothing con tendencia aditiva y estacionalidad según el lag.",
        caution: "Malo si hay muchos ceros o promociones no modeladas.",
        libs: ["statsforecast", "statsmodels"],
      });
      add({
        id: "sarima",
        name: "SARIMA / AutoARIMA",
        fit: "alta",
        why: "Misma familia de señal; útil como segundo modelo de ensemble.",
        howToStart: "statsforecast AutoARIMA con season_length = lag estacional.",
        caution: "No forzar órdenes altos con n chico.",
        libs: ["statsforecast", "pmdarima"],
      });
    } else if (hasTrend) {
      add({
        id: "holt",
        name: "Holt (tendencia)",
        fit: "alta",
        why: "Hay tendencia y no hay estacionalidad clara.",
        howToStart: "SES damped trend / Holt. Comparar contra naive.",
        caution: "Holt lineal se va al infinito: preferí tendencia amortiguada.",
        libs: ["statsforecast", "statsmodels"],
      });
    } else if (seasonalLag) {
      add({
        id: "snaive_ets",
        name: "Naive estacional + ETS aditivo",
        fit: "alta",
        why: "Patrón que se repite y poca tendencia.",
        howToStart: "SeasonalNaive como piso; ETS sin tendencia como candidato.",
        caution: "Revisar si el lag detectado (7/12/52) coincide con el negocio.",
        libs: ["statsforecast"],
      });
    } else {
      add({
        id: "ses_theta",
        name: "SES / Theta",
        fit: "alta",
        why: "Serie suave o errática sin estacionalidad fuerte.",
        howToStart: "AutoTheta y SES. Theta suele ser un baseline difícil de ganar.",
        caution: "Si el error es errático, agregar features de promo antes de un modelo más complejo.",
        libs: ["statsforecast"],
      });
    }
  }

  if (n >= 24 && demandClass === "smooth") {
    add({
      id: "prophet",
      name: "Prophet / Fourier",
      fit: "media",
      why: "Historia suficiente para estacionalidades múltiples y feriados (útil en LatAm con calendario comercial).",
      howToStart: "Prophet con holidays AR/país, o AutoCES/MSTL si preferís Nixtla.",
      caution: "Pesado por SKU. No lo uses en intermitentes.",
      libs: ["prophet", "statsforecast"],
    });
  }

  if (n >= 16 && (demandClass === "erratic" || demandClass === "smooth")) {
    add({
      id: "gbm",
      name: "LightGBM / XGBoost (lags + calendario)",
      fit: "media",
      why: "Si hay promociones, precio o más de ~50 SKUs, un modelo tabular global suele ganar a ETS aislado.",
      howToStart: "mlforecast o pipeline propio: lags 1,2,3,12, medias móviles, dummies de mes, precio, promo.",
      caution: "Sin variables exógenas reales el boosting no magia: perdés interpretabilidad contra ETS.",
      libs: ["lightgbm", "xgboost", "mlforecast"],
    });
  }

  if (constantForecast) {
    add({
      id: "replace_constant",
      name: "Reemplazar el constante",
      fit: "alta",
      why: "Un forecast plano no es un modelo: es un default. Hay señal que no se está usando.",
      howToStart: "Empezar por seasonal naive o Croston según la clase de demanda.",
      caution: "No 'suavices' más un constante.",
      libs: ["statsforecast"],
    });
  }

  if (leakage) {
    add({
      id: "fix_leak",
      name: "Rehacer el backtest",
      fit: "alta",
      why: "El pronóstico copia el real anterior: las métricas están infladas.",
      howToStart: "Separar corte temporal. El modelo solo puede ver información conocida al origen del forecast.",
      caution: "Cualquier ranking de modelos hoy es inválido hasta corregir la filtración.",
      libs: ["pandas", "mlforecast"],
    });
  }

  if (!hasActuals) {
    recs.forEach((r) => {
      r.caution += " Sin columna real no se puede elegir ganador: estas recomendaciones son por forma de la serie de forecast.";
    });
  }

  add({
    id: "ensemble",
    name: "Ensemble simple",
    fit: "media",
    why: "Promediar 2–3 modelos no correlacionados (p.ej. ETS + Croston o ETS + GBM) suele bajar RMSE.",
    howToStart: "Promedio simple o ponderado por 1/MAE en validación rolling.",
    caution: "No ensembles de 10 modelos en 12 puntos de historia.",
    libs: ["statsforecast", "mlforecast"],
  });

  const order = { alta: 0, media: 1, baja: 2 };
  return recs.sort((a, b) => order[a.fit] - order[b.fit]).slice(0, 4);
}

export function improvements(opts: {
  demandClass: DemandClass;
  issues: { id: string; severity: string }[];
  metrics: { id: string; value: number | null }[];
  verdict: Verdict;
  n: number;
  seasonalLag: number | null;
}): string[] {
  const out: string[] = [];
  const mape = opts.metrics.find((m) => m.id === "mape")?.value;
  const wape = opts.metrics.find((m) => m.id === "wape")?.value;
  const pbias = opts.metrics.find((m) => m.id === "pbias")?.value;
  const mase = opts.metrics.find((m) => m.id === "mase")?.value;
  const ts = opts.metrics.find((m) => m.id === "tracking_signal")?.value;
  const skill = opts.metrics.find((m) => m.id === "skill_naive")?.value;

  if (opts.verdict === "discard") {
    out.push("Descartar este SKU del paquete de forecast hasta tener ≥8 períodos limpios o un modelo de intermitencia con pooling.");
  }
  if (opts.n < 12) out.push("Alargar historia (mínimo 12–24 períodos) o agrupar con SKUs hermanos.");
  if (opts.demandClass === "intermittent" || opts.demandClass === "lumpy") {
    out.push("No uses MAPE. Reportá MASE, RMSSE y disponibilidad. Modelá ocurrencia y tamaño por separado.");
  }
  if (mape != null && mape > 40) out.push("MAPE alto: revisar outliers, promociones no informadas y unidad (cajas vs unidades).");
  if (wape != null && wape > 30) out.push("WAPE > 30%: el error pesa en volumen. Priorizá este SKU en el next model bake-off.");
  if (pbias != null && pbias > 15) out.push("Sobrepronóstico sistemático: bajar nivel (SES más reactivo) o incorporar stock/perdido.");
  if (pbias != null && pbias < -15) out.push("Subpronóstico sistemático: el modelo no ve picos. Agregar promo, precio y rupturas de stock.");
  if (mase != null && mase > 1) out.push("MASE > 1: el modelo pierde contra el naive. Volvé a un baseline y rehacé features.");
  if (ts != null && Math.abs(ts) > 4) out.push("Tracking signal inestable: el sesgo no se autocorrige. Recalibrar o resetear el nivel.");
  if (skill != null && skill < 0) out.push("Skill negativo vs naive: dejar de usar este forecast en abastecimiento.");
  if (opts.seasonalLag) out.push(`Estacionalidad ~${opts.seasonalLag} períodos: alineá season_length y el calendario comercial (aguinaldo, fiestas, vacaciones).`);
  if (opts.issues.some((i) => i.id === "outliers" || i.id === "spike")) {
    out.push("Tratar picos como eventos (promo/ruptura), no como demanda base.");
  }
  if (opts.issues.some((i) => i.id === "leakage")) {
    out.push("Rehacer el archivo sin filtración: forecast origin-based, nunca con el real ya observado del mismo período.");
  }
  if (out.length === 0) out.push("Mantener el modelo actual y controlar WAPE/sesgo en un rolling de 8 semanas.");
  return out;
}

export function scoreProduct(opts: {
  verdict: Verdict;
  issues: { severity: string }[];
  series: Point[];
}): number {
  let s = 100;
  if (opts.verdict === "discard") s -= 45;
  if (opts.verdict === "correct") s -= 12;
  for (const i of opts.issues) {
    if (i.severity === "fatal") s -= 25;
    else if (i.severity === "error") s -= 12;
    else if (i.severity === "warn") s -= 5;
  }
  const w = wapeOf(pairs(opts.series));
  if (w !== null) {
    if (w > 50) s -= 20;
    else if (w > 30) s -= 12;
    else if (w > 15) s -= 5;
    else s += 5;
  }
  return Math.max(0, Math.min(100, Math.round(s)));
}
