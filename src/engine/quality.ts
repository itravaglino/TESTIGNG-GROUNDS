import { medianGapDays } from "./dates";
import { median, quantile } from "./metrics";
import type { Flag, ForecastRow, SeriesFeatures, Verdict } from "./types";
import { EPS, near } from "./types";

export function evaluateQuality(
  original: ForecastRow[],
  corrected: ForecastRow[],
  features: SeriesFeatures,
): { flags: Flag[]; verdict: Verdict } {
  const flags: Flag[] = [];
  const pts = corrected;
  const forecasts = pts.map((p) => p.forecast).filter((x): x is number => x != null);
  const actuals = pts.map((p) => p.actual).filter((x): x is number => x != null);
  const pairs = pts.filter((p) => p.actual != null && p.forecast != null) as { actual: number; forecast: number; date: string }[];

  const origNeg = original.filter((p) => (p.forecast != null && p.forecast < 0) || (p.actual != null && p.actual < 0));
  if (origNeg.length) {
    flags.push({
      id: "NEG_01",
      severity: "warn",
      message: `Hay cantidades negativas. No se usan como demanda y se recortaron a cero.`,
    });
  }

  const byDate = new Map<string, ForecastRow[]>();
  for (const p of original) {
    const k = p.date;
    const list = byDate.get(k) ?? [];
    list.push(p);
    byDate.set(k, list);
  }
  for (const [date, list] of byDate) {
    if (list.length < 2) continue;
    const fs = list.map((x) => x.forecast).filter((x): x is number => x != null);
    const conflict = fs.length >= 2 && fs.some((x) => !near(x, fs[0]));
    flags.push({
      id: conflict ? "DUP_CONFLICT" : "DUP_01",
      severity: conflict ? "error" : "info",
      message: conflict
        ? `Hay filas duplicadas para ${date} y los valores no coinciden.`
        : `Hay filas duplicadas exactas para ${date}.`,
    });
  }

  if (features.n < 6 || features.nPairs < 3) {
    flags.push({
      id: "SHORT_01",
      severity: "warn",
      message: `Tiene muy poca historia (${features.n} periodos). No alcanza para evaluar el pronóstico con confianza.`,
    });
  }

  if (actuals.length && actuals.every((x) => Math.abs(x) <= EPS) && forecasts.some((x) => x > EPS)) {
    flags.push({
      id: "ZERO_01",
      severity: "error",
      message: "No hay demanda histórica y el pronóstico es positivo. Revise si el producto está mal asignado.",
    });
  }
  if (actuals.length >= 4 && actuals.every((x) => Math.abs(x) <= EPS) && forecasts.every((x) => Math.abs(x) <= EPS)) {
    flags.push({
      id: "DISC_01",
      severity: "discard",
      message: "El producto se considera descontinuado: los reales y el pronóstico son cero.",
    });
  }

  if (pairs.length >= 4) {
    const equal = pairs.filter((p) => near(p.forecast, p.actual));
    const allEqual = equal.length === pairs.length;
    const somePositive = pairs.some((p) => Math.abs(p.actual) > EPS);
    if (allEqual && somePositive) {
      flags.push({
        id: "LEAK_01",
        severity: "discard",
        message: `El pronóstico coincide exactamente con la venta en los ${pairs.length} periodos comparables. Revise si se copió la venta al pronóstico.`,
      });
    }
  }

  if (forecasts.length >= 3) {
    const uniq = new Set(forecasts.map((x) => x.toFixed(4)));
    const med = median(forecasts) ?? 0;
    const mad = median(forecasts.map((x) => Math.abs(x - med))) ?? 0;
    const flat = uniq.size <= 2 || (med > EPS && mad / med < 0.02);
    if (
      flat &&
      features.cv != null &&
      features.cv >= 0.15 &&
      features.demandClass !== "intermittent" &&
      features.demandClass !== "lumpy"
    ) {
      flags.push({
        id: "FLAT_01",
        severity: "warn",
        message: "El pronóstico es plano y la historia no lo es.",
      });
    }
  }

  const gap = medianGapDays(pts.map((p) => p.date));
  if (gap != null && !(gap === 1 || (gap >= 6 && gap <= 8) || (gap >= 27 && gap <= 32))) {
    flags.push({
      id: "CADENCE_01",
      severity: "warn",
      message: "Las fechas no siguen un calendario mensual o semanal uniforme.",
    });
  }

  if (actuals.length >= 6) {
    const pos = actuals.filter((x) => x > EPS);
    const s = [...pos].sort((a, b) => a - b);
    const q1 = quantile(s, 0.25);
    const q3 = quantile(s, 0.75);
    const iqr = q3 - q1;
    const med = median(pos) ?? 0;
    const mad = median(pos.map((x) => Math.abs(x - med))) ?? 0;
    pts.forEach((p) => {
      if (p.actual == null || p.actual <= EPS) return;
      const m = mad > EPS ? (0.6745 * (p.actual - med)) / mad : Infinity;
      const iqrHit = p.actual > q3 + 3 * Math.max(iqr, EPS);
      const ratioHit = med >= 1 && p.actual >= 10 * med;
      if ((m > 3.5 && iqrHit) || ratioHit) {
        flags.push({
          id: "OUT_01",
          severity: "warn",
          message: `Hay un valor atípico en ${p.date} (${p.actual} frente a una mediana de ${med.toFixed(1)}).`,
        });
      }
    });
  }

  if (features.demandClass === "intermittent" || features.demandClass === "lumpy") {
    flags.push({
      id: "INT_01",
      severity: "info",
      message: "Tiene demanda intermitente. Un pronóstico suave no representa los periodos sin venta. No use MAPE.",
    });
    flags.push({
      id: "MET_MAPE_OFF",
      severity: "info",
      message: "MAPE queda indefinido o inflado por ceros. Evalúe con MASE, RMSSE y WAPE.",
    });
  }

  if (features.seasonal) {
    flags.push({
      id: "SEA_01",
      severity: "info",
      message: "La serie muestra un patrón estacional. El ingenuo estacional es el rival a batir.",
    });
  }

  if (features.trend) {
    flags.push({
      id: "TRD_01",
      severity: "warn",
      message: "La venta muestra tendencia. Un pronóstico plano llega tarde.",
    });
  }

  const last6 = actuals.slice(-6);
  if (last6.length === 6 && last6.every((x) => Math.abs(x) <= EPS) && forecasts.some((x) => x > EPS)) {
    flags.push({
      id: "DISC_OPEN",
      severity: "warn",
      message: "Los últimos 6 reales son cero, pero el pronóstico sigue distinto de cero.",
    });
  }

  if (pairs.length >= 3) {
    const L = median(actuals.slice(-3)) ?? 0;
    const F = median(forecasts.slice(0, Math.min(3, forecasts.length))) ?? 0;
    if (L > EPS && F > 3 * L) {
      flags.push({
        id: "DQ-S10",
        severity: "error",
        message: `El pronóstico está muy por encima de la venta reciente (×${(F / L).toFixed(1)}).`,
      });
    }
  }

  const verdict = decideVerdict(flags, features);
  return { flags: uniqueFlags(flags), verdict };
}

function uniqueFlags(flags: Flag[]): Flag[] {
  const seen = new Set<string>();
  const out: Flag[] = [];
  for (const f of flags) {
    if (seen.has(f.id)) continue;
    seen.add(f.id);
    out.push(f);
  }
  return out;
}

function decideVerdict(flags: Flag[], features: SeriesFeatures): Verdict {
  if (flags.some((f) => f.severity === "discard")) return "discard";
  if (flags.some((f) => f.id === "DUP_CONFLICT")) return "review";
  if (flags.some((f) => f.severity === "error")) return "review";
  if (features.n < 6) return "review";
  if (flags.some((f) => f.severity === "warn" && ["TRD_01", "OUT_01", "FLAT_01", "DISC_OPEN", "NEG_01", "SHORT_01"].includes(f.id))) {
    return "review";
  }
  return "keep";
}
