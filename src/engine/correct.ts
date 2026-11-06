import type { Correction, DiscardDecision, ForecastPoint, Issue, Metrics, SeriesProfile } from "./types";
import { toIsoDate } from "./parse";
import { fillDateGrid, mean, sortPoints } from "./profile";

function clone(p: ForecastPoint): ForecastPoint {
  return { ...p, raw: { ...p.raw } };
}

export function correctSeries(
  points: ForecastPoint[],
  profile: SeriesProfile,
): { corrected: ForecastPoint[]; corrections: Correction[] } {
  const corrections: Correction[] = [];
  let s = sortPoints(points).map(clone);
  if (s.length === 0) return { corrected: s, corrections };

  const beforeDup = s.length;
  const byDate = new Map<string, ForecastPoint[]>();
  for (const p of s) {
    const list = byDate.get(p.isoDate) ?? [];
    list.push(p);
    byDate.set(p.isoDate, list);
  }
  if (byDate.size < beforeDup) {
    s = [...byDate.entries()].map(([, group]) => {
      const g = group[0];
      const avg = (sel: (p: ForecastPoint) => number | undefined) => {
        const xs = group.map(sel).filter((x): x is number => x !== undefined && Number.isFinite(x));
        return xs.length ? mean(xs) : undefined;
      };
      return {
        ...g,
        forecast: mean(group.map((p) => p.forecast).filter(Number.isFinite)),
        actual: avg((p) => p.actual),
        lower: avg((p) => p.lower),
        upper: avg((p) => p.upper),
        price: avg((p) => p.price),
      };
    });
    s = sortPoints(s);
    corrections.push({
      code: "dedupe",
      description: "Fechas duplicadas agregadas por promedio",
      pointsChanged: beforeDup - s.length,
    });
  }

  let nanDropped = 0;
  s = s.filter((p) => {
    const ok = Number.isFinite(p.forecast);
    if (!ok) nanDropped++;
    return ok;
  });
  if (nanDropped) {
    corrections.push({ code: "drop_nan", description: "Filas NaN/Inf eliminadas", pointsChanged: nanDropped });
  }

  let clipped = 0;
  s = s.map((p) => {
    if (p.forecast < 0) {
      clipped++;
      return { ...p, forecast: 0 };
    }
    return p;
  });
  if (clipped) {
    corrections.push({ code: "clip_neg", description: "Pronósticos negativos recortados a 0", pointsChanged: clipped });
  }

  if (profile.cadence !== "irregular" && s.length >= 2) {
    const grid = fillDateGrid(s[0].date, s[s.length - 1].date, profile.stepDays);
    const map = new Map(s.map((p) => [p.isoDate, p]));
    const period = profile.seasonalPeriod;
    const filled: ForecastPoint[] = [];
    let nFill = 0;
    for (const iso of grid) {
      const existing = map.get(iso);
      if (existing) {
        filled.push(existing);
        continue;
      }
      const [y, m, d] = iso.split("-").map(Number);
      const date = new Date(Date.UTC(y, m - 1, d));
      const seasonalIso = toIsoDate(new Date(date.getTime() - period * profile.stepDays * 86400000));
      const seasonal = map.get(seasonalIso);
      const prev = filled[filled.length - 1];
      const nextKnown = s.find((p) => p.date.getTime() > date.getTime());
      let forecast = prev?.forecast ?? 0;
      if (seasonal && period > 1) forecast = seasonal.forecast;
      else if (prev && nextKnown) {
        const span = nextKnown.date.getTime() - prev.date.getTime();
        const t = span === 0 ? 0 : (date.getTime() - prev.date.getTime()) / span;
        forecast = prev.forecast + t * (nextKnown.forecast - prev.forecast);
      }
      nFill++;
      filled.push({
        date,
        isoDate: iso,
        forecast,
        raw: {},
      });
    }
    if (nFill) {
      s = filled;
      corrections.push({
        code: "fill_gaps",
        description: `Huecos completados (${profile.cadence})`,
        pointsChanged: nFill,
      });
    }
  }

  if (s.length >= 8) {
    const f = s.map((p) => p.forecast);
    const q = [...f].sort((a, b) => a - b);
    const q1 = q[Math.floor(q.length * 0.25)];
    const q3 = q[Math.floor(q.length * 0.75)];
    const iqr = q3 - q1;
    const lo = q1 - 3 * iqr;
    const hi = q3 + 3 * iqr;
    let capped = 0;
    if (iqr > 0) {
      s = s.map((p) => {
        if (p.forecast > hi) {
          capped++;
          return { ...p, forecast: hi };
        }
        if (p.forecast < lo) {
          capped++;
          return { ...p, forecast: Math.max(0, lo) };
        }
        return p;
      });
    }
    if (capped) {
      corrections.push({ code: "winsor", description: "Picos recortados por 3×IQR", pointsChanged: capped });
    }
  }

  const overlap = s.filter((p) => p.actual !== undefined && Number.isFinite(p.actual) && p.actual !== 0);
  if (overlap.length >= 8) {
    const mf = mean(overlap.map((p) => p.forecast));
    const ma = mean(overlap.map((p) => p.actual as number));
    if (mf > 0 && ma > 0) {
      const ratio = ma / mf;
      if (ratio > 1.08 || ratio < 1 / 1.08) {
        if (ratio < 6 && ratio > 1 / 6) {
          s = s.map((p) => ({ ...p, forecast: p.forecast * ratio }));
          corrections.push({
            code: "bias",
            description: `Corrección de sesgo ×${ratio.toFixed(3)} (media real / media forecast)`,
            pointsChanged: s.length,
          });
        }
      }
    }
  }

  let swapped = 0;
  s = s.map((p) => {
    if (p.lower !== undefined && p.upper !== undefined && p.lower > p.upper) {
      swapped++;
      return { ...p, lower: p.upper, upper: p.lower };
    }
    return p;
  });
  if (swapped) {
    corrections.push({ code: "pi_swap", description: "Intervalos invertidos intercambiados", pointsChanged: swapped });
  }

  const actualsInt = s.every((p) => p.actual === undefined || Math.abs((p.actual as number) - Math.round(p.actual as number)) < 1e-6);
  if (actualsInt && profile.meanDemand < 80) {
    let rounded = 0;
    s = s.map((p) => {
      const r = Math.max(0, Math.round(p.forecast));
      if (Math.abs(r - p.forecast) > 1e-9) rounded++;
      return { ...p, forecast: r };
    });
    if (rounded) {
      corrections.push({ code: "round", description: "Redondeo a unidades enteras", pointsChanged: rounded });
    }
  }

  return { corrected: sortPoints(s), corrections };
}

export function discardDecision(
  points: ForecastPoint[],
  issues: Issue[],
  metrics: Metrics,
  profile: SeriesProfile,
): DiscardDecision {
  const fatals = issues.filter((i) => i.severity === "fatal");
  const codes = new Set(issues.map((i) => i.code));

  if (points.length === 0) {
    return { discard: true, reason: "Sin puntos válidos.", keepHint: "Reconstruir el SKU en el extracto origen." };
  }
  if (codes.has("all_zero_fcst")) {
    return { discard: true, reason: "Pronóstico nulo en toda la serie.", keepHint: "Reemplazar por Croston/TSB o analogía." };
  }
  if (codes.has("zero_actual_high_fcst")) {
    return { discard: true, reason: "Demanda real en cero con forecast alto (posible delist o error de cruce).", keepHint: "Validar maestro de producto y ventas." };
  }
  if (codes.has("scale")) {
    return { discard: true, reason: "Inconsistencia de unidades (cajas vs unidades u otro factor).", keepHint: "Corregir el factor de conversión y volver a cargar." };
  }
  if (points.length < 8) {
    return { discard: true, reason: "Historia insuficiente (<8 períodos) para un forecast operable.", keepHint: "Usar análogos / prior bayesiano hasta tener ≥16 períodos." };
  }
  if (metrics.nWithActual >= 8 && metrics.wape !== null && metrics.wape > 1.5 && Math.abs(metrics.biasPct ?? 0) > 2) {
    return { discard: true, reason: `WAPE ${(metrics.wape * 100).toFixed(0)}% y sesgo extremo: el modelo no es informativo.`, keepHint: "Entrenar de nuevo o usar seasonal naive como piso." };
  }
  if (fatals.length >= 2) {
    return { discard: true, reason: "Múltiples fallas estructurales.", keepHint: profile.isNewProduct ? "Tratar como producto nuevo (análogos)." : "Revisar ETL y reforecast." };
  }
  return { discard: false, reason: "", keepHint: "" };
}
