export function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value);
}

export function mean(values: number[]): number | null {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function quantile(values: number[], q: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] * (hi - pos) + sorted[hi] * (pos - lo);
}

export function stdev(values: number[]): number | null {
  if (values.length < 2) return null;
  const avg = mean(values);
  if (avg == null) return null;
  const variance = values.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

export function pearson(xs: number[], ys: number[]): number | null {
  if (xs.length !== ys.length || xs.length < 3) return null;
  const mx = mean(xs);
  const my = mean(ys);
  if (mx == null || my == null) return null;
  let num = 0;
  let dx = 0;
  let dy = 0;
  for (let i = 0; i < xs.length; i += 1) {
    const a = xs[i] - mx;
    const b = ys[i] - my;
    num += a * b;
    dx += a * a;
    dy += b * b;
  }
  if (dx === 0 || dy === 0) return null;
  return num / Math.sqrt(dx * dy);
}

export function acf(values: number[], lag: number): number | null {
  if (lag < 1 || values.length <= lag + 2) return null;
  const avg = mean(values);
  if (avg == null) return null;
  let denom = 0;
  for (const value of values) denom += (value - avg) ** 2;
  if (denom === 0) return null;
  let num = 0;
  for (let i = lag; i < values.length; i += 1) num += (values[i] - avg) * (values[i - lag] - avg);
  return num / denom;
}

export function pairsOf(
  forecast: Array<number | null>,
  actual: Array<number | null>,
): Array<[number, number]> {
  const pairs: Array<[number, number]> = [];
  const n = Math.min(forecast.length, actual.length);
  for (let i = 0; i < n; i += 1) {
    if (finite(forecast[i]) && finite(actual[i])) pairs.push([forecast[i] as number, actual[i] as number]);
  }
  return pairs;
}

export function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}
