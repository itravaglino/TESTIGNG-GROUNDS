import { finite, mean, median, pairsOf, pearson, quantile, stdev } from './stats';

export type Score = {
  n: number;
  mae: number | null;
  rmse: number | null;
  mape: number | null;
  smape: number | null;
  mdape: number | null;
  wape: number | null;
  bias: number | null;
  biasPct: number | null;
  mpe: number | null;
  trackingSignal: number | null;
  correlation: number | null;
  hit10: number | null;
  hit20: number | null;
  hit30: number | null;
  overRate: number | null;
  p50ae: number | null;
  p90ae: number | null;
};

export function emptyScore(): Score {
  return {
    n: 0,
    mae: null,
    rmse: null,
    mape: null,
    smape: null,
    mdape: null,
    wape: null,
    bias: null,
    biasPct: null,
    mpe: null,
    trackingSignal: null,
    correlation: null,
    hit10: null,
    hit20: null,
    hit30: null,
    overRate: null,
    p50ae: null,
    p90ae: null,
  };
}

export function scoreForecast(forecast: Array<number | null>, actual: Array<number | null>): Score {
  const pairs = pairsOf(forecast, actual);
  if (!pairs.length) return emptyScore();
  const errors = pairs.map(([f, a]) => f - a);
  const abs = errors.map((error) => Math.abs(error));
  const mae = mean(abs);
  const rmse = Math.sqrt(mean(errors.map((error) => error * error)) ?? 0);
  const mapeTerms = pairs.filter(([, a]) => a !== 0).map(([f, a]) => Math.abs(f - a) / Math.abs(a));
  const smapeTerms = pairs
    .filter(([f, a]) => Math.abs(f) + Math.abs(a) !== 0)
    .map(([f, a]) => (2 * Math.abs(f - a)) / (Math.abs(f) + Math.abs(a)));
  const absActual = pairs.reduce((sum, [, a]) => sum + Math.abs(a), 0);
  const signedActual = pairs.reduce((sum, [, a]) => sum + a, 0);
  const absError = abs.reduce((sum, value) => sum + value, 0);
  const bias = mean(errors);
  const mad = mae;
  const cumulative = errors.reduce((sum, value) => sum + value, 0);
  const hits = (tol: number) =>
    pairs.filter(([f, a]) => (a === 0 ? f === 0 : Math.abs(f - a) / Math.abs(a) <= tol)).length / pairs.length;
  return {
    n: pairs.length,
    mae,
    rmse,
    mape: mean(mapeTerms),
    smape: mean(smapeTerms),
    mdape: median(mapeTerms),
    wape: absActual === 0 ? (absError === 0 ? 0 : null) : absError / absActual,
    bias,
    biasPct: signedActual === 0 ? null : cumulative / signedActual,
    mpe: mean(pairs.filter(([, a]) => a !== 0).map(([f, a]) => (f - a) / a)),
    trackingSignal: mad && mad !== 0 ? cumulative / mad : null,
    correlation: pearson(
      pairs.map(([f]) => f),
      pairs.map(([, a]) => a),
    ),
    hit10: hits(0.1),
    hit20: hits(0.2),
    hit30: hits(0.3),
    overRate: errors.filter((error) => error > 0).length / pairs.length,
    p50ae: median(abs),
    p90ae: quantile(abs, 0.9),
  };
}

export function mase(
  forecast: Array<number | null>,
  actual: Array<number | null>,
  season: number,
): number | null {
  const scored = scoreForecast(forecast, actual);
  if (scored.mae == null || scored.n === 0) return null;
  const scale = seasonalScale(actual, season) ?? lagScale(actual, 1);
  if (scale == null || scale < 1e-9) return null;
  return scored.mae / scale;
}

export function seasonalScale(actual: Array<number | null>, season: number): number | null {
  if (season < 1) return null;
  const diffs: number[] = [];
  for (let i = season; i < actual.length; i += 1) {
    const current = actual[i];
    const past = actual[i - season];
    if (finite(current) && finite(past)) diffs.push(Math.abs(current - past));
  }
  return mean(diffs);
}

export function lagScale(actual: Array<number | null>, lag: number): number | null {
  return seasonalScale(actual, lag);
}

export function theilU(
  forecast: Array<number | null>,
  actual: Array<number | null>,
  naive: Array<number | null>,
): number | null {
  const model = alignedRmse(forecast, actual, naive);
  const bench = alignedRmse(naive, actual, forecast);
  if (model == null || bench == null) return null;
  if (bench < 1e-9) return model < 1e-9 ? 0 : Number.POSITIVE_INFINITY;
  return model / bench;
}

function alignedRmse(
  forecast: Array<number | null>,
  actual: Array<number | null>,
  other: Array<number | null>,
): number | null {
  const errors: number[] = [];
  const n = Math.min(forecast.length, actual.length, other.length);
  for (let i = 0; i < n; i += 1) {
    if (finite(forecast[i]) && finite(actual[i]) && finite(other[i])) {
      errors.push((forecast[i] as number) - (actual[i] as number));
    }
  }
  if (!errors.length) return null;
  return Math.sqrt(errors.reduce((sum, error) => sum + error * error, 0) / errors.length);
}

export function fva(modelWape: number | null, benchmarkWape: number | null): number | null {
  if (modelWape == null || benchmarkWape == null) return null;
  if (benchmarkWape < 1e-9) {
    if (modelWape != null && modelWape <= 0.05) return null;
    return modelWape != null && modelWape < 1e-9 ? 0 : -1;
  }
  return (benchmarkWape - modelWape) / benchmarkWape;
}

export function coverage(
  actual: Array<number | null>,
  lower: Array<number | null>,
  upper: Array<number | null>,
): { coverage: number | null; meanWidth: number | null; n: number } {
  let inside = 0;
  let n = 0;
  const widths: number[] = [];
  for (let i = 0; i < actual.length; i += 1) {
    if (!finite(actual[i]) || !finite(lower[i]) || !finite(upper[i])) continue;
    n += 1;
    const lo = Math.min(lower[i] as number, upper[i] as number);
    const hi = Math.max(lower[i] as number, upper[i] as number);
    if ((actual[i] as number) >= lo && (actual[i] as number) <= hi) inside += 1;
    widths.push(hi - lo);
  }
  return { coverage: n ? inside / n : null, meanWidth: mean(widths), n };
}

export function coefficientOfVariation(values: Array<number | null>): number | null {
  const clean = values.filter(finite);
  const avg = mean(clean);
  const sd = stdev(clean);
  if (avg == null || sd == null || Math.abs(avg) < 1e-9) return null;
  return sd / Math.abs(avg);
}
