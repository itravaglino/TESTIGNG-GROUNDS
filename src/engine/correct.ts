import type { Correction, Point } from "./types";
import { inferFrequency } from "./quality";
import { median, quantile } from "./metrics";

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function addPeriod(d: Date, freq: ReturnType<typeof inferFrequency>): Date {
  const x = new Date(d.getTime());
  if (freq === "daily") x.setUTCDate(x.getUTCDate() + 1);
  else if (freq === "weekly") x.setUTCDate(x.getUTCDate() + 7);
  else if (freq === "quarterly") x.setUTCMonth(x.getUTCMonth() + 3);
  else x.setUTCMonth(x.getUTCMonth() + 1);
  return x;
}

function interpolate(values: (number | null)[]): (number | null)[] {
  const out = [...values];
  let i = 0;
  while (i < out.length) {
    if (out[i] !== null) {
      i++;
      continue;
    }
    let j = i;
    while (j < out.length && out[j] === null) j++;
    const left = i > 0 ? out[i - 1] : null;
    const right = j < out.length ? out[j] : null;
    if (left === null && right === null) {
      i = j;
      continue;
    }
    if (left === null) {
      for (let k = i; k < j; k++) out[k] = right;
    } else if (right === null) {
      for (let k = i; k < j; k++) out[k] = left;
    } else {
      const span = j - i + 1;
      for (let k = i; k < j; k++) {
        const t = (k - (i - 1)) / span;
        out[k] = left + t * (right - left);
      }
    }
    i = j;
  }
  return out;
}

export function correctSeries(input: Point[]): { series: Point[]; corrections: Correction[] } {
  const corrections: Correction[] = [];
  const bump = (id: string, message: string, n = 1) => {
    const existing = corrections.find((c) => c.id === id);
    if (existing) existing.count += n;
    else corrections.push({ id, message, count: n });
  };

  const byDate = new Map<string, Point>();
  const ordered = [...input].sort((a, b) => a.period.getTime() - b.period.getTime());
  let dups = 0;
  for (const p of ordered) {
    if (byDate.has(p.date)) dups++;
    byDate.set(p.date, { ...p });
  }
  if (dups) bump("dedupe", "Fechas duplicadas: me quedé con la última fila", dups);

  let points = [...byDate.values()].sort((a, b) => a.period.getTime() - b.period.getTime());
  const freq = inferFrequency(points.map((p) => p.period));

  if (points.length >= 2) {
    const filled: Point[] = [];
    for (let i = 0; i < points.length; i++) {
      filled.push(points[i]!);
      if (i === points.length - 1) break;
      let cursor = addPeriod(points[i]!.period, freq);
      let guard = 0;
      while (cursor.getTime() < points[i + 1]!.period.getTime() - 86400000 * 0.4 && guard < 36) {
        filled.push({
          date: ymd(cursor),
          period: new Date(cursor.getTime()),
          forecastRaw: null,
          forecast: null,
          actual: 0,
          lower: null,
          upper: null,
        });
        bump("fill_gap", "Hueco de calendario completado (real=0, forecast a interpolar)");
        cursor = addPeriod(cursor, freq);
        guard++;
      }
    }
    points = filled;
  }

  let neg = 0;
  for (const p of points) {
    if (p.forecast !== null && p.forecast < 0) {
      p.forecast = 0;
      neg++;
    }
    if (p.actual !== null && p.actual < 0) {
      p.actual = 0;
      neg++;
    }
  }
  if (neg) bump("clip_neg", "Valores negativos recortados a 0", neg);

  const fcs = interpolate(points.map((p) => p.forecast));
  let interp = 0;
  points.forEach((p, i) => {
    if (p.forecast === null && fcs[i] !== null) {
      p.forecast = fcs[i]!;
      interp++;
    }
  });
  if (interp) bump("interpolate", "Pronósticos vacíos interpolados", interp);

  const vals = points.map((p) => p.forecast).filter((x): x is number => x !== null);
  if (vals.length >= 8) {
    const q1 = quantile(vals, 0.25)!;
    const q3 = quantile(vals, 0.75)!;
    const iqr = q3 - q1;
    const lo = q1 - 1.5 * iqr;
    const hi = q3 + 1.5 * iqr;
    const med = median(vals)!;
    const mad = median(vals.map((x) => Math.abs(x - med))) ?? 0;
    let wins = 0;
    for (const p of points) {
      if (p.forecast === null) continue;
      const z = mad === 0 ? 0 : (0.6745 * (p.forecast - med)) / mad;
      let v = p.forecast;
      if (v < lo) v = lo;
      if (v > hi) v = hi;
      if (Math.abs(z) > 3.5) v = Math.max(lo, Math.min(hi, v));
      if (v !== p.forecast) {
        p.forecast = v;
        wins++;
      }
    }
    if (wins) bump("winsor", "Outliers recortados (winsor IQR / z modificado)", wins);
  }

  const actuals = points.map((p) => p.actual).filter((x): x is number => x !== null);
  if (actuals.length >= 6) {
    const cap = 3 * Math.max(...actuals);
    let caps = 0;
    for (const p of points) {
      if (p.forecast !== null && p.forecast > cap) {
        p.forecast = cap;
        caps++;
      }
    }
    if (caps) bump("cap_max", `Pronóstico limitado a 3× el máximo real (${cap.toFixed(1)})`, caps);
  }

  const origInt = input.every(
    (p) => p.forecast === null || Math.abs(p.forecast - Math.round(p.forecast)) < 1e-6,
  );
  if (origInt) {
    let rnd = 0;
    for (const p of points) {
      if (p.forecast !== null) {
        const r = Math.round(p.forecast);
        if (r !== p.forecast) {
          p.forecast = r;
          rnd++;
        }
      }
    }
    if (rnd) bump("round", "Redondeo a enteros porque el original era entero", rnd);
  }

  return { series: points, corrections };
}
