import type { ParsedRow, Point, ProductReport, QaReport, Verdict } from "./types";
import { parseForecastCsv } from "./parse";
import { analyzeQuality } from "./quality";
import { correctSeries } from "./correct";
import { classifyDemand, detectSeasonality, detectTrend, seriesValues } from "./classify";
import { computeMetrics, mean, pairs, wapeOf } from "./metrics";
import { improvements, recommendModels, scoreProduct } from "./recommend";

const MAX_ROWS = 80000;
const MAX_PRODUCTS = 5000;

function keyOf(r: ParsedRow): string {
  return [r.product, r.channel ?? "", r.warehouse ?? ""].join("|");
}

function toPoint(r: ParsedRow): Point {
  return {
    date: r.date,
    period: r.period,
    forecastRaw: r.forecast,
    forecast: r.forecast,
    actual: r.actual,
    lower: r.lower,
    upper: r.upper,
  };
}

export function analyzeProduct(rows: ParsedRow[]): ProductReport {
  const first = rows[0]!;
  const raw: Point[] = rows.map(toPoint);
  const { issues, frequency } = analyzeQuality(raw);
  const fatal = issues.some((i) => i.severity === "fatal");
  const { series, corrections } = fatal && rows.length < 4 ? { series: raw, corrections: [] } : correctSeries(raw);

  const actuals = seriesValues(series, "actual");
  const forecasts = seriesValues(series, "forecast");
  const { demandClass, adi, cv2 } = classifyDemand(actuals.length >= 4 ? actuals : forecasts);
  const seasonalLag = detectSeasonality(actuals.length >= 8 ? actuals : forecasts);
  const hasTrend = detectTrend(actuals.length >= 8 ? actuals : forecasts);
  const metrics = computeMetrics(series);
  const constantForecast = forecasts.length >= 4 && forecasts.every((x) => x === forecasts[0]);
  const leakage = issues.some((i) => i.id === "leakage");

  const wape = metrics.find((m) => m.id === "wape")?.value;
  const pbias = metrics.find((m) => m.id === "pbias")?.value;
  const mase = metrics.find((m) => m.id === "mase")?.value;
  const skill = metrics.find((m) => m.id === "skill_naive")?.value;
  const accuracyBad =
    constantForecast ||
    leakage ||
    (pbias != null && Math.abs(pbias) > 20) ||
    (mase != null && mase > 1.15) ||
    (skill != null && skill < 0) ||
    (wape != null && wape > 35 && demandClass !== "intermittent" && demandClass !== "lumpy");

  let verdict: Verdict = "keep";
  if (fatal || issues.some((i) => i.id === "short_history" || i.id === "all_zero")) verdict = "discard";
  else if (corrections.length > 0 || issues.some((i) => i.severity === "error") || accuracyBad) {
    verdict = "correct";
  }

  const models = recommendModels({
    demandClass,
    n: series.length,
    seasonalLag,
    hasTrend,
    hasActuals: actuals.length >= 4,
    constantForecast,
    leakage,
  });
  const score = scoreProduct({ verdict, issues, series });
  const tips = improvements({ demandClass, issues, metrics, verdict, n: series.length, seasonalLag });

  return {
    key: keyOf(first),
    product: first.product,
    channel: first.channel,
    warehouse: first.warehouse,
    modelHint: first.model,
    n: series.length,
    nActual: actuals.length,
    nForecast: forecasts.length,
    frequency,
    demandClass,
    adi,
    cv2,
    seasonalLag,
    hasTrend,
    verdict,
    score,
    issues,
    corrections,
    metrics,
    models,
    improvements: tips,
    series,
  };
}

export function runQa(text: string): QaReport {
  const parse = parseForecastCsv(text);
  if (parse.rows.length > MAX_ROWS) {
    parse.issues.push({
      severity: "error",
      message: `El archivo tiene ${parse.rows.length} filas; analicé las primeras ${MAX_ROWS}.`,
    });
    parse.rows = parse.rows.slice(0, MAX_ROWS);
  }

  const groups = new Map<string, ParsedRow[]>();
  for (const row of parse.rows) {
    const k = keyOf(row);
    const g = groups.get(k);
    if (g) g.push(row);
    else groups.set(k, [row]);
  }

  let products = [...groups.values()].map(analyzeProduct);
  if (products.length > MAX_PRODUCTS) {
    parse.issues.push({
      severity: "error",
      message: `Hay ${products.length} series; analicé las ${MAX_PRODUCTS} de mayor volumen.`,
    });
    products = products
      .sort((a, b) => b.n - a.n)
      .slice(0, MAX_PRODUCTS);
  }

  products.sort((a, b) => a.score - b.score || a.product.localeCompare(b.product));

  const allPairs = products.flatMap((p) => pairs(p.series));
  const keep = products.filter((p) => p.verdict === "keep").length;
  const correct = products.filter((p) => p.verdict === "correct").length;
  const discard = products.filter((p) => p.verdict === "discard").length;
  const mae = allPairs.length ? allPairs.reduce((s, p) => s + Math.abs(p.f - p.a), 0) / allPairs.length : null;
  const mapeVals = allPairs.filter((p) => p.a !== 0).map((p) => Math.abs(p.f - p.a) / Math.abs(p.a));
  const bias = allPairs.length ? mean(allPairs.map((p) => p.f - p.a)) : null;

  return {
    parse,
    products,
    portfolio: {
      products: products.length,
      rows: parse.rows.length,
      keep,
      correct,
      discard,
      wape: wapeOf(allPairs),
      bias,
      mape: mapeVals.length ? (mean(mapeVals)! * 100) : null,
      mae,
      skillNaive: mean(
        products
          .map((p) => p.metrics.find((m) => m.id === "skill_naive")?.value)
          .filter((x): x is number => x !== null && x !== undefined),
      ),
    },
    generatedAt: new Date().toISOString(),
  };
}

export function toCsv(rows: string[][]): string {
  return rows
    .map((r) =>
      r
        .map((c) => {
          if (/[",;\n]/.test(c)) return `"${c.replace(/"/g, '""')}"`;
          return c;
        })
        .join(","),
    )
    .join("\n");
}

export function exportCleaned(report: QaReport): string {
  const header = [
    "producto",
    "canal",
    "deposito",
    "fecha",
    "pronostico_original",
    "pronostico_corregido",
    "real",
    "veredicto",
    "score",
    "clase_demanda",
  ];
  const rows: string[][] = [header];
  for (const p of report.products) {
    if (p.verdict === "discard") continue;
    for (const s of p.series) {
      rows.push([
        p.product,
        p.channel ?? "",
        p.warehouse ?? "",
        s.date,
        s.forecastRaw === null ? "" : String(s.forecastRaw),
        s.forecast === null ? "" : String(s.forecast),
        s.actual === null ? "" : String(s.actual),
        p.verdict,
        String(p.score),
        p.demandClass,
      ]);
    }
  }
  return toCsv(rows);
}

export function exportDiscarded(report: QaReport): string {
  const rows: string[][] = [["producto", "canal", "n", "score", "motivo"]];
  for (const p of report.products.filter((x) => x.verdict === "discard")) {
    rows.push([
      p.product,
      p.channel ?? "",
      String(p.n),
      String(p.score),
      p.issues.map((i) => i.message).join(" | "),
    ]);
  }
  return toCsv(rows);
}

export function exportRecommendations(report: QaReport): string {
  const rows: string[][] = [
    [
      "producto",
      "veredicto",
      "score",
      "clase",
      "adi",
      "cv2",
      "wape",
      "mape",
      "mase",
      "sesgo_pct",
      "modelo_1",
      "por_que",
      "como_empezar",
      "mejoras",
    ],
  ];
  for (const p of report.products) {
    const w = p.metrics.find((m) => m.id === "wape")?.value;
    const mape = p.metrics.find((m) => m.id === "mape")?.value;
    const mase = p.metrics.find((m) => m.id === "mase")?.value;
    const bias = p.metrics.find((m) => m.id === "pbias")?.value;
    const m1 = p.models[0];
    rows.push([
      p.product,
      p.verdict,
      String(p.score),
      p.demandClass,
      p.adi === null ? "" : p.adi.toFixed(3),
      p.cv2 === null ? "" : p.cv2.toFixed(3),
      w === null || w === undefined ? "" : w.toFixed(2),
      mape === null || mape === undefined ? "" : mape.toFixed(2),
      mase === null || mase === undefined ? "" : mase.toFixed(3),
      bias === null || bias === undefined ? "" : bias.toFixed(2),
      m1?.name ?? "",
      m1?.why ?? "",
      m1?.howToStart ?? "",
      p.improvements.join(" • "),
    ]);
  }
  return toCsv(rows);
}
