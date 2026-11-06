import type { ForecastPoint, IntermittencyClass, Metrics } from "./types";
import { adiCv2, mean, stdev } from "./profile";

export const METRIC_HELP: Record<string, { name: string; formula: string; good: string }> = {
  mae: { name: "MAE", formula: "media |y − ŷ|", good: "Más bajo mejor. Unidades de demanda." },
  mse: { name: "MSE", formula: "media (y − ŷ)²", good: "Más bajo mejor. Penaliza picos." },
  rmse: { name: "RMSE", formula: "√MSE", good: "Más bajo mejor. Misma unidad que la demanda." },
  mape: { name: "MAPE", formula: "media |y − ŷ| / |y|", good: "<10% excelente, <20% usable. Inestable si y≈0." },
  smape: { name: "sMAPE", formula: "media 2|y − ŷ| / (|y|+|ŷ|)", good: "<15% bueno. Acotado 0–200%." },
  wape: { name: "WAPE", formula: "Σ|y − ŷ| / Σ|y|", good: "Métrica principal de negocio. <15% bueno, <25% aceptable." },
  mdape: { name: "MdAPE", formula: "mediana |y − ŷ| / |y|", good: "Robusto a outliers." },
  mase: { name: "MASE", formula: "MAE / MAE naive estacional", good: "<1 gana al naive. <0.85 fuerte." },
  rmsse: { name: "RMSSE", formula: "RMSE / RMSE naive estacional", good: "<1 gana al naive." },
  me: { name: "Bias (ME)", formula: "media (ŷ − y)", good: "Cerca de 0. Positivo = sobrepronóstico." },
  mpe: { name: "MPE", formula: "media (ŷ − y)/y", good: "Cerca de 0." },
  biasPct: { name: "Bias %", formula: "ME / media(y)", good: "|bias| < 5% ideal, <10% aceptable." },
  trackingSignal: { name: "Tracking signal", formula: "Σ error / MAE", good: "Fuera de ±4: sesgo sistemático." },
  theilU1: { name: "Theil U1", formula: "RMSE / (RMSE_y + RMSE_ŷ)", good: "0 perfecto, <1 siempre." },
  theilU2: { name: "Theil U2", formula: "RMSE modelo / RMSE naive", good: "<1 supera al naive." },
  r2: { name: "R²", formula: "1 − SS_res/SS_tot", good: ">0.5 útil en series suaves." },
  rmsePct: { name: "RMSE%", formula: "RMSE / media(y)", good: "Comparable entre productos." },
  hitRate10: { name: "Hit ±10%", formula: "% puntos con |err|/y ≤ 10%", good: "Más alto mejor." },
  hitRate20: { name: "Hit ±20%", formula: "% puntos con |err|/y ≤ 20%", good: "Más alto mejor." },
  underForecastRate: { name: "% subpronóstico", formula: "% con ŷ < y", good: "Alto implica quiebre de stock." },
  overForecastRate: { name: "% sobrepronóstico", formula: "% con ŷ > y", good: "Alto implica sobrestock." },
  piCoverage: { name: "Cobertura PI", formula: "% y ∈ [lo, hi]", good: "Cerca del nivel nominal (p.ej. 80%)." },
  pinaw: { name: "PINAW", formula: "ancho medio PI / rango y", good: "Bajo = intervalos informativos." },
  zeroForecastRate: { name: "% pronóstico 0", formula: "% ŷ = 0", good: "Debe alinearse a la intermitencia real." },
  adi: { name: "ADI", formula: "n / n_demanda>0", good: ">1.32 intermitente (Syntetos-Boylan)." },
  cv2: { name: "CV²", formula: "(σ/μ)² de demandas >0", good: ">0.49 errático/lumpy." },
};

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function naiveSeasonalMae(actuals: number[], period: number): number {
  const p = Math.max(1, period);
  if (actuals.length <= p) {
    const diffs: number[] = [];
    for (let i = 1; i < actuals.length; i++) diffs.push(Math.abs(actuals[i] - actuals[i - 1]));
    return diffs.length ? mean(diffs) : 0;
  }
  const diffs: number[] = [];
  for (let i = p; i < actuals.length; i++) diffs.push(Math.abs(actuals[i] - actuals[i - p]));
  return diffs.length ? mean(diffs) : 0;
}

function naiveSeasonalRmse(actuals: number[], period: number): number {
  const p = Math.max(1, period);
  const diffs: number[] = [];
  const start = actuals.length > p ? p : 1;
  for (let i = start; i < actuals.length; i++) {
    const prev = actuals[i - (actuals.length > p ? p : 1)];
    diffs.push((actuals[i] - prev) ** 2);
  }
  return diffs.length ? Math.sqrt(mean(diffs)) : 0;
}

export function computeMetrics(series: ForecastPoint[], seasonalPeriod = 1): Metrics {
  const n = series.length;
  const forecasts = series.map((p) => p.forecast);
  const pairs = series.filter((p) => p.actual !== undefined && Number.isFinite(p.actual));
  const actuals = pairs.map((p) => p.actual as number);
  const preds = pairs.map((p) => p.forecast);
  const { adi, cv2, intermittency } = adiCv2(actuals.length ? actuals : forecasts);

  const emptyAcc: Metrics = {
    n,
    nWithActual: pairs.length,
    meanForecast: mean(forecasts),
    meanActual: actuals.length ? mean(actuals) : null,
    mae: null, mse: null, rmse: null, mape: null, smape: null, wape: null, mdape: null,
    mase: null, rmsse: null, me: null, mpe: null, biasPct: null, trackingSignal: null,
    theilU1: null, theilU2: null, r2: null, rmsePct: null, hitRate10: null, hitRate20: null,
    underForecastRate: null, overForecastRate: null, piCoverage: null, pinaw: null,
    zeroForecastRate: n === 0 ? 0 : forecasts.filter((f) => f === 0).length / n,
    demandCv: actuals.length >= 2 ? stdev(actuals) / (Math.abs(mean(actuals)) || 1) : null,
    adi, cv2, intermittency,
  };

  if (pairs.length === 0) return emptyAcc;

  const err = preds.map((f, i) => f - actuals[i]);
  const abs = err.map(Math.abs);
  const mae = mean(abs);
  const mse = mean(err.map((e) => e ** 2));
  const rmse = Math.sqrt(mse);
  const me = mean(err);
  const mapeVals = pairs
    .map((_, i) => (Math.abs(actuals[i]) > 1e-9 ? abs[i] / Math.abs(actuals[i]) : null))
    .filter((x): x is number => x !== null);
  const mape = mapeVals.length ? mean(mapeVals) : null;
  const smape = mean(
    pairs.map((_, i) => {
      const d = Math.abs(actuals[i]) + Math.abs(preds[i]);
      return d === 0 ? 0 : (2 * abs[i]) / d;
    }),
  );
  const sumAbsY = actuals.reduce((a, y) => a + Math.abs(y), 0);
  const wape = sumAbsY === 0 ? null : abs.reduce((a, x) => a + x, 0) / sumAbsY;
  const mdape = mapeVals.length ? median(mapeVals) : null;
  const scaleMae = naiveSeasonalMae(actuals, seasonalPeriod);
  const scaleRmse = naiveSeasonalRmse(actuals, seasonalPeriod);
  const mase = scaleMae > 0 ? mae / scaleMae : null;
  const rmsse = scaleRmse > 0 ? rmse / scaleRmse : null;
  const mpeVals = pairs
    .map((_, i) => (Math.abs(actuals[i]) > 1e-9 ? err[i] / actuals[i] : null))
    .filter((x): x is number => x !== null);
  const meanY = mean(actuals);
  const ssTot = actuals.reduce((a, y) => a + (y - meanY) ** 2, 0);
  const ssRes = err.reduce((a, e) => a + e ** 2, 0);
  const rmseY = Math.sqrt(mean(actuals.map((y) => y ** 2)));
  const rmseF = Math.sqrt(mean(preds.map((f) => f ** 2)));
  const naiveErr = actuals.slice(1).map((y, i) => y - actuals[i]);
  const naiveRmse = naiveErr.length ? Math.sqrt(mean(naiveErr.map((e) => e ** 2))) : 0;
  const piPairs = pairs.filter((p) => p.lower !== undefined && p.upper !== undefined);
  const yMin = Math.min(...actuals);
  const yMax = Math.max(...actuals);

  return {
    ...emptyAcc,
    mae, mse, rmse, mape, smape, wape, mdape, mase, rmsse, me,
    mpe: mpeVals.length ? mean(mpeVals) : null,
    biasPct: meanY === 0 ? null : me / meanY,
    trackingSignal: mae === 0 ? 0 : err.reduce((a, e) => a + e, 0) / mae,
    theilU1: rmseY + rmseF === 0 ? null : rmse / (rmseY + rmseF),
    theilU2: naiveRmse === 0 ? null : rmse / naiveRmse,
    r2: ssTot === 0 ? null : 1 - ssRes / ssTot,
    rmsePct: meanY === 0 ? null : rmse / Math.abs(meanY),
    hitRate10: mean(pairs.map((_, i) => (Math.abs(actuals[i]) > 1e-9 && abs[i] / Math.abs(actuals[i]) <= 0.1 ? 1 : 0))),
    hitRate20: mean(pairs.map((_, i) => (Math.abs(actuals[i]) > 1e-9 && abs[i] / Math.abs(actuals[i]) <= 0.2 ? 1 : 0))),
    underForecastRate: mean(pairs.map((_, i) => (preds[i] < actuals[i] ? 1 : 0))),
    overForecastRate: mean(pairs.map((_, i) => (preds[i] > actuals[i] ? 1 : 0))),
    piCoverage: piPairs.length
      ? mean(piPairs.map((p) => ((p.actual as number) >= (p.lower as number) && (p.actual as number) <= (p.upper as number) ? 1 : 0)))
      : null,
    pinaw: piPairs.length && yMax > yMin
      ? mean(piPairs.map((p) => (p.upper as number) - (p.lower as number))) / (yMax - yMin)
      : null,
  };
}

export function formatPct(x: number | null, digits = 1): string {
  if (x === null || !Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function formatNum(x: number | null, digits = 2): string {
  if (x === null || !Number.isFinite(x)) return "—";
  return x.toLocaleString("es-AR", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function intermittencyLabel(c: IntermittencyClass): string {
  return {
    smooth: "Suave",
    erratic: "Errática",
    intermittent: "Intermitente",
    lumpy: "Lumpy",
  }[c];
}
