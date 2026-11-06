import type { AccuracyMetrics, PointMetrics } from "./types";

export interface ForecastPoint {
  forecast: number;
  actual: number | null;
  lower?: number | null;
  upper?: number | null;
}

export interface AccuracyOptions {
  seasonLength?: number;
  history?: readonly (number | null | undefined)[];
  naive?: { mae: number | null; mse: number | null };
  hitTolerance?: number;
}

function asFinite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function defined(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) return null;
  return value === 0 ? 0 : value;
}

export function percentile(values: readonly number[], p: number): number | null {
  if (!Number.isFinite(p) || p < 0 || p > 100) return null;
  const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  if (sorted.length === 1) return sorted[0];
  const index = ((sorted.length - 1) * p) / 100;
  const low = Math.floor(index);
  const high = Math.ceil(index);
  if (low === high) return sorted[low];
  const weight = index - low;
  return sorted[low] * (1 - weight) + sorted[high] * weight;
}

export function naiveScale(
  history: readonly (number | null | undefined)[],
  seasonLength = 1,
): { mae: number | null; mse: number | null; pairs: number } {
  const season = Math.max(1, Math.trunc(seasonLength || 1));
  let abs = 0;
  let sq = 0;
  let pairs = 0;
  for (let t = season; t < history.length; t++) {
    const cur = asFinite(history[t]);
    const prev = asFinite(history[t - season]);
    if (cur === null || prev === null) continue;
    const d = cur - prev;
    abs += Math.abs(d);
    sq += d * d;
    pairs++;
  }
  if (pairs === 0) return { mae: null, mse: null, pairs: 0 };
  return { mae: abs / pairs, mse: sq / pairs, pairs };
}

export function computePoint(
  forecast: number,
  actual: number | null,
  bounds?: { lower?: number | null; upper?: number | null } | null,
): PointMetrics {
  const predicted = asFinite(forecast);
  const observed = asFinite(actual);
  const lower = asFinite(bounds?.lower);
  const upper = asFinite(bounds?.upper);
  const intervalWidth = lower !== null && upper !== null ? upper - lower : null;
  const insideInterval =
    observed !== null && lower !== null && upper !== null
      ? lower <= observed && observed <= upper
      : null;
  if (predicted === null || observed === null) {
    return {
      error: null,
      absError: null,
      pctError: null,
      ape: null,
      squaredError: null,
      insideInterval,
      intervalWidth,
    };
  }
  const error = predicted - observed;
  const mag = Math.abs(observed);
  return {
    error,
    absError: Math.abs(error),
    pctError: mag === 0 ? null : error / mag,
    ape: mag === 0 ? null : Math.abs(error) / mag,
    squaredError: error * error,
    insideInterval,
    intervalWidth,
  };
}

export function computeAccuracy(
  points: readonly ForecastPoint[],
  options?: AccuracyOptions,
): AccuracyMetrics {
  const hitTolerance = options?.hitTolerance ?? 0.1;
  let nWithActual = 0;
  let sumError = 0;
  let sumAbsolute = 0;
  let sumSquared = 0;
  let sumApe = 0;
  let apeCount = 0;
  let sumPct = 0;
  let pctCount = 0;
  let sumSmape = 0;
  let smapeCount = 0;
  let sumAbsActual = 0;
  let sumActual = 0;
  let sumForecast = 0;
  let hits = 0;
  let over = 0;
  let under = 0;
  let sumPinball = 0;
  let maxAbs = 0;
  let intervalHits = 0;
  let intervalCount = 0;
  let sumWidth = 0;
  let widthCount = 0;
  let theilModel = 0;
  let theilNaive = 0;
  let theilPairs = 0;
  let previousActual: number | null = null;
  const absErrors: number[] = [];
  const apes: number[] = [];
  const actuals: number[] = [];
  const forecasts: number[] = [];
  const actualSeries: (number | null)[] = [];

  for (const point of points) {
    const observed = asFinite(point.actual);
    const predicted = asFinite(point.forecast);
    const metrics = computePoint(point.forecast, point.actual, point);
    actualSeries.push(observed);
    if (metrics.intervalWidth !== null) {
      sumWidth += metrics.intervalWidth;
      widthCount++;
    }
    if (metrics.insideInterval !== null) {
      intervalCount++;
      if (metrics.insideInterval) intervalHits++;
    }
    if (metrics.error === null || observed === null || predicted === null) {
      previousActual = observed;
      continue;
    }
    const error = metrics.error;
    nWithActual++;
    sumError += error;
    sumAbsolute += Math.abs(error);
    sumSquared += error * error;
    sumAbsActual += Math.abs(observed);
    sumActual += observed;
    sumForecast += predicted;
    sumPinball += Math.abs(error) / 2;
    absErrors.push(Math.abs(error));
    actuals.push(observed);
    forecasts.push(predicted);
    if (Math.abs(error) > maxAbs) maxAbs = Math.abs(error);
    if (metrics.ape !== null) {
      sumApe += metrics.ape;
      apeCount++;
      apes.push(metrics.ape);
    }
    if (metrics.pctError !== null) {
      sumPct += metrics.pctError;
      pctCount++;
    }
    const denom = Math.abs(observed) + Math.abs(predicted);
    if (denom !== 0) {
      sumSmape += (2 * Math.abs(error)) / denom;
      smapeCount++;
    }
    if (observed === 0) {
      if (predicted === 0) hits++;
    } else if (metrics.ape !== null && metrics.ape <= hitTolerance) {
      hits++;
    }
    if (predicted > observed) over++;
    else if (predicted < observed) under++;
    if (previousActual !== null) {
      const naiveGap = observed - previousActual;
      theilNaive += naiveGap * naiveGap;
      theilModel += error * error;
      theilPairs++;
    }
    previousActual = observed;
  }

  const scale = options?.naive
    ? { mae: asFinite(options.naive.mae), mse: asFinite(options.naive.mse) }
    : naiveScale(options?.history ?? actualSeries, options?.seasonLength ?? 1);
  const me = nWithActual > 0 ? sumError / nWithActual : null;
  const mae = nWithActual > 0 ? sumAbsolute / nWithActual : null;
  const mse = nWithActual > 0 ? sumSquared / nWithActual : null;
  const rmse = mse === null ? null : Math.sqrt(mse);
  let r2: number | null = null;
  let corr: number | null = null;
  if (actuals.length >= 2) {
    const meanA = sumActual / actuals.length;
    const meanF = sumForecast / forecasts.length;
    let cov = 0;
    let a2 = 0;
    let f2 = 0;
    for (let i = 0; i < actuals.length; i++) {
      const da = actuals[i] - meanA;
      const df = forecasts[i] - meanF;
      cov += da * df;
      a2 += da * da;
      f2 += df * df;
    }
    if (a2 > 0) r2 = 1 - sumSquared / a2;
    if (a2 > 0 && f2 > 0) corr = cov / Math.sqrt(a2 * f2);
  }

  return {
    n: points.length,
    nWithActual,
    me: defined(me),
    mae: defined(mae),
    mse: defined(mse),
    rmse: defined(rmse),
    mape: defined(apeCount > 0 ? (100 * sumApe) / apeCount : null),
    smape: defined(smapeCount > 0 ? (100 * sumSmape) / smapeCount : null),
    wape: defined(sumAbsActual > 0 ? (100 * sumAbsolute) / sumAbsActual : null),
    mdape: defined((() => {
      const m = percentile(apes, 50);
      return m === null ? null : 100 * m;
    })()),
    mpe: defined(pctCount > 0 ? (100 * sumPct) / pctCount : null),
    biasPct: defined(sumAbsActual > 0 ? (100 * sumError) / sumAbsActual : null),
    trackingSignal: defined(mae !== null && mae > 0 ? sumError / mae : null),
    mase: defined(mae !== null && scale.mae !== null && scale.mae > 0 ? mae / scale.mae : null),
    rmsse: defined(
      mse !== null && scale.mse !== null && scale.mse > 0 ? Math.sqrt(mse / scale.mse) : null,
    ),
    r2: defined(r2),
    corr: defined(corr),
    theilU: defined(theilPairs > 0 && theilNaive > 0 ? Math.sqrt(theilModel / theilNaive) : null),
    hitRate: defined(nWithActual > 0 ? hits / nWithActual : null),
    overforecastRate: defined(nWithActual > 0 ? over / nWithActual : null),
    underforecastRate: defined(nWithActual > 0 ? under / nWithActual : null),
    coverage: defined(intervalCount > 0 ? (100 * intervalHits) / intervalCount : null),
    meanIntervalWidth: defined(widthCount > 0 ? sumWidth / widthCount : null),
    pinball50: defined(nWithActual > 0 ? sumPinball / nWithActual : null),
    maxAbsError: defined(nWithActual > 0 ? maxAbs : null),
    p90AbsError: percentile(absErrors, 90),
  };
}

export const DEFAULT_GATES = {
  mapeWarn: 25,
  mapeFail: 55,
  wapeWarn: 20,
  wapeFail: 45,
  trackingSignalFail: 4,
  minPoints: 8,
  spikeZ: 3.5,
  coverageMin: 70,
  scaleShiftRatio: 50,
};
