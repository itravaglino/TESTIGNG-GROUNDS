import { computePoint, percentile } from "./metrics";
import type { CanonicalRow, ForecastIssue, ProcessedRow, QualityGates, SeriesProfile } from "./types";

function clone(row: CanonicalRow, patch: Partial<ProcessedRow>): ProcessedRow {
  return {
    ...row,
    originalForecast: row.forecast,
    disposition: "keep",
    correction: null,
    discardReason: null,
    point: computePoint(row.forecast, row.actual, row),
    ...patch,
  };
}

export function processRows(
  rows: CanonicalRow[],
  issues: ForecastIssue[],
  profile: SeriesProfile,
  gates: QualityGates,
): { kept: ProcessedRow[]; discarded: ProcessedRow[] } {
  const ordered = [...rows].sort((a, b) => a.timestamp - b.timestamp || a.line - b.line);
  const discarded: ProcessedRow[] = [];
  const working: CanonicalRow[] = [];

  const explode = issues.some((i) => i.code === "TREND_EXPLOSION");

  const seen = new Map<string, CanonicalRow>();
  for (const row of ordered) {
    if (!Number.isFinite(row.forecast) || !Number.isFinite(row.timestamp)) {
      discarded.push(
        clone(row, {
          disposition: "discarded",
          discardReason: "Fecha o pronóstico ilegible",
        }),
      );
      continue;
    }
    const key = `${row.date}|${row.location ?? ""}|${row.channel ?? ""}|${row.horizon ?? ""}`;
    const prev = seen.get(key);
    if (prev) {
      discarded.push(
        clone(prev, {
          disposition: "discarded",
          discardReason: "Duplicado: se conserva la última fila",
        }),
      );
    }
    seen.set(key, row);
  }

  for (const row of seen.values()) working.push(row);
  working.sort((a, b) => a.timestamp - b.timestamp);

  const finiteForecasts = working.map((r) => r.forecast).filter(Number.isFinite);
  const med = percentile(finiteForecasts, 50) ?? 0;
  const q1 = percentile(finiteForecasts, 25) ?? med;
  const q3 = percentile(finiteForecasts, 75) ?? med;
  const iqr = q3 - q1 || Math.abs(med) * 0.1 || 1;
  const lo = q1 - 2.5 * iqr;
  const hi = q3 + 2.5 * iqr;

  const paired = working.filter((r) => r.actual !== null && Number.isFinite(r.actual) && r.actual > 0 && r.forecast > 0);
  const meanA = paired.length ? paired.reduce((s, r) => s + (r.actual as number), 0) / paired.length : 0;
  const meanF = paired.length ? paired.reduce((s, r) => s + r.forecast, 0) / paired.length : 0;
  const biasFactor = meanF > 0 && meanA > 0 && Math.abs(meanA / meanF - 1) > 0.25 ? meanA / meanF : 1;

  const kept: ProcessedRow[] = [];
  for (let i = 0; i < working.length; i++) {
    const row = working[i];
    if (explode) {
      discarded.push(
        clone(row, {
          disposition: "discarded",
          discardReason: "Tendencia explosiva: la serie no es usable en operación",
        }),
      );
      continue;
    }
    if (med > 0 && row.forecast / med >= gates.scaleShiftRatio) {
      discarded.push(
        clone(row, {
          disposition: "discarded",
          discardReason: `Error de escala (×${(row.forecast / med).toFixed(0)} respecto de la mediana)`,
        }),
      );
      continue;
    }

    let forecast = row.forecast;
    const notes: string[] = [];
    if (profile.n >= 8 && forecast >= 0 && (forecast > hi || forecast < lo)) {
      const clamped = Math.min(hi, Math.max(lo, forecast));
      if (clamped !== forecast) {
        forecast = Math.max(0, clamped);
        notes.push("Pico winsorizado (IQR 2.5)");
      }
    }
    if (biasFactor !== 1) {
      forecast *= biasFactor;
      notes.push(`Rescala de sesgo ×${biasFactor.toFixed(2)}`);
    }
    if (forecast < 0) {
      forecast = 0;
      notes.push("Negativo recortado a 0");
    }
    let actual = row.actual;
    if (actual !== null && actual < 0) actual = 0;

    kept.push(
      clone(
        { ...row, forecast, actual },
        {
          originalForecast: row.forecast,
          disposition: notes.length ? "corrected" : "keep",
          correction: notes.length ? notes.join("; ") : null,
          point: computePoint(forecast, actual, { lower: row.lower, upper: row.upper }),
        },
      ),
    );
  }

  const byTs = [...kept].sort((a, b) => a.timestamp - b.timestamp);
  if (byTs.length >= 3) {
    const diffs = [];
    for (let i = 1; i < byTs.length; i++) diffs.push(byTs[i].timestamp - byTs[i - 1].timestamp);
    const medDiff = [...diffs].sort((a, b) => a - b)[Math.floor(diffs.length / 2)];
    if (medDiff > 0) {
      const filled: ProcessedRow[] = [];
      for (let i = 0; i < byTs.length; i++) {
        filled.push(byTs[i]);
        if (i === byTs.length - 1) break;
        const gap = byTs[i + 1].timestamp - byTs[i].timestamp;
        const steps = Math.round(gap / medDiff);
        if (steps > 1 && steps <= 8) {
          for (let s = 1; s < steps; s++) {
            const ts = byTs[i].timestamp + s * medDiff;
            const t = s / steps;
            const forecast = byTs[i].forecast * (1 - t) + byTs[i + 1].forecast * t;
            const d = new Date(ts);
            const iso = d.toISOString().slice(0, 10);
            filled.push(
              clone(
                {
                  ...byTs[i],
                  line: -1,
                  date: iso,
                  timestamp: ts,
                  forecast,
                  actual: null,
                  extra: { ...byTs[i].extra, interpolated: "1" },
                },
                {
                  originalForecast: NaN,
                  disposition: "corrected",
                  correction: "Hueco interpolado linealmente",
                  point: computePoint(forecast, null, null),
                },
              ),
            );
          }
        }
      }
      return { kept: filled, discarded };
    }
  }

  return { kept, discarded };
}
