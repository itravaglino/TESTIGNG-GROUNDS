import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parseForecastCsv, parseDate, parseNumber } from "../src/engine/parse";
import { computeMetrics } from "../src/engine/metrics";
import { profileSeries } from "../src/engine/profile";
import { diagnoseSeries } from "../src/engine/diagnose";
import { correctSeries, discardDecision } from "../src/engine/correct";
import { runForecastQa } from "../src/engine/pipeline";
import { buildSampleCsv } from "../src/engine/sample";
import type { ForecastPoint } from "../src/engine/types";

function pt(iso: string, forecast: number, actual?: number): ForecastPoint {
  const date = parseDate(iso)!;
  return { date, isoDate: iso, forecast, actual, raw: {} };
}

describe("parse", () => {
  it("detects semicolon, decimal comma and Spanish headers", () => {
    const csv = "sku;nombre;fecha;pronostico;ventas\nA;Leche;06/01/2025;10,5;9,0\n";
    const r = parseForecastCsv(csv);
    expect(r.report.delimiter).toBe("punto y coma");
    expect(r.rows).toHaveLength(1);
    expect(r.rows[0].productId).toBe("A");
    expect(r.rows[0].point.forecast).toBeCloseTo(10.5);
    expect(r.rows[0].point.actual).toBeCloseTo(9);
  });

  it("rejects empty file", () => {
    expect(parseForecastCsv("").report.errors[0].message).toMatch(/vacío/i);
  });

  it("parses ISO weeks", () => {
    const d = parseDate("2025-W02");
    expect(d).toBeTruthy();
  });

  it("parseNumber handles NA and European decimals", () => {
    expect(parseNumber("NA")).toBeUndefined();
    expect(parseNumber("1.234,5")).toBeCloseTo(1234.5);
  });
});

describe("metrics", () => {
  it("computes WAPE and bias on a known series", () => {
    const s = [
      pt("2025-01-06", 10, 10),
      pt("2025-01-13", 12, 10),
      pt("2025-01-20", 8, 10),
      pt("2025-01-27", 10, 10),
    ];
    const m = computeMetrics(s, 1);
    expect(m.wape).toBeCloseTo(4 / 40);
    expect(m.me).toBeCloseTo(0);
    expect(m.nWithActual).toBe(4);
  });

  it("returns null accuracy without actuals", () => {
    const m = computeMetrics([pt("2025-01-06", 3), pt("2025-01-13", 4)]);
    expect(m.wape).toBeNull();
    expect(m.meanForecast).toBeCloseTo(3.5);
  });
});

describe("diagnose + correct", () => {
  it("clips negatives and fills weekly gaps", () => {
    const s = [
      pt("2025-01-06", 10, 10),
      pt("2025-01-13", 9, 9),
      pt("2025-01-27", -4, 8),
      pt("2025-02-03", 8, 8),
    ];
    const profile = profileSeries(s);
    const issues = diagnoseSeries(s, profile);
    expect(issues.some((i) => i.code === "negative")).toBe(true);
    const { corrected, corrections } = correctSeries(s, profile);
    expect(corrected.every((p) => p.forecast >= 0)).toBe(true);
    expect(corrections.some((c) => c.code === "clip_neg")).toBe(true);
    expect(corrected.length).toBeGreaterThanOrEqual(4);
  });

  it("discards all-zero forecasts", () => {
    const s = Array.from({ length: 12 }, (_, i) => pt(`2025-0${i < 9 ? 1 : 2}-${String((i % 9) + 1).padStart(2, "0")}`, 0, 0));
    const profile = profileSeries(s);
    const issues = diagnoseSeries(s, profile);
    const d = discardDecision(s, issues, computeMetrics(s), profile);
    expect(d.discard).toBe(true);
  });

  it("discards scale mismatch", () => {
    const s = Array.from({ length: 16 }, (_, i) => {
      const day = 1 + (i % 28);
      return pt(`2025-01-${String(day).padStart(2, "0")}`, 1200, 10);
    });
    const profile = profileSeries(s);
    const issues = diagnoseSeries(s, profile);
    expect(issues.some((i) => i.code === "scale")).toBe(true);
    expect(discardDecision(s, issues, computeMetrics(s), profile).discard).toBe(true);
  });
});

describe("sample pipeline", () => {
  it("classifies the 12 example products", () => {
    const out = runForecastQa(buildSampleCsv());
    expect(out.summary.total).toBe(12);
    const by = Object.fromEntries(out.products.map((p) => [p.productId, p]));
    expect(by["SKU-LECHE-1L"].verdict).toBe("keep");
    expect(by["SKU-PAN-BAG"].verdict).toBe("correct");
    expect(by["SKU-YOGUR"].verdict).toBe("correct");
    expect(by["SKU-ACEITE"].verdict).toBe("correct");
    expect(by["SKU-ZERO"].verdict).toBe("discard");
    expect(by["SKU-CAJAS"].verdict).toBe("discard");
    expect(by["SKU-NUEVO"].verdict).toBe("discard");
    expect(by["SKU-BIAS"].verdict).toBe("correct");
    expect(by["SKU-FILTRO"].models[0].id).toMatch(/croston|sba|tsb|analog/i);
    expect(by["SKU-LECHE-1L"].metricsCorrected.wape).not.toBeNull();
    expect(by["SKU-LECHE-1L"].metricsCorrected.wape!).toBeLessThan(0.2);
    expect(out.products.every((p) => p.models.length >= 3)).toBe(true);
  });

  it("classifies the 8-SKU shared fixture", () => {
    const csv = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "fixtures/lote-8-skus.csv"),
      "utf8",
    );
    const parsed = parseForecastCsv(csv);
    expect(new Set(parsed.rows.map((r) => r.productId)).size).toBe(8);
    const out = runForecastQa(csv);
    const by = Object.fromEntries(out.products.map((p) => [p.productId, p]));
    expect(out.summary.total).toBe(8);
    expect(by["ZERO-01"].verdict).toBe("discard");
    expect(by["SCALE-01"].verdict).toBe("discard");
    expect(by["NEG-01"].verdict).toBe("correct");
    expect(by["NEG-01"].corrected.every((p) => p.forecast >= 0)).toBe(true);
    expect(by["BIAS-01"].verdict).toBe("correct");
    expect(Math.abs(by["BIAS-01"].metricsCorrected.biasPct ?? 1)).toBeLessThan(0.08);
    expect(by["GOOD-01"].verdict).toBe("keep");
    expect(by["GOOD-01"].metricsCorrected.wape!).toBeLessThan(0.05);
    expect(by["INTER-01"].profile.intermittency).toMatch(/intermittent|lumpy/);
    expect(by["INTER-01"].models[0].id).toMatch(/croston|sba|tsb/);
    expect(by["MISS-01"].verdict).toBe("correct");
  });

  it("maps English aliases", () => {
    const csv = "product_id,date,forecast,actual\nX,2025-01-06,5,5\nX,2025-01-13,5,5\nX,2025-01-20,5,5\nX,2025-01-27,5,5\nX,2025-02-03,5,5\nX,2025-02-10,5,5\nX,2025-02-17,5,5\nX,2025-02-24,5,5\n";
    const out = runForecastQa(csv);
    expect(out.summary.total).toBe(1);
    expect(out.products[0].verdict).toBe("keep");
  });
});
