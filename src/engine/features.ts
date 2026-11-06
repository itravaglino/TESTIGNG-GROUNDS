import { seasonLag } from "./dates";
import { mean, stdev } from "./metrics";
import type { DemandClass, ForecastRow, PeriodType, SeriesFeatures } from "./types";
import { EPS } from "./types";

export function computeFeatures(points: ForecastRow[], periodType: PeriodType): SeriesFeatures {
  const actuals = points.map((p) => p.actual).filter((x): x is number => x != null && Number.isFinite(x));
  const n = actuals.length;
  const pos = actuals.filter((x) => x > EPS);
  const nPos = pos.length;
  const zerosShare = n ? actuals.filter((x) => Math.abs(x) <= EPS).length / n : null;
  const m = mean(actuals);
  const sd = stdev(actuals);
  const cv = m != null && Math.abs(m) > EPS && sd != null ? sd / m : null;
  const adi = nPos > 0 ? n / nPos : null;
  const zMean = mean(pos);
  const zSd = stdev(pos);
  const cv2 = zMean != null && Math.abs(zMean) > EPS && zSd != null ? (zSd / zMean) ** 2 : null;
  const demandClass = classify(adi, cv2);
  const pairs = points.filter((p) => p.actual != null && p.forecast != null && Number.isFinite(p.actual) && Number.isFinite(p.forecast));
  const trend = mannKendallTrend(actuals);
  const lag = seasonLag(periodType);
  const acfSeason = acf(actuals, lag);
  const seasonal = n >= 2 * lag && acfSeason != null && acfSeason > 0.3;
  return {
    n,
    nPos,
    nPairs: pairs.length,
    mean: m,
    cv,
    adi,
    cv2,
    zerosShare,
    demandClass,
    trend: trend.flag,
    seasonal,
    senSlope: trend.slope,
    acfSeason,
    lastShock: lastShock(actuals),
  };
}

export function classify(adi: number | null, cv2: number | null): DemandClass {
  if (adi == null || cv2 == null) return "unknown";
  if (adi < 1.32 && cv2 < 0.49) return "smooth";
  if (adi < 1.32 && cv2 >= 0.49) return "erratic";
  if (adi >= 1.32 && cv2 < 0.49) return "intermittent";
  return "lumpy";
}

function mannKendallTrend(xs: number[]): { flag: boolean; slope: number | null } {
  if (xs.length < 10) return { flag: false, slope: null };
  let s = 0;
  const slopes: number[] = [];
  for (let i = 1; i < xs.length; i++) {
    for (let j = 0; j < i; j++) {
      const d = xs[i] - xs[j];
      if (d > EPS) s += 1;
      else if (d < -EPS) s -= 1;
      const den = i - j;
      if (den > 0) slopes.push(d / den);
    }
  }
  slopes.sort((a, b) => a - b);
  const slope = slopes.length ? slopes[Math.floor(slopes.length / 2)] : null;
  const n = xs.length;
  const varS = (n * (n - 1) * (2 * n + 5)) / 18;
  const z = varS > 0 ? s / Math.sqrt(varS) : 0;
  const m = mean(xs.map(Math.abs)) ?? 1;
  const material = slope != null && Math.abs(slope) * Math.min(n, 12) / Math.max(m, EPS) >= 0.1;
  return { flag: Math.abs(z) > 1.96 && material, slope };
}

function acf(xs: number[], lag: number): number | null {
  if (xs.length <= lag + 2) return null;
  const m = mean(xs)!;
  let num = 0;
  let den = 0;
  for (let i = 0; i < xs.length; i++) den += (xs[i] - m) ** 2;
  for (let i = lag; i < xs.length; i++) num += (xs[i] - m) * (xs[i - lag] - m);
  if (den <= EPS) return null;
  return num / den;
}

function lastShock(xs: number[]): boolean {
  if (xs.length < 7) return false;
  const prev = xs.slice(-7, -1);
  const last = xs[xs.length - 1];
  const med = [...prev].sort((a, b) => a - b)[Math.floor(prev.length / 2)];
  const mad = medianAbs(prev, med);
  if (mad <= EPS) return last > 3 * Math.max(med, EPS);
  const z = (0.6745 * (last - med)) / mad;
  return Math.abs(z) > 3.5 || last > 3 * Math.max(med, EPS);
}

function medianAbs(xs: number[], med: number): number {
  const d = xs.map((x) => Math.abs(x - med)).sort((a, b) => a - b);
  return d[Math.floor(d.length / 2)] ?? 0;
}
