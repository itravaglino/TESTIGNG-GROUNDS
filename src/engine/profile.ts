import type { Cadence, ForecastPoint, ForecastRow, IntermittencyClass, SeriesProfile } from "./types";
import { toIsoDate } from "./parse";

export function groupByProduct(rows: ForecastRow[]): Map<string, ForecastRow[]> {
  const map = new Map<string, ForecastRow[]>();
  for (const row of rows) {
    const key = `${row.productId}||${row.location}`;
    const list = map.get(key);
    if (list) list.push(row);
    else map.set(key, [row]);
  }
  return map;
}

export function sortPoints(points: ForecastPoint[]): ForecastPoint[] {
  return [...points].sort((a, b) => a.date.getTime() - b.date.getTime());
}

export function inferCadence(dates: Date[]): { cadence: Cadence; stepDays: number } {
  if (dates.length < 2) return { cadence: "irregular", stepDays: 7 };
  const diffs: number[] = [];
  const sorted = [...dates].sort((a, b) => a.getTime() - b.getTime());
  for (let i = 1; i < sorted.length; i++) {
    const d = (sorted[i].getTime() - sorted[i - 1].getTime()) / 86400000;
    if (d > 0) diffs.push(d);
  }
  if (diffs.length === 0) return { cadence: "irregular", stepDays: 7 };
  diffs.sort((a, b) => a - b);
  const median = diffs[Math.floor(diffs.length / 2)];
  if (median <= 1.5) return { cadence: "day", stepDays: 1 };
  if (median <= 9) return { cadence: "week", stepDays: 7 };
  if (median <= 40) return { cadence: "month", stepDays: 30 };
  if (median <= 100) return { cadence: "quarter", stepDays: 91 };
  return { cadence: "irregular", stepDays: Math.max(1, Math.round(median)) };
}

export function seasonalPeriodFor(cadence: Cadence, n: number): number {
  if (cadence === "day") return n >= 28 ? 7 : 1;
  if (cadence === "week") return n >= 52 ? 52 : n >= 12 ? 13 : 1;
  if (cadence === "month") return n >= 24 ? 12 : 1;
  if (cadence === "quarter") return n >= 8 ? 4 : 1;
  return 1;
}

export function mean(xs: number[]): number {
  if (xs.length === 0) return 0;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function variance(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1);
}

export function stdev(xs: number[]): number {
  return Math.sqrt(variance(xs));
}

export function mannKendall(values: number[]): { hasTrend: boolean; slope: number } {
  const n = values.length;
  if (n < 8) return { hasTrend: false, slope: 0 };
  let s = 0;
  for (let i = 0; i < n - 1; i++) {
    for (let j = i + 1; j < n; j++) {
      const d = values[j] - values[i];
      s += d > 0 ? 1 : d < 0 ? -1 : 0;
    }
  }
  const varS = (n * (n - 1) * (2 * n + 5)) / 18;
  const z = s === 0 ? 0 : (s > 0 ? s - 1 : s + 1) / Math.sqrt(varS);
  const slope = n >= 2 ? (values[n - 1] - values[0]) / (n - 1) : 0;
  return { hasTrend: Math.abs(z) > 1.96, slope };
}

export function autocorrelation(values: number[], lag: number): number {
  if (lag <= 0 || lag >= values.length) return 0;
  const m = mean(values);
  let num = 0;
  let den = 0;
  for (let i = 0; i < values.length; i++) {
    den += (values[i] - m) ** 2;
    if (i >= lag) num += (values[i] - m) * (values[i - lag] - m);
  }
  return den === 0 ? 0 : num / den;
}

export function seasonalStrength(values: number[], period: number): number {
  if (period < 2 || values.length < period * 2) return 0;
  const seasons = Array.from({ length: period }, () => [] as number[]);
  values.forEach((v, i) => seasons[i % period].push(v));
  const seasonal = seasons.map((s) => mean(s));
  const seasMean = mean(seasonal);
  const centered = seasonal.map((s) => s - seasMean);
  const remainder: number[] = [];
  const seasonalComp: number[] = [];
  values.forEach((v, i) => {
    const s = centered[i % period];
    seasonalComp.push(s);
    remainder.push(v - s - mean(values));
  });
  const varR = variance(remainder);
  const varSR = variance(seasonalComp.map((s, i) => s + remainder[i]));
  if (varSR <= 0) return 0;
  return Math.max(0, Math.min(1, 1 - varR / varSR));
}

export function adiCv2(actualOrForecast: number[]): { adi: number; cv2: number; intermittency: IntermittencyClass } {
  const xs = actualOrForecast;
  if (xs.length === 0) return { adi: 1, cv2: 0, intermittency: "smooth" };
  const nz = xs.filter((x) => x > 0);
  const adi = nz.length === 0 ? xs.length : xs.length / nz.length;
  const cv2 = nz.length < 2 ? 0 : (stdev(nz) / mean(nz)) ** 2;
  const highAdi = adi > 1.32;
  const highCv = cv2 > 0.49;
  let intermittency: IntermittencyClass = "smooth";
  if (!highAdi && highCv) intermittency = "erratic";
  else if (highAdi && !highCv) intermittency = "intermittent";
  else if (highAdi && highCv) intermittency = "lumpy";
  return { adi, cv2, intermittency };
}

export function profileSeries(points: ForecastPoint[]): SeriesProfile {
  const sorted = sortPoints(points);
  const dates = sorted.map((p) => p.date);
  const { cadence, stepDays } = inferCadence(dates);
  const demand = sorted.map((p) => (p.actual !== undefined ? p.actual : p.forecast));
  const actuals = sorted.filter((p) => p.actual !== undefined).map((p) => p.actual as number);
  const basis = actuals.length >= 4 ? actuals : demand;
  const period = seasonalPeriodFor(cadence, basis.length);
  const mk = mannKendall(basis);
  const { adi, cv2, intermittency } = adiCv2(basis);
  const m = mean(basis);
  const cv = m === 0 ? 0 : stdev(basis) / Math.abs(m);
  const spikes = basis.filter((v) => Math.abs(v - m) > 3 * (stdev(basis) || 1)).length;
  return {
    n: sorted.length,
    cadence,
    stepDays,
    seasonalPeriod: period,
    hasTrend: mk.hasTrend,
    trendSlope: mk.slope,
    seasonalStrength: seasonalStrength(basis, period),
    intermittency,
    adi,
    cv2,
    meanDemand: m,
    cv,
    isNewProduct: sorted.length < 16,
    promotionsLikely: spikes >= 3,
  };
}

export function fillDateGrid(start: Date, end: Date, stepDays: number): string[] {
  const out: string[] = [];
  const cur = new Date(start.getTime());
  while (cur.getTime() <= end.getTime() + 86400000 * 0.4) {
    out.push(toIsoDate(cur));
    cur.setUTCDate(cur.getUTCDate() + stepDays);
  }
  return out;
}
