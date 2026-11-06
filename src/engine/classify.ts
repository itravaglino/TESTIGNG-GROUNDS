import type { DemandClass, Point } from "./types";
import { acf, guessSeasonalLag, mean, stdev } from "./metrics";

export function classifyDemand(actuals: number[]): {
  demandClass: DemandClass;
  adi: number | null;
  cv2: number | null;
} {
  if (actuals.length < 4) return { demandClass: "unknown", adi: null, cv2: null };
  const nz = actuals.filter((x) => x > 0);
  const adi = nz.length === 0 ? Infinity : actuals.length / nz.length;
  const m = mean(nz);
  const s = stdev(nz);
  const cv2 = m && s !== null ? (s / m) ** 2 : null;
  let demandClass: DemandClass = "unknown";
  if (adi !== Infinity && cv2 !== null) {
    if (adi < 1.32 && cv2 < 0.49) demandClass = "smooth";
    else if (adi >= 1.32 && cv2 < 0.49) demandClass = "intermittent";
    else if (adi < 1.32 && cv2 >= 0.49) demandClass = "erratic";
    else demandClass = "lumpy";
  } else if (adi === Infinity) demandClass = "intermittent";
  return { demandClass, adi: Number.isFinite(adi) ? adi : null, cv2 };
}

export function detectSeasonality(values: number[]): number | null {
  const lag = guessSeasonalLag(values.length);
  if (!lag) return null;
  const candidates = [...new Set([lag, 7, 12, 13, 52])].filter((l) => values.length > l * 2);
  let best: { lag: number; ac: number } | null = null;
  for (const l of candidates) {
    const ac = acf(values, l);
    if (ac === null) continue;
    if (!best || Math.abs(ac) > Math.abs(best.ac)) best = { lag: l, ac };
  }
  if (best && Math.abs(best.ac) >= 0.25) return best.lag;
  return null;
}

export function detectTrend(values: number[]): boolean {
  if (values.length < 8) return false;
  const n = values.length;
  const xs = values.map((_, i) => i);
  const mx = mean(xs)!;
  const my = mean(values)!;
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i]! - mx) * (values[i]! - my);
    den += (xs[i]! - mx) ** 2;
  }
  if (den === 0) return false;
  const slope = num / den;
  const sd = stdev(values) ?? 0;
  return Math.abs(slope) * n > 0.35 * Math.max(sd, Math.abs(my) * 0.05, 1e-6);
}

export function seriesValues(series: Point[], field: "forecast" | "actual"): number[] {
  return series.map((p) => p[field]).filter((x): x is number => x !== null);
}
