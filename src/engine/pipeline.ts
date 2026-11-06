import { processRows } from "./correct";
import { rowsToCsv } from "./csv";
import { detectIssues } from "./detect";
import { computeAccuracy, DEFAULT_GATES } from "./metrics";
import { parseForecastCsv } from "./parse";
import { profileSeries, seasonFor } from "./profile";
import { improvementActions, recommendModels } from "./recommend";
import type {
  CanonicalRow,
  PipelineResult,
  PortfolioSummary,
  ProductReport,
  QualityGates,
} from "./types";

function qualityScore(report: Omit<ProductReport, "qualityScore" | "verdict" | "verdictReason">): {
  score: number;
  verdict: ProductReport["verdict"];
  reason: string;
} {
  const { metrics, issues, discarded, profile } = report;
  const critical = issues.filter((i) => i.severity === "critical").length;
  const errors = issues.filter((i) => i.severity === "error").length;
  let score = 80;
  if (metrics.wape !== null) score -= Math.min(40, metrics.wape * 0.6);
  if (metrics.mape !== null) score -= Math.min(20, Math.max(0, metrics.mape - 10) * 0.25);
  if (metrics.mase !== null && metrics.mase > 1) score -= Math.min(20, (metrics.mase - 1) * 15);
  if (metrics.trackingSignal !== null) score -= Math.min(15, Math.abs(metrics.trackingSignal));
  score -= critical * 18;
  score -= errors * 6;
  score -= Math.min(15, discarded.length);
  if (profile.n < 8) score -= 25;
  score = Math.max(0, Math.min(100, Math.round(score)));

  if (critical > 0 || discarded.length === profile.n || score < 25) {
    return {
      score,
      verdict: "descartar",
      reason: "Hay fallas críticas, escala rota o la serie no es operable.",
    };
  }
  if (report.rows.some((r) => r.disposition === "corrected") || errors > 0 || score < 55) {
    return {
      score,
      verdict: "corregir",
      reason: "Se puede usar si aplica las correcciones y cambia de modelo.",
    };
  }
  if (issues.some((i) => i.severity === "warn") || score < 70) {
    return {
      score,
      verdict: "revisar",
      reason: "Aceptable con reservas: mire sesgo, intervalos y holdout.",
    };
  }
  return { score, verdict: "ok", reason: "El pronóstico pasa los controles de calidad." };
}

function reportProduct(productRows: CanonicalRow[], gates: QualityGates): ProductReport {
  const productId = productRows[0].productId;
  const productName = productRows[0].productName;
  const profile = profileSeries(productId, productName, productRows);
  const rawMetrics = computeAccuracy(productRows, { seasonLength: seasonFor(profile.frequency) });
  const issues = detectIssues(productId, productRows, profile, rawMetrics, gates);
  const { kept, discarded } = processRows(productRows, issues, profile, gates);
  const metrics = computeAccuracy(kept, { seasonLength: seasonFor(profile.frequency) });
  const suggestions = recommendModels(profile, metrics).slice(0, 8);
  const improvements = improvementActions(profile, metrics, issues);
  const base = {
    productId,
    productName,
    profile,
    metrics,
    issues,
    rows: kept,
    discarded,
    suggestions,
    improvements,
  };
  const { score, verdict, reason } = qualityScore(base);
  return { ...base, qualityScore: score, verdict, verdictReason: reason };
}

export function runPipeline(text: string, gates: QualityGates = DEFAULT_GATES): PipelineResult {
  const { rows, parse } = parseForecastCsv(text);
  const byProduct = new Map<string, CanonicalRow[]>();
  for (const row of rows) {
    const list = byProduct.get(row.productId) ?? [];
    list.push(row);
    byProduct.set(row.productId, list);
  }
  const products = [...byProduct.values()]
    .map((group) => reportProduct(group, gates))
    .sort((a, b) => a.qualityScore - b.qualityScore || a.productId.localeCompare(b.productId));

  const allIssues = products.flatMap((p) => p.issues);
  const keptRows = products.flatMap((p) => p.rows);
  const discardedRows = products.flatMap((p) => p.discarded);
  const withActual = products.filter((p) => p.metrics.nWithActual > 0);
  const volume = withActual.reduce((s, p) => s + (p.profile.meanActual ?? 0) * p.metrics.nWithActual, 0);
  const weightedWape =
    volume > 0
      ? withActual.reduce(
          (s, p) => s + (p.metrics.wape ?? 0) * (p.profile.meanActual ?? 0) * p.metrics.nWithActual,
          0,
        ) / volume
      : null;
  const weightedMape =
    volume > 0
      ? withActual.reduce(
          (s, p) => s + (p.metrics.mape ?? 0) * (p.profile.meanActual ?? 0) * p.metrics.nWithActual,
          0,
        ) / volume
      : null;
  const weightedRmse =
    volume > 0
      ? withActual.reduce(
          (s, p) => s + (p.metrics.rmse ?? 0) * (p.profile.meanActual ?? 0) * p.metrics.nWithActual,
          0,
        ) / volume
      : null;

  const summary: PortfolioSummary = {
    products: products.length,
    rows: rows.length,
    discardedRows: discardedRows.length,
    correctedRows: keptRows.filter((r) => r.disposition === "corrected").length,
    productsOk: products.filter((p) => p.verdict === "ok").length,
    productsFix: products.filter((p) => p.verdict === "corregir").length,
    productsDiscard: products.filter((p) => p.verdict === "descartar").length,
    productsReview: products.filter((p) => p.verdict === "revisar").length,
    weightedWape,
    weightedMape,
    weightedRmse,
    meanQualityScore:
      products.length === 0
        ? 0
        : products.reduce((s, p) => s + p.qualityScore, 0) / products.length,
  };

  return {
    parse,
    products,
    summary,
    issues: allIssues,
    cleanedCsv: rowsToCsv(keptRows),
    discardedCsv: rowsToCsv(discardedRows),
    generatedAt: new Date().toISOString(),
  };
}

export { DEFAULT_GATES };
