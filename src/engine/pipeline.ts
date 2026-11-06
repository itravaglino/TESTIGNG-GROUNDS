import type { ForecastPoint, PipelineResult, ProductResult, Verdict } from "./types";
import { parseForecastCsv } from "./parse";
import { groupByProduct, profileSeries, sortPoints } from "./profile";
import { computeMetrics } from "./metrics";
import { diagnoseSeries } from "./diagnose";
import { correctSeries, discardDecision } from "./correct";
import { recommendModels } from "./models";

function qualityScore(
  verdict: Verdict,
  issues: ProductResult["issues"],
  metrics: ProductResult["metricsCorrected"],
): number {
  if (verdict === "discard") return 0;
  let s = 100;
  for (const i of issues) {
    s -= i.severity === "fatal" ? 25 : i.severity === "error" ? 12 : i.severity === "warn" ? 6 : 1;
  }
  if (metrics.nWithActual > 0) {
    if (metrics.wape !== null) s -= Math.min(40, metrics.wape * 40);
    if (metrics.biasPct !== null) s -= Math.min(18, Math.abs(metrics.biasPct) * 40);
    if (metrics.mase !== null && metrics.mase > 1) s -= Math.min(10, (metrics.mase - 1) * 8);
  }
  return Math.max(0, Math.min(100, Math.round(s)));
}

function improvements(p: ProductResult): string[] {
  const out: string[] = [];
  const m = p.metricsCorrected;
  const top = p.models[0];
  if (p.verdict === "discard") {
    out.push(p.discard.keepHint);
    if (top) out.push(`Si se rehace: empezar por ${top.name}.`);
    return out.filter(Boolean);
  }
  if (m.wape !== null && m.wape > 0.25) {
    out.push("WAPE alto: revisar promociones, quiebres de stock y el grano (día vs semana).");
  }
  if (m.biasPct !== null && Math.abs(m.biasPct) > 0.1) {
    out.push(m.biasPct > 0
      ? "Sobrepronóstico sistemático: bajar nivel o usar SBA/damped; evita sobrestock."
      : "Subpronóstico sistemático: subir nivel o capturar tendencia; riesgo de quiebre.");
  }
  if (p.issues.some((i) => i.code === "season_ignored")) {
    out.push("Agregar estacionalidad (HW, Fourier o dummies de semana/mes).");
  }
  if (p.profile.intermittency === "intermittent" || p.profile.intermittency === "lumpy") {
    out.push("No uses MAPE clásico ni ARIMA: evalúa con MASE/RMSSE y modelá con Croston/SBA/TSB.");
  }
  if (p.profile.promotionsLikely) {
    out.push("Marcar calendarios de promo/precio como regresores; un LGBM de panel suele ganar.");
  }
  if (p.profile.isNewProduct) {
    out.push("Producto corto: mezclar análogos de categoría con un prior y no fiarse de un único modelo.");
  }
  if (top) out.push(`Modelo sugerido #1: ${top.name} — ${top.whyThisProduct}`);
  out.push("Validar con rolling origin (WAPE + bias %) antes de mandar a abastecimiento.");
  return out;
}

function analyzeProduct(
  productId: string,
  productName: string,
  location: string,
  points: ForecastPoint[],
): ProductResult {
  const original = sortPoints(points);
  const profile = profileSeries(original);
  const issues = diagnoseSeries(original, profile);
  const metricsOriginal = computeMetrics(original, profile.seasonalPeriod);
  const { corrected, corrections } = correctSeries(original, profile);
  const profileC = profileSeries(corrected);
  const metricsCorrected = computeMetrics(corrected, profileC.seasonalPeriod);
  const discard = discardDecision(corrected, issues, metricsOriginal, profile);
  let verdict: Verdict = "keep";
  if (discard.discard) verdict = "discard";
  else if (corrections.length) verdict = "correct";
  const models = recommendModels(profileC, metricsCorrected);
  const result: ProductResult = {
    key: `${productId}||${location}`,
    productId,
    productName,
    location,
    verdict,
    quality: 0,
    profile: profileC,
    original,
    corrected: verdict === "discard" ? original : corrected,
    issues,
    corrections: verdict === "discard" ? [] : corrections,
    metricsOriginal,
    metricsCorrected: verdict === "discard" ? metricsOriginal : metricsCorrected,
    discard,
    models,
    improvements: [],
  };
  result.quality = qualityScore(verdict, issues, result.metricsCorrected);
  result.improvements = improvements(result);
  return result;
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function runForecastQa(csvText: string): PipelineResult {
  const { rows, report } = parseForecastCsv(csvText);
  const grouped = groupByProduct(rows);
  const products: ProductResult[] = [];
  for (const [, list] of grouped) {
    products.push(
      analyzeProduct(
        list[0].productId,
        list[0].productName,
        list[0].location,
        list.map((r) => r.point),
      ),
    );
  }
  products.sort((a, b) => {
    const order = { discard: 0, correct: 1, keep: 2 };
    return order[a.verdict] - order[b.verdict] || a.quality - b.quality || a.productId.localeCompare(b.productId);
  });
  const wapes = products
    .map((p) => p.metricsCorrected.wape)
    .filter((x): x is number => x !== null);
  return {
    report,
    products,
    summary: {
      total: products.length,
      keep: products.filter((p) => p.verdict === "keep").length,
      correct: products.filter((p) => p.verdict === "correct").length,
      discard: products.filter((p) => p.verdict === "discard").length,
      medianWape: median(wapes),
      withActuals: products.filter((p) => p.metricsOriginal.nWithActual > 0).length,
    },
  };
}

export function exportCleanCsv(products: ProductResult[]): string {
  const header = "sku,nombre,deposito,fecha,pronostico_original,pronostico_corregido,ventas,veredicto,calidad";
  const lines = [header];
  for (const p of products) {
    if (p.verdict === "discard") continue;
    const orig = new Map(p.original.map((x) => [x.isoDate, x]));
    for (const c of p.corrected) {
      const o = orig.get(c.isoDate);
      const ventas = c.actual ?? o?.actual;
      lines.push(
        [
          csv(p.productId),
          csv(p.productName),
          csv(p.location),
          c.isoDate,
          o ? String(o.forecast) : "",
          String(c.forecast),
          ventas === undefined ? "" : String(ventas),
          p.verdict,
          String(p.quality),
        ].join(","),
      );
    }
  }
  return lines.join("\n");
}

export function exportDiscardCsv(products: ProductResult[]): string {
  const header = "sku,nombre,deposito,puntos,razon,pista,calidad,wape";
  const lines = [header];
  for (const p of products.filter((x) => x.verdict === "discard")) {
    lines.push(
      [
        csv(p.productId),
        csv(p.productName),
        csv(p.location),
        String(p.original.length),
        csv(p.discard.reason),
        csv(p.discard.keepHint),
        String(p.quality),
        p.metricsOriginal.wape === null ? "" : (p.metricsOriginal.wape * 100).toFixed(1),
      ].join(","),
    );
  }
  return lines.join("\n");
}

export function exportModelsCsv(products: ProductResult[]): string {
  const header = "sku,nombre,deposito,veredicto,clase_demanda,modelo,score,por_que,librerias,hiperparametros";
  const lines = [header];
  for (const p of products) {
    for (const m of p.models.slice(0, 3)) {
      lines.push(
        [
          csv(p.productId),
          csv(p.productName),
          csv(p.location),
          p.verdict,
          p.profile.intermittency,
          csv(m.name),
          String(m.score),
          csv(m.whyThisProduct),
          csv(m.libraries),
          csv(m.hyperparameters),
        ].join(","),
      );
    }
  }
  return lines.join("\n");
}

function csv(v: string): string {
  if (/[",\n]/.test(v)) return `"${v.replace(/"/g, '""')}"`;
  return v;
}
