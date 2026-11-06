import type { Issue, Point } from "./types";
import { median, quantile } from "./metrics";

export function inferFrequency(dates: Date[]): "daily" | "weekly" | "monthly" | "quarterly" | "unknown" {
  if (dates.length < 2) return "unknown";
  const diffs: number[] = [];
  const sorted = [...dates].sort((a, b) => a.getTime() - b.getTime());
  for (let i = 1; i < sorted.length; i++) {
    diffs.push((sorted[i]!.getTime() - sorted[i - 1]!.getTime()) / 86400000);
  }
  const med = median(diffs) ?? 0;
  if (med <= 1.5) return "daily";
  if (med <= 9) return "weekly";
  if (med <= 45) return "monthly";
  if (med <= 100) return "quarterly";
  return "unknown";
}

function stepDays(freq: ReturnType<typeof inferFrequency>): number {
  switch (freq) {
    case "daily":
      return 1;
    case "weekly":
      return 7;
    case "monthly":
      return 30;
    case "quarterly":
      return 91;
    default:
      return 30;
  }
}

export function analyzeQuality(raw: Point[]): { issues: Issue[]; frequency: ReturnType<typeof inferFrequency> } {
  const issues: Issue[] = [];
  const dates = raw.map((p) => p.period);
  const frequency = inferFrequency(dates);

  if (raw.length < 8) {
    issues.push({
      id: "short_history",
      severity: raw.length < 4 ? "fatal" : "error",
      message: `Serie corta (${raw.length} puntos). Con menos de 8 observaciones el pronóstico no es confiable.`,
      autoFixed: false,
    });
  }

  const seen = new Map<string, number>();
  let dups = 0;
  for (const p of raw) {
    seen.set(p.date, (seen.get(p.date) ?? 0) + 1);
  }
  for (const c of seen.values()) if (c > 1) dups += c - 1;
  if (dups > 0) {
    issues.push({
      id: "duplicate_dates",
      severity: "warn",
      message: `${dups} fechas duplicadas. Se conserva la última fila.`,
      autoFixed: true,
    });
  }

  const fc = raw.map((p) => p.forecast).filter((x): x is number => x !== null);
  const negatives = raw.filter((p) => (p.forecast !== null && p.forecast < 0) || (p.actual !== null && p.actual < 0)).length;
  if (negatives > 0) {
    issues.push({
      id: "negatives",
      severity: "error",
      message: `${negatives} valores negativos. En demanda se recortan a 0.`,
      autoFixed: true,
    });
  }

  const missingF = raw.filter((p) => p.forecast === null).length;
  if (raw.length && missingF / raw.length > 0.3) {
    issues.push({
      id: "missing_forecast",
      severity: missingF / raw.length > 0.5 ? "fatal" : "error",
      message: `${Math.round((100 * missingF) / raw.length)}% de pronósticos vacíos.`,
      autoFixed: missingF / raw.length <= 0.5,
    });
  } else if (missingF > 0) {
    issues.push({
      id: "missing_forecast",
      severity: "warn",
      message: `${missingF} pronósticos vacíos; se interpolan.`,
      autoFixed: true,
    });
  }

  if (fc.length > 0 && fc.every((x) => x === 0)) {
    issues.push({
      id: "all_zero",
      severity: "fatal",
      message: "El pronóstico es todo ceros.",
      autoFixed: false,
    });
  }

  if (fc.length >= 4 && fc.every((x) => x === fc[0])) {
    issues.push({
      id: "constant",
      severity: "warn",
      message: "Pronóstico constante. Suele ignorar estacionalidad y tendencia.",
      autoFixed: false,
    });
  }

  const sorted = [...raw].sort((a, b) => a.period.getTime() - b.period.getTime());
  const uniqueDates = [...new Set(sorted.map((p) => p.date))].map((d) => sorted.find((p) => p.date === d)!);
  if (uniqueDates.length >= 3) {
    const step = stepDays(frequency);
    let gaps = 0;
    for (let i = 1; i < uniqueDates.length; i++) {
      const diff = (uniqueDates[i]!.period.getTime() - uniqueDates[i - 1]!.period.getTime()) / 86400000;
      if (diff > step * 1.6) gaps++;
    }
    if (gaps > 0) {
      issues.push({
        id: "date_gaps",
        severity: gaps > uniqueDates.length * 0.3 ? "error" : "warn",
        message: `${gaps} huecos de calendario. Se completan fechas faltantes.`,
        autoFixed: true,
      });
    }
  }

  if (fc.length >= 8) {
    const q1 = quantile(fc, 0.25)!;
    const q3 = quantile(fc, 0.75)!;
    const iqr = q3 - q1;
    const lo = q1 - 1.5 * iqr;
    const hi = q3 + 1.5 * iqr;
    const med = median(fc)!;
    const mad = median(fc.map((x) => Math.abs(x - med))) ?? 0;
    let outliers = 0;
    for (const x of fc) {
      const z = mad === 0 ? 0 : (0.6745 * (x - med)) / mad;
      if (x < lo || x > hi || Math.abs(z) > 3.5) outliers++;
    }
    if (outliers > 0) {
      issues.push({
        id: "outliers",
        severity: outliers > 3 ? "error" : "warn",
        message: `${outliers} outliers en el pronóstico (IQR / z modificado). Se recortan por winsor.`,
        autoFixed: true,
      });
    }
    const mx = Math.max(...fc);
    const p95 = quantile(fc, 0.95)!;
    if (mx > 8 * Math.max(p95, 1) && mx > 0) {
      issues.push({
        id: "spike",
        severity: "error",
        message: `Pico extremo (${mx}) respecto al resto de la serie.`,
        autoFixed: true,
      });
    }
  }

  const actuals = raw.map((p) => p.actual).filter((x): x is number => x !== null);
  if (actuals.length >= 6 && fc.length >= 6) {
    const maxA = Math.max(...actuals);
    const maxF = Math.max(...fc);
    if (maxA > 0 && maxF > 3 * maxA) {
      issues.push({
        id: "overshoot",
        severity: "error",
        message: "El pronóstico supera 3× el máximo histórico real. Se recorta el tope.",
        autoFixed: true,
      });
    }
  }

  if (actuals.length >= 8 && fc.length >= 8) {
    let leak = 0;
    const byDate = new Map(raw.map((p) => [p.date, p]));
    const ordered = [...raw].sort((a, b) => a.period.getTime() - b.period.getTime());
    for (let i = 1; i < ordered.length; i++) {
      const prevA = ordered[i - 1]!.actual;
      const f = ordered[i]!.forecast;
      if (prevA !== null && f !== null && Math.abs(f - prevA) < 1e-9) leak++;
    }
    if (leak / ordered.length > 0.7) {
      issues.push({
        id: "leakage",
        severity: "error",
        message: "El pronóstico copia el real del período anterior (filtración / naive disfrazado). No se 'corrige': hay que reentrenar.",
        autoFixed: false,
      });
    }
    void byDate;
  }

  const intLike = fc.length > 0 && fc.every((x) => Math.abs(x - Math.round(x)) < 1e-6);
  if (!intLike && fc.length > 0) {
    issues.push({
      id: "continuous",
      severity: "info",
      message: "El pronóstico no es entero. Si el SKU se vende en unidades, redondear al exportar.",
      autoFixed: false,
    });
  }

  return { issues, frequency };
}
