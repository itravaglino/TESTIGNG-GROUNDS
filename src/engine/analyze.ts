import { correctSeries } from "./correct";
import { computeFeatures } from "./features";
import { computeMetrics, metricMap } from "./metrics";
import { parseCsvText } from "./parse";
import { tipsFor } from "./playbook";
import { evaluateQuality } from "./quality";
import { recommendModels } from "./recommend";
import type { ForecastRow, ParseResult, PeriodType, PortfolioReport, ProductReport } from "./types";
import { EPS } from "./types";

export function analyzeCsv(text: string): PortfolioReport {
  const parsed = parseCsvText(text);
  return analyzeParsed(parsed);
}

export function analyzeParsed(parsed: ParseResult): PortfolioReport {
  const groups = new Map<string, ForecastRow[]>();
  for (const row of parsed.rows) {
    const key = `${row.productId}||${row.model}`;
    const list = groups.get(key) ?? [];
    list.push(row);
    groups.set(key, list);
  }

  const products: ProductReport[] = [];
  for (const [, rows] of groups) {
    products.push(analyzeProduct(rows));
  }

  markWinners(products);

  const periodType = majorityPeriod(products);
  const scored = products.filter((p) => p.verdict !== "discard" && p.volume > 0 && p.metrics.find((m) => m.id === "wape")?.defined);
  const totalVol = products.reduce((a, p) => a + p.volume, 0);
  const scoredVol = scored.reduce((a, p) => a + p.volume, 0);
  const absErr = scored.reduce((a, p) => {
    const wape = p.metrics.find((m) => m.id === "wape")?.value ?? 0;
    return a + (wape / 100) * p.volume;
  }, 0);
  const biasAbs = scored.reduce((a, p) => {
    const b = p.metrics.find((m) => m.id === "pbias")?.value ?? 0;
    return a + (b / 100) * p.volume;
  }, 0);

  const wape = scoredVol > EPS ? (absErr / scoredVol) * 100 : null;
  const bias = scoredVol > EPS ? (biasAbs / scoredVol) * 100 : null;

  const aggPairs = aggregatePairs(products.filter((p) => p.verdict !== "discard"));
  const aggWape =
    aggPairs.sumAbsY > EPS ? (aggPairs.sumAbsErr / aggPairs.sumAbsY) * 100 : null;
  const cancellationGap = wape != null && aggWape != null ? wape - aggWape : null;

  const discardedShare = products.length ? products.filter((p) => p.verdict === "discard").length / products.length : 0;
  const reviewShare = products.length ? products.filter((p) => p.verdict === "review").length / products.length : 0;
  const healthWeighted = volumeWeightedHealth(products);

  const dates = new Set(parsed.rows.map((r) => r.date));

  return {
    products: products.sort((a, b) => b.volume - a.volume),
    diagnostics: parsed.diagnostics,
    parse: parsed,
    health: healthWeighted,
    discardedShare,
    reviewShare,
    wape,
    bias,
    cancellationGap,
    scoredVolume: scoredVol,
    unscoredVolumeShare: totalVol > EPS ? 1 - scoredVol / totalVol : 1,
    periodType,
    productCount: new Set(products.map((p) => p.productId)).size,
    periodCount: dates.size,
    rowCount: parsed.rows.length,
  };
}

function analyzeProduct(rows: ForecastRow[]): ProductReport {
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
  const head = sorted[0];
  const periodType: PeriodType = head.periodType;
  const corrected = correctSeries(sorted);
  const features = computeFeatures(corrected.points, periodType);
  const { flags, verdict } = evaluateQuality(sorted, corrected.points, features);
  const pairs = corrected.points
    .filter((p) => p.actual != null && p.forecast != null)
    .map((p) => ({
      date: p.date,
      actual: p.actual as number,
      forecast: p.forecast as number,
      lo: p.lo,
      hi: p.hi,
    }));
  const allActuals = corrected.points.map((p) => p.actual).filter((x): x is number => x != null);
  const metrics = computeMetrics(pairs, periodType, allActuals);
  const rec = recommendModels(features, flags);
  const tips = tipsFor(features, flags, metrics);
  const volume = Math.max(
    allActuals.reduce((a, b) => a + Math.abs(b), 0),
    pairs.reduce((a, p) => a + Math.abs(p.actual), 0),
  );
  let finalVerdict = verdict;
  const wapeVal = metrics.find((x) => x.id === "wape")?.value;
  if (
    finalVerdict !== "discard" &&
    wapeVal != null &&
    wapeVal > 30 &&
    flags.some((f) => f.id === "TRD_01") &&
    flags.some((f) => f.id === "FLAT_01")
  ) {
    finalVerdict = "discard";
    flags.push({
      id: "BAD_FLAT_TREND",
      severity: "discard",
      message: "El pronóstico plano no sigue la tendencia de la venta. No publique este modelo.",
    });
  }
  const health = skuHealth(metrics, finalVerdict, flags.length);
  const uniqFlags = [...new Map(flags.map((f) => [f.id, f])).values()];
  if (rec.primary.id === "holt_winters") uniqFlags.push({ id: "REC_HW", severity: "info", message: "Se recomienda Holt-Winters." });
  if (rec.primary.id === "seasonal_naive" || rec.challengers.some((c) => c.id === "seasonal_naive")) {
    uniqFlags.push({ id: "REC_SNAIVE", severity: "info", message: "El ingenuo estacional es un retador válido." });
  }
  if (rec.primary.id === "sba" || rec.primary.id === "croston") {
    uniqFlags.push({ id: "REC_CROSTON", severity: "info", message: "Se recomienda Croston/SBA." });
  }
  if (rec.challengers.some((c) => c.id === "tsb") || rec.primary.id === "tsb") {
    uniqFlags.push({ id: "REC_TSB", severity: "info", message: "TSB es el retador para obsolescencia." });
  }
  if (rec.primary.id === "analog") uniqFlags.push({ id: "REC_ANALOG", severity: "info", message: "Use análogos de lanzamiento." });
  if (rec.primary.id === "damped_holt" || rec.primary.id === "holt") {
    uniqFlags.push({ id: "REC_HOLT", severity: "info", message: "Se recomienda Holt con tendencia." });
  }

  return {
    productId: head.productId,
    productName: head.productName,
    model: head.model,
    attributes: head.attributes,
    points: sorted,
    correctedForecast: corrected.correctedForecast,
    pairs,
    flags: uniqFlags,
    mutations: corrected.mutations,
    metrics,
    features,
    verdict: finalVerdict,
    health,
    volume,
    recommended: rec.primary,
    challengers: rec.challengers,
    tips,
  };
}

function skuHealth(metrics: ProductReport["metrics"], verdict: ProductReport["verdict"], flagCount: number): number {
  const m = metricMap(metrics);
  let score = 100;
  if (verdict === "discard") return 15;
  if (verdict === "review") score -= 18;
  const wape = m.wape;
  if (wape == null) score -= 10;
  else if (wape <= 15) score -= 0;
  else if (wape <= 30) score -= 12;
  else if (wape <= 50) score -= 28;
  else score -= 45;
  const bias = Math.abs(m.pbias ?? 0);
  if (bias > 15) score -= 18;
  else if (bias > 5) score -= 8;
  const mase = m.mase;
  if (mase != null) {
    if (mase <= 1) score += 5;
    else if (mase > 1.5) score -= 10;
  }
  score -= Math.min(12, flagCount);
  return Math.max(0, Math.min(100, Math.round(score)));
}

function volumeWeightedHealth(products: ProductReport[]): number {
  const usable = products.filter((p) => p.verdict !== "discard");
  const vol = usable.reduce((a, p) => a + p.volume, 0);
  if (vol <= EPS) {
    if (!products.length) return 0;
    return Math.round(products.reduce((a, p) => a + p.health, 0) / products.length);
  }
  const w = usable.reduce((a, p) => a + p.health * p.volume, 0) / vol;
  const discardedShare = products.filter((p) => p.verdict === "discard").length / products.length;
  return Math.max(0, Math.min(100, Math.round(w - discardedShare * 35)));
}

function majorityPeriod(products: ProductReport[]): PeriodType {
  const counts = new Map<PeriodType, number>();
  for (const p of products) {
    const t = p.points[0]?.periodType ?? "unknown";
    counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  let best: PeriodType = "month";
  let n = -1;
  for (const [k, v] of counts) {
    if (v > n) {
      best = k;
      n = v;
    }
  }
  return best;
}

function aggregatePairs(products: ProductReport[]): { sumAbsErr: number; sumAbsY: number } {
  const byDate = new Map<string, { y: number; f: number }>();
  for (const p of products) {
    for (const pair of p.pairs) {
      const cur = byDate.get(pair.date) ?? { y: 0, f: 0 };
      cur.y += pair.actual;
      cur.f += pair.forecast;
      byDate.set(pair.date, cur);
    }
  }
  let sumAbsErr = 0;
  let sumAbsY = 0;
  for (const v of byDate.values()) {
    sumAbsErr += Math.abs(v.f - v.y);
    sumAbsY += Math.abs(v.y);
  }
  return { sumAbsErr, sumAbsY };
}

function markWinners(products: ProductReport[]): void {
  const bySku = new Map<string, ProductReport[]>();
  for (const p of products) {
    const list = bySku.get(p.productId) ?? [];
    list.push(p);
    bySku.set(p.productId, list);
  }
  for (const [, list] of bySku) {
    if (list.length < 2) continue;
    const scored = list.filter((p) => p.metrics.find((m) => m.id === "wape")?.defined);
    if (!scored.length) continue;
    scored.sort((a, b) => (a.metrics.find((m) => m.id === "wape")?.value ?? 1e9) - (b.metrics.find((m) => m.id === "wape")?.value ?? 1e9));
    scored[0].winnerAmongUploaded = true;
    scored[0].flags.push({
      id: "WIN_01",
      severity: "info",
      message: `Entre los modelos cargados, ${scored[0].model} tiene el menor WAPE.`,
    });
    for (const other of scored.slice(1)) {
      if ((other.metrics.find((m) => m.id === "wape")?.value ?? 0) > 25) {
        other.flags.push({
          id: "MULTI_01",
          severity: "warn",
          message: `El modelo ${other.model} pierde claramente frente a ${scored[0].model}.`,
        });
      }
    }
  }
}

export function exportCsv(report: PortfolioReport): string {
  const header = [
    "sku",
    "producto",
    "modelo",
    "veredicto",
    "salud",
    "wape",
    "sesgo",
    "mase",
    "mae",
    "rmse",
    "mape",
    "smape",
    "volumen",
    "clase_demanda",
    "modelo_recomendado",
    "senales",
    "consejos",
  ];
  const lines = [header.join(",")];
  for (const p of report.products) {
    const m = metricMap(p.metrics);
    const row = [
      csv(p.productId),
      csv(p.productName ?? ""),
      csv(p.model),
      p.verdict,
      String(p.health),
      num(m.wape),
      num(m.pbias),
      num(m.mase),
      num(m.mae),
      num(m.rmse),
      num(m.mape),
      num(m.smape),
      num(p.volume),
      p.features.demandClass,
      csv(p.recommended.name),
      csv(p.flags.map((f) => f.id).join("|")),
      csv(p.tips.map((t) => t.title).join("|")),
    ];
    lines.push(row.join(","));
  }
  return lines.join("\n");
}

function csv(s: string): string {
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}
function num(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "" : String(Math.round(v * 1000) / 1000);
}

export { metricMap };
