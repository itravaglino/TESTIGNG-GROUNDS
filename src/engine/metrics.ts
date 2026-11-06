import type { MetricValue, Point } from "./types";

export function mean(xs: number[]): number | null {
  if (xs.length === 0) return null;
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function stdev(xs: number[]): number | null {
  if (xs.length < 2) return null;
  const m = mean(xs)!;
  const v = xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1);
  return Math.sqrt(v);
}

export function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid]! : (s[mid - 1]! + s[mid]!) / 2;
}

export function quantile(xs: number[], q: number): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return s[lo]!;
  return s[lo]! * (hi - pos) + s[hi]! * (pos - lo);
}

export interface Pair {
  f: number;
  a: number;
}

export function pairs(series: Point[]): Pair[] {
  const out: Pair[] = [];
  for (const p of series) {
    if (p.forecast !== null && p.actual !== null && Number.isFinite(p.forecast) && Number.isFinite(p.actual)) {
      out.push({ f: p.forecast, a: p.actual });
    }
  }
  return out;
}

function m(id: string, label: string, value: number | null, unit: MetricValue["unit"], better: MetricValue["better"], note?: string): MetricValue {
  return { id, label, value: value !== null && Number.isFinite(value) ? value : null, unit, better, note };
}

export function maeOf(ps: Pair[]): number | null {
  if (ps.length === 0) return null;
  return mean(ps.map((p) => Math.abs(p.f - p.a)));
}

export function mseOf(ps: Pair[]): number | null {
  if (ps.length === 0) return null;
  return mean(ps.map((p) => (p.f - p.a) ** 2));
}

export function mapeOf(ps: Pair[]): number | null {
  const ok = ps.filter((p) => p.a !== 0);
  if (ok.length === 0) return null;
  return mean(ok.map((p) => Math.abs(p.f - p.a) / Math.abs(p.a)))! * 100;
}

export function smapeOf(ps: Pair[]): number | null {
  const ok = ps.filter((p) => Math.abs(p.f) + Math.abs(p.a) !== 0);
  if (ok.length === 0) return null;
  return mean(ok.map((p) => (200 * Math.abs(p.f - p.a)) / (Math.abs(p.f) + Math.abs(p.a))));
}

export function wapeOf(ps: Pair[]): number | null {
  const den = ps.reduce((s, p) => s + Math.abs(p.a), 0);
  if (den === 0) return null;
  return (ps.reduce((s, p) => s + Math.abs(p.f - p.a), 0) / den) * 100;
}

export function maseOf(ps: Pair[], actualsInOrder: number[]): number | null {
  const mae = maeOf(ps);
  if (mae === null || actualsInOrder.length < 2) return null;
  let naive = 0;
  let n = 0;
  for (let i = 1; i < actualsInOrder.length; i++) {
    naive += Math.abs(actualsInOrder[i]! - actualsInOrder[i - 1]!);
    n++;
  }
  if (n === 0 || naive === 0) return null;
  return mae / (naive / n);
}

export function computeMetrics(series: Point[]): MetricValue[] {
  const ps = pairs(series);
  const actuals = series.map((s) => s.actual).filter((x): x is number => x !== null);
  const n = ps.length;
  if (n === 0) {
    return [
      m("n_eval", "Puntos evaluables", 0, "none", "high", "Sin pares pronóstico–real"),
    ];
  }

  const mae = maeOf(ps);
  const mse = mseOf(ps);
  const rmse = mse === null ? null : Math.sqrt(mse);
  const mape = mapeOf(ps);
  const smape = smapeOf(ps);
  const wape = wapeOf(ps);
  const mdape = (() => {
    const ok = ps.filter((p) => p.a !== 0).map((p) => (100 * Math.abs(p.f - p.a)) / Math.abs(p.a));
    return median(ok);
  })();
  const mbe = mean(ps.map((p) => p.f - p.a));
  const pbias = (() => {
    const den = ps.reduce((s, p) => s + p.a, 0);
    if (den === 0) return null;
    return (100 * ps.reduce((s, p) => s + (p.f - p.a), 0)) / den;
  })();
  const tracking = (() => {
    if (mae === null || mae === 0 || mbe === null) return null;
    const cum = ps.reduce((s, p) => s + (p.f - p.a), 0);
    return cum / mae;
  })();
  const meanA = mean(ps.map((p) => p.a));
  const meanF = mean(ps.map((p) => p.f));
  const corr = (() => {
    if (n < 3 || meanA === null || meanF === null) return null;
    let num = 0;
    let da = 0;
    let df = 0;
    for (const p of ps) {
      num += (p.a - meanA) * (p.f - meanF);
      da += (p.a - meanA) ** 2;
      df += (p.f - meanF) ** 2;
    }
    if (da === 0 || df === 0) return null;
    return num / Math.sqrt(da * df);
  })();
  const r2 = (() => {
    if (meanA === null || n < 3) return null;
    const ssTot = ps.reduce((s, p) => s + (p.a - meanA) ** 2, 0);
    if (ssTot === 0) return null;
    const ssRes = ps.reduce((s, p) => s + (p.a - p.f) ** 2, 0);
    return 1 - ssRes / ssTot;
  })();
  const rmsePct = rmse !== null && meanA ? (100 * rmse) / Math.abs(meanA) : null;
  const maePct = mae !== null && meanA ? (100 * mae) / Math.abs(meanA) : null;
  const nrmse = (() => {
    if (rmse === null) return null;
    const mn = Math.min(...ps.map((p) => p.a));
    const mx = Math.max(...ps.map((p) => p.a));
    if (mx === mn) return null;
    return rmse / (mx - mn);
  })();
  const hit10 = (100 * ps.filter((p) => p.a !== 0 && Math.abs(p.f - p.a) / Math.abs(p.a) <= 0.1).length) / n;
  const hit20 = (100 * ps.filter((p) => p.a !== 0 && Math.abs(p.f - p.a) / Math.abs(p.a) <= 0.2).length) / n;
  const dirAcc = (() => {
    if (n < 2) return null;
    let ok = 0;
    let tot = 0;
    for (let i = 1; i < n; i++) {
      const da = ps[i]!.a - ps[i - 1]!.a;
      const df = ps[i]!.f - ps[i - 1]!.f;
      if (da === 0 && df === 0) continue;
      tot++;
      if (da === 0 || df === 0) continue;
      if (Math.sign(da) === Math.sign(df)) ok++;
    }
    return tot === 0 ? null : (100 * ok) / tot;
  })();
  const theilU1 = (() => {
    const rmseF = rmse;
    const rmsA = Math.sqrt(mean(ps.map((p) => p.a ** 2)) ?? 0);
    const rmsFc = Math.sqrt(mean(ps.map((p) => p.f ** 2)) ?? 0);
    const den = rmsA + rmsFc;
    if (!rmseF || den === 0) return null;
    return rmseF / den;
  })();
  const theilU2 = (() => {
    let num = 0;
    let den = 0;
    for (let i = 1; i < n; i++) {
      if (ps[i - 1]!.a === 0) continue;
      num += ((ps[i]!.f - ps[i]!.a) / ps[i - 1]!.a) ** 2;
      den += ((ps[i]!.a - ps[i - 1]!.a) / ps[i - 1]!.a) ** 2;
    }
    if (den === 0) return null;
    return Math.sqrt(num / den);
  })();
  const mase = maseOf(ps, actuals);
  const rmsse = (() => {
    if (actuals.length < 2 || rmse === null) return null;
    let s = 0;
    for (let i = 1; i < actuals.length; i++) s += (actuals[i]! - actuals[i - 1]!) ** 2;
    const scale = Math.sqrt(s / (actuals.length - 1));
    if (scale === 0) return null;
    return rmse / scale;
  })();
  const naivePairs: Pair[] = [];
  for (let i = 1; i < series.length; i++) {
    const prev = series[i - 1]!.actual;
    const a = series[i]!.actual;
    if (prev !== null && a !== null) naivePairs.push({ f: prev, a });
  }
  const maeNaive = maeOf(naivePairs);
  const skillNaive = mae !== null && maeNaive && maeNaive !== 0 ? 1 - mae / maeNaive : null;
  const seasonal = guessSeasonalLag(series.length);
  const snaivePairs: Pair[] = [];
  if (seasonal) {
    for (let i = seasonal; i < series.length; i++) {
      const prev = series[i - seasonal]!.actual;
      const a = series[i]!.actual;
      if (prev !== null && a !== null) snaivePairs.push({ f: prev, a });
    }
  }
  const maeSnaive = maeOf(snaivePairs);
  const skillSnaive = mae !== null && maeSnaive && maeSnaive !== 0 ? 1 - mae / maeSnaive : null;
  const gmape = (() => {
    const ok = ps.filter((p) => p.a > 0 && p.f > 0);
    if (ok.length === 0) return null;
    const logs = ok.map((p) => Math.log(Math.abs(p.f / p.a)));
    const g = Math.exp(mean(logs.map(Math.abs))!);
    return (g - 1) * 100;
  })();
  const msle = (() => {
    const ok = ps.filter((p) => p.a > -1 && p.f > -1 && p.a + 1 > 0 && p.f + 1 > 0);
    if (ok.length === 0) return null;
    return mean(ok.map((p) => (Math.log1p(p.f) - Math.log1p(p.a)) ** 2));
  })();
  const biasRatio = meanA ? (meanF ?? 0) / meanA : null;
  const coverage = (() => {
    const band = series.filter((s) => s.actual !== null && s.lower !== null && s.upper !== null);
    if (band.length === 0) return null;
    return (100 * band.filter((s) => s.actual! >= s.lower! && s.actual! <= s.upper!).length) / band.length;
  })();
  const intervalWidth = (() => {
    const band = series.filter((s) => s.lower !== null && s.upper !== null);
    if (band.length === 0) return null;
    return mean(band.map((s) => s.upper! - s.lower!));
  })();
  const pinball = (() => {
    // 0.5 pinball = 0.5 * MAE
    return mae === null ? null : 0.5 * mae;
  })();

  return [
    m("n_eval", "Puntos evaluables", n, "none", "high"),
    m("mae", "MAE", mae, "qty", "low", "Error absoluto medio"),
    m("mse", "MSE", mse, "qty", "low"),
    m("rmse", "RMSE", rmse, "qty", "low"),
    m("mape", "MAPE", mape, "pct", "low", "Omite reales = 0"),
    m("smape", "sMAPE", smape, "pct", "low"),
    m("wape", "WAPE", wape, "pct", "low", "Ponderado por volumen"),
    m("mdape", "MdAPE", mdape, "pct", "low"),
    m("mae_pct", "MAE%", maePct, "pct", "low"),
    m("rmse_pct", "RMSE%", rmsePct, "pct", "low"),
    m("nrmse", "NRMSE", nrmse, "ratio", "low"),
    m("mase", "MASE", mase, "ratio", "low", "<1 supera al naive"),
    m("rmsse", "RMSSE", rmsse, "ratio", "low"),
    m("mbe", "Sesgo (MBE)", mbe, "qty", "zero", ">0 sobrepronostica"),
    m("pbias", "Sesgo %", pbias, "pct", "zero"),
    m("bias_ratio", "Ratio forecast/real", biasRatio, "ratio", "zero"),
    m("tracking_signal", "Tracking signal", tracking, "ratio", "zero", "|TS|>4 inestable"),
    m("corr", "Correlación", corr, "ratio", "high"),
    m("r2", "R²", r2, "ratio", "high"),
    m("theil_u1", "Theil U1", theilU1, "ratio", "low"),
    m("theil_u2", "Theil U2", theilU2, "ratio", "low", "<1 mejor que naive"),
    m("dir_acc", "Acierto direccional", dirAcc, "pct", "high"),
    m("hit10", "Hit ±10%", hit10, "pct", "high"),
    m("hit20", "Hit ±20%", hit20, "pct", "high"),
    m("skill_naive", "Skill vs naive", skillNaive, "ratio", "high", "1 = perfecto, 0 = naive"),
    m("skill_snaive", "Skill vs naive estacional", skillSnaive, "ratio", "high"),
    m("gmape", "GMAPE", gmape, "pct", "low"),
    m("msle", "MSLE", msle, "qty", "low"),
    m("pinball_50", "Pinball 50%", pinball, "qty", "low"),
    m("coverage", "Cobertura intervalo", coverage, "pct", "high"),
    m("interval_width", "Ancho de intervalo", intervalWidth, "qty", "low"),
  ];
}

export function guessSeasonalLag(n: number): number | null {
  if (n >= 104) return 52;
  if (n >= 24) return 12;
  if (n >= 14) return 7;
  return null;
}

export function acf(xs: number[], lag: number): number | null {
  if (xs.length <= lag + 2) return null;
  const m = mean(xs);
  if (m === null) return null;
  let num = 0;
  let den = 0;
  for (let i = 0; i < xs.length; i++) {
    den += (xs[i]! - m) ** 2;
    if (i >= lag) num += (xs[i]! - m) * (xs[i - lag]! - m);
  }
  if (den === 0) return null;
  return num / den;
}
