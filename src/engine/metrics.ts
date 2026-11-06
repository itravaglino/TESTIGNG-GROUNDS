import { seasonLag } from "./dates";
import type { MetricValue, Pair, PeriodType } from "./types";
import { EPS } from "./types";

export function quantile(sorted: number[], p: number): number {
  const n = sorted.length;
  if (n === 0) return NaN;
  if (n === 1) return sorted[0];
  const h = 1 + (n - 1) * p;
  const lo = Math.floor(h);
  const hi = Math.ceil(h);
  const a = sorted[lo - 1];
  const b = sorted[hi - 1];
  if (lo === hi) return a;
  return a * (1 - (h - lo)) + b * (h - lo);
}

export function mean(xs: number[]): number | null {
  if (!xs.length) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return quantile(s, 0.5);
}

export function stdev(xs: number[]): number | null {
  if (xs.length < 2) return null;
  const m = mean(xs)!;
  const v = xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1);
  return Math.sqrt(v);
}

function metric(
  id: string,
  name: string,
  value: number | null,
  unit: MetricValue["unit"],
  lowerIsBetter: boolean | null,
  note?: string,
): MetricValue {
  const defined = value != null && Number.isFinite(value);
  return { id, name, value: defined ? value : null, unit, lowerIsBetter, defined, note };
}

export function computeMetrics(pairs: Pair[], periodType: PeriodType, allActuals: number[]): MetricValue[] {
  const n = pairs.length;
  const errors = pairs.map((p) => p.forecast - p.actual);
  const abs = errors.map(Math.abs);
  const sq = errors.map((e) => e * e);
  const y = pairs.map((p) => p.actual);
  const f = pairs.map((p) => p.forecast);
  const sumY = y.reduce((a, b) => a + b, 0);
  const sumAbsY = y.reduce((a, b) => a + Math.abs(b), 0);
  const mae = mean(abs);
  const mse = mean(sq);
  const rmse = mse != null ? Math.sqrt(mse) : null;
  const me = mean(errors);

  const mapeParts = pairs.filter((p) => Math.abs(p.actual) > EPS).map((p) => Math.abs(p.forecast - p.actual) / Math.abs(p.actual));
  const mape = mapeParts.length ? mean(mapeParts)! * 100 : null;

  const smapeParts = pairs
    .map((p) => {
      const den = Math.abs(p.actual) + Math.abs(p.forecast);
      return den > EPS ? (2 * Math.abs(p.forecast - p.actual)) / den : null;
    })
    .filter((x): x is number => x != null);
  const smape = smapeParts.length ? mean(smapeParts)! * 100 : null;

  const wape = sumAbsY > EPS ? (abs.reduce((a, b) => a + b, 0) / sumAbsY) * 100 : null;
  const mdape = mapeParts.length ? median(mapeParts.map((x) => x * 100)) : null;
  const pbias = sumY !== 0 && Math.abs(sumY) > EPS ? (errors.reduce((a, b) => a + b, 0) / sumY) * 100 : null;

  const lag = seasonLag(periodType);
  const mase = seasonalMase(pairs, allActuals, lag);
  const rmsse = seasonalRmsse(pairs, allActuals, lag);
  const theil = theilU2(pairs, allActuals);
  const seasonalTheil = theilU2Seasonal(pairs, allActuals, lag);

  const mad = median(abs);
  const ts = mad != null && mad > EPS ? errors.reduce((a, b) => a + b, 0) / mad : null;
  const r2 = rSquared(y, f);
  const corr = pearson(y, f);
  const hit = hitRate(pairs);
  const maape = mean(
    pairs.map((p) => Math.atan(Math.abs(p.forecast - p.actual) / Math.max(Math.abs(p.actual), EPS))),
  );
  const naiveMae = naiveScale(allActuals);
  const relmae = mae != null && naiveMae != null && naiveMae > EPS ? mae / naiveMae : null;
  const nmse = mse != null && mean(y.map((v) => v * v)) != null && mean(y.map((v) => v * v))! > EPS ? mse / mean(y.map((v) => v * v))! : null;
  const madMean = mae != null && mean(y.map(Math.abs)) != null && mean(y.map(Math.abs))! > EPS ? mae / mean(y.map(Math.abs))! : null;
  const cvErr = mae != null && stdev(errors) != null && mae > EPS ? stdev(errors)! / mae : stdev(errors);
  const maxAe = abs.length ? Math.max(...abs) : null;
  const large = y.length ? (pairs.filter((p) => Math.abs(p.actual) > EPS && Math.abs(p.forecast - p.actual) / Math.abs(p.actual) > 0.5).length / n) * 100 : null;
  const over = n ? (pairs.filter((p) => p.forecast > p.actual + EPS).length / n) * 100 : null;
  const fill = fillRate(pairs);
  const pinball = pinballLoss(pairs);
  const coverage = coverageRate(pairs);
  const rmsePct = rmse != null && mean(y.map(Math.abs)) != null && mean(y.map(Math.abs))! > EPS ? (rmse / mean(y.map(Math.abs))!) * 100 : null;
  const gmrae = gmraeOf(pairs, allActuals);

  const mapeNote = mape == null ? "Indefinido con ceros o sin pares con real distinto de cero. No usar para demanda intermitente." : undefined;

  return [
    metric("n_pairs", "Pares evaluados", n, "count", null),
    metric("mae", "MAE", mae, "units", true),
    metric("mse", "MSE", mse, "units", true),
    metric("rmse", "RMSE", rmse, "units", true),
    metric("rmse_pct", "RMSE %", rmsePct, "percent", true),
    metric("mape", "MAPE", mape, "percent", true, mapeNote),
    metric("smape", "sMAPE", smape, "percent", true),
    metric("wape", "WAPE", wape, "percent", true),
    metric("mdape", "MdAPE", mdape, "percent", true),
    metric("maape", "MAAPE", maape != null ? maape * 100 : null, "percent", true),
    metric("me", "Sesgo (ME)", me, "units", null),
    metric("pbias", "Sesgo porcentual", pbias, "percent", null),
    metric("tracking_signal", "Señal de rastreo", ts, "ratio", null),
    metric("mase", "MASE", mase, "ratio", true),
    metric("rmsse", "RMSSE", rmsse, "ratio", true),
    metric("relmae", "RelMAE vs ingenuo", relmae, "ratio", true),
    metric("theil_u2", "Theil U2 vs ingenuo", theil, "ratio", true),
    metric("theil_u2_seasonal", "Theil U2 vs ingenuo estacional", seasonalTheil, "ratio", true),
    metric("gmrae", "GMRAE", gmrae, "ratio", true),
    metric("r2", "R²", r2, "ratio", false),
    metric("corr", "Correlación", corr, "ratio", false),
    metric("hit_rate", "Acierto de dirección", hit, "percent", false),
    metric("nmse", "NMSE", nmse, "ratio", true),
    metric("mad_mean", "MAE / media", madMean, "ratio", true),
    metric("cv_error", "CV del error", cvErr, "ratio", true),
    metric("max_ae", "Error absoluto máximo", maxAe, "units", true),
    metric("pct_large_error", "Periodos con |error| > 50%", large, "percent", true),
    metric("pct_overforecast", "Periodos sobrepronosticados", over, "percent", null),
    metric("fill_rate", "Fill rate proxy", fill, "percent", false),
    metric("pinball", "Pinball 0.5 / cobertura", pinball, "units", true),
    metric("coverage", "Cobertura del intervalo", coverage, "percent", null),
  ];
}

function seasonalMase(pairs: Pair[], actuals: number[], lag: number): number | null {
  const mae = mean(pairs.map((p) => Math.abs(p.forecast - p.actual)));
  const scale = seasonalNaiveMae(actuals, lag);
  if (mae == null || scale == null || scale <= EPS) return null;
  return mae / scale;
}

function seasonalRmsse(pairs: Pair[], actuals: number[], lag: number): number | null {
  const mse = mean(pairs.map((p) => (p.forecast - p.actual) ** 2));
  const diffs: number[] = [];
  for (let i = lag; i < actuals.length; i++) diffs.push((actuals[i] - actuals[i - lag]) ** 2);
  const scale = mean(diffs);
  if (mse == null || scale == null || scale <= EPS) return null;
  return Math.sqrt(mse / scale);
}

function seasonalNaiveMae(actuals: number[], lag: number): number | null {
  const diffs: number[] = [];
  for (let i = lag; i < actuals.length; i++) diffs.push(Math.abs(actuals[i] - actuals[i - lag]));
  if (diffs.length === 0) {
    const naive: number[] = [];
    for (let i = 1; i < actuals.length; i++) naive.push(Math.abs(actuals[i] - actuals[i - 1]));
    return mean(naive);
  }
  return mean(diffs);
}

function naiveScale(actuals: number[]): number | null {
  const diffs: number[] = [];
  for (let i = 1; i < actuals.length; i++) diffs.push(Math.abs(actuals[i] - actuals[i - 1]));
  return mean(diffs);
}

function theilU2(pairs: Pair[], actuals: number[]): number | null {
  if (pairs.length < 1 || actuals.length < 2) return null;
  const last = actuals[actuals.length - 2] ?? actuals[0];
  const num = mean(pairs.map((p) => (p.forecast - p.actual) ** 2));
  const den = mean(pairs.map((p) => (last - p.actual) ** 2));
  if (num == null || den == null || den <= EPS) return null;
  return Math.sqrt(num / den);
}

function theilU2Seasonal(pairs: Pair[], actuals: number[], lag: number): number | null {
  if (actuals.length <= lag) return theilU2(pairs, actuals);
  const num = mean(pairs.map((p) => (p.forecast - p.actual) ** 2));
  const denParts: number[] = [];
  for (const p of pairs) {
    const idx = actuals.length - 1;
    const seasonal = actuals[Math.max(0, idx - lag)];
    denParts.push((seasonal - p.actual) ** 2);
  }
  const den = mean(denParts);
  if (num == null || den == null || den <= EPS) return null;
  return Math.sqrt(num / den);
}

function rSquared(y: number[], f: number[]): number | null {
  if (y.length < 2) return null;
  const my = mean(y)!;
  const ssTot = y.reduce((a, v) => a + (v - my) ** 2, 0);
  const ssRes = y.reduce((a, v, i) => a + (v - f[i]) ** 2, 0);
  if (ssTot <= EPS) return null;
  return 1 - ssRes / ssTot;
}

function pearson(y: number[], f: number[]): number | null {
  if (y.length < 3) return null;
  const my = mean(y)!;
  const mf = mean(f)!;
  let num = 0;
  let dy = 0;
  let df = 0;
  for (let i = 0; i < y.length; i++) {
    num += (y[i] - my) * (f[i] - mf);
    dy += (y[i] - my) ** 2;
    df += (f[i] - mf) ** 2;
  }
  if (dy <= EPS || df <= EPS) return null;
  return num / Math.sqrt(dy * df);
}

function hitRate(pairs: Pair[]): number | null {
  if (pairs.length < 2) return null;
  let ok = 0;
  let n = 0;
  for (let i = 1; i < pairs.length; i++) {
    const dy = pairs[i].actual - pairs[i - 1].actual;
    const df = pairs[i].forecast - pairs[i - 1].forecast;
    if (Math.abs(dy) <= EPS) continue;
    n += 1;
    if (Math.sign(dy) === Math.sign(df)) ok += 1;
  }
  return n ? (ok / n) * 100 : null;
}

function fillRate(pairs: Pair[]): number | null {
  const demand = pairs.reduce((a, p) => a + Math.max(p.actual, 0), 0);
  if (demand <= EPS) return null;
  const filled = pairs.reduce((a, p) => a + Math.min(Math.max(p.forecast, 0), Math.max(p.actual, 0)), 0);
  return (filled / demand) * 100;
}

function pinballLoss(pairs: Pair[]): number | null {
  const withQ = pairs.filter((p) => p.lo != null && p.hi != null);
  if (!withQ.length) return null;
  const tau = 0.5;
  return mean(withQ.map((p) => {
    const e = p.actual - p.forecast;
    return e >= 0 ? tau * e : (tau - 1) * e;
  }));
}

function coverageRate(pairs: Pair[]): number | null {
  const withQ = pairs.filter((p) => p.lo != null && p.hi != null);
  if (!withQ.length) return null;
  return (withQ.filter((p) => p.actual >= p.lo! && p.actual <= p.hi!).length / withQ.length) * 100;
}

function gmraeOf(pairs: Pair[], actuals: number[]): number | null {
  if (actuals.length < 2 || pairs.length === 0) return null;
  const ratios: number[] = [];
  for (let i = 0; i < pairs.length; i++) {
    const naive = i === 0 ? Math.abs(actuals[0] ?? 0) : Math.abs(pairs[i].actual - pairs[Math.max(0, i - 1)].actual);
    const ae = Math.abs(pairs[i].forecast - pairs[i].actual);
    if (naive > EPS) ratios.push(ae / naive);
  }
  if (!ratios.length) return null;
  const log = mean(ratios.map((r) => Math.log(r)));
  return log == null ? null : Math.exp(log);
}

export function metricMap(metrics: MetricValue[]): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const m of metrics) out[m.id] = m.value;
  return out;
}
