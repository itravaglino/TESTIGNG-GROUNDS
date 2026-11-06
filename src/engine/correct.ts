import { inferPeriodType } from "./dates";
import { quantile } from "./metrics";
import type { ForecastRow, Mutation } from "./types";
import { EPS, near } from "./types";

export interface CorrectedSeries {
  points: ForecastRow[];
  mutations: Mutation[];
  correctedForecast: Record<string, number | null>;
}

export function correctSeries(input: ForecastRow[]): CorrectedSeries {
  const mutations: Mutation[] = [];
  const points = input.map((p) => ({ ...p, attributes: { ...p.attributes } }));
  points.sort((a, b) => a.date.localeCompare(b.date) || a.sourceRow - b.sourceRow);

  const grouped = new Map<string, ForecastRow[]>();
  for (const p of points) {
    const list = grouped.get(p.date) ?? [];
    list.push(p);
    grouped.set(p.date, list);
  }
  const deduped: ForecastRow[] = [];
  let conflict = false;
  for (const [date, list] of grouped) {
    if (list.length === 1) {
      deduped.push(list[0]);
      continue;
    }
    const forecasts = list.map((x) => x.forecast).filter((x): x is number => x != null);
    const actuals = list.map((x) => x.actual).filter((x): x is number => x != null);
    const sameF = forecasts.length <= 1 || forecasts.every((x) => near(x, forecasts[0]));
    const sameA = actuals.length <= 1 || actuals.every((x) => near(x, actuals[0]));
    if (!sameF || !sameA) conflict = true;
    const latest = list.reduce((a, b) => (a.sourceRow >= b.sourceRow ? a : b));
    const meanF = forecasts.length ? forecasts.reduce((a, b) => a + b, 0) / forecasts.length : null;
    const meanA = actuals.length ? actuals.reduce((a, b) => a + b, 0) / actuals.length : null;
    deduped.push({
      ...latest,
      forecast: sameF ? (forecasts[0] ?? latest.forecast) : meanF,
      actual: sameA ? (actuals[0] ?? latest.actual) : meanA,
    });
    mutations.push({
      code: sameF && sameA ? "DUP_EXACT" : "DUP_CONFLICT",
      message: sameF && sameA
        ? `Se fusionaron filas duplicadas en ${date} porque los valores coincidían.`
        : `Hay filas duplicadas con valores distintos en ${date}. Se usó la media para continuar el diagnóstico.`,
      affectedDates: [date],
    });
  }
  if (conflict) {
    /* already logged per date */
  }

  let negF = 0;
  let negA = 0;
  for (const p of deduped) {
    if (p.forecast != null && p.forecast < 0) {
      p.forecast = 0;
      negF += 1;
    }
    if (p.actual != null && p.actual < 0) {
      p.actual = 0;
      negA += 1;
    }
  }
  if (negF || negA) {
    mutations.push({
      code: "NEG_CLIP",
      message: `Se recortaron a cero ${negF} pronósticos negativos y ${negA} reales negativos.`,
      affectedDates: deduped.filter((p) => p.forecast === 0).map((p) => p.date),
    });
  }

  const finiteF = deduped.map((p) => p.forecast).filter((x): x is number => x != null);
  const fMed = finiteF.length ? [...finiteF].sort((a, b) => a - b)[Math.floor(finiteF.length / 2)] : 0;
  const fMax = finiteF.length ? Math.max(...finiteF) : 0;
  const extremeTail = fMed > EPS && fMax >= 8 * fMed;
  if (finiteF.length >= 30 || (finiteF.length >= 12 && extremeTail)) {
    const sorted = [...finiteF].sort((a, b) => a - b);
    const lo = quantile(sorted, finiteF.length >= 30 ? 0.01 : 0.05);
    const hi = quantile(sorted, finiteF.length >= 30 ? 0.99 : 0.95);
    let k = 0;
    const dates: string[] = [];
    for (const p of deduped) {
      if (p.forecast == null) continue;
      if (p.forecast < lo || p.forecast > hi) {
        p.forecast = Math.min(hi, Math.max(lo, p.forecast));
        k += 1;
        dates.push(p.date);
      }
    }
    if (k) {
      mutations.push({
        code: "winsorize",
        message: `Se winsorizaron ${k} pronósticos al intervalo [${lo.toFixed(1)}, ${hi.toFixed(1)}].`,
        affectedDates: dates,
      });
    }
  }

  const periodType = inferPeriodType(
    deduped.map((p) => p.date),
    deduped[0]?.periodType ?? "unknown",
  );
  fillSmallGaps(deduped, periodType === "week" ? 7 : periodType === "month" ? 12 : null, mutations);

  const allZero = finiteF.length >= 4 && finiteF.every((x) => Math.abs(x) <= EPS);
  const actuals = deduped.filter((p) => p.actual != null);
  if (allZero && actuals.length) {
    const p = periodType === "week" ? 52 : 12;
    for (let i = 0; i < deduped.length; i++) {
      const j = i - p;
      const src = j >= 0 ? deduped[j].actual : actuals[actuals.length - 1].actual;
      if (src != null) deduped[i].forecast = Math.max(0, src);
    }
    mutations.push({
      code: "zero_to_seasonal_naive",
      message: `El pronóstico era constantemente cero y se reemplazó por un ingenuo estacional de periodo ${p} construido con los reales.`,
      affectedDates: deduped.map((x) => x.date),
    });
  }

  const correctedForecast: Record<string, number | null> = {};
  for (const p of deduped) correctedForecast[p.date] = p.forecast;
  return { points: deduped, mutations, correctedForecast };
}

function fillSmallGaps(points: ForecastRow[], season: number | null, mutations: Mutation[]): void {
  let filled = 0;
  const dates: string[] = [];
  for (let i = 1; i < points.length - 1; i++) {
    if (points[i].forecast != null) continue;
    const left = points[i - 1].forecast;
    const right = points[i + 1].forecast;
    if (left == null || right == null) continue;
    if (season && i - season >= 0 && i + season < points.length) {
      const a = points[i - season].forecast;
      const b = points[i + season].forecast;
      if (a != null && b != null) {
        points[i].forecast = 0.5 * (a + b);
        filled += 1;
        dates.push(points[i].date);
        continue;
      }
    }
    points[i].forecast = (left + right) / 2;
    filled += 1;
    dates.push(points[i].date);
  }
  if (filled) {
    mutations.push({
      code: "gap_fill",
      message: `Se rellenaron ${filled} huecos cortos del pronóstico.`,
      affectedDates: dates,
    });
  }
}
