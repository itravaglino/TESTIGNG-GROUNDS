import { describe, expect, it } from "vitest";
import { computeAccuracy, computePoint } from "../metrics";
import { parseForecastCsv, parseNumber } from "../parse";
import { processRows } from "../correct";
import { recommendModels } from "../recommend";
import { runPipeline } from "../pipeline";
import { DEFAULT_GATES } from "../metrics";
import type { CanonicalRow, SeriesProfile } from "../types";

describe("métricas Grok-7", () => {
  const points = [
    { forecast: 9, actual: 10 },
    { forecast: 15, actual: 12 },
    { forecast: 8, actual: 8 },
    { forecast: 20, actual: 11 },
  ];

  it("MAE RMSE MAPE WAPE", () => {
    const m = computeAccuracy(points);
    expect(m.mae).toBeCloseTo(3.25, 10);
    expect(m.rmse).toBeCloseTo(Math.sqrt(91 / 4), 10);
    expect(m.mape).toBeCloseTo((257 / 880) * 100, 10);
    expect(m.wape).toBeCloseTo((13 / 41) * 100, 10);
  });

  it("MAPE omite reales en cero", () => {
    const m = computeAccuracy([
      { forecast: 5, actual: 0 },
      { forecast: 10, actual: 8 },
    ]);
    expect(m.mape).toBeCloseTo((2 / 8) * 100, 8);
    expect(m.nWithActual).toBe(2);
  });

  it("computePoint error = forecast - actual", () => {
    const p = computePoint(9, 10);
    expect(p.error).toBe(-1);
    expect(p.absError).toBe(1);
  });
});

describe("parseo", () => {
  it("lee DD/MM/YYYY y 1.234,56", () => {
    const csv = "producto;fecha;forecast\nA;15/03/2025;1.234,56\n";
    const { rows } = parseForecastCsv(csv);
    expect(rows[0].date).toBe("2025-03-15");
    expect(rows[0].forecast).toBeCloseTo(1234.56);
  });

  it("parseNumber europeo y US", () => {
    expect(parseNumber("1.234,56")).toBeCloseTo(1234.56);
    expect(parseNumber("1,234.56")).toBeCloseTo(1234.56);
    expect(parseNumber("(12)")).toBe(-12);
  });
});

function row(partial: Partial<CanonicalRow>): CanonicalRow {
  return {
    line: 1,
    productId: "P",
    productName: "P",
    date: "2025-01-06",
    timestamp: Date.UTC(2025, 0, 6, 12),
    forecast: 10,
    actual: 10,
    model: null,
    location: null,
    channel: null,
    horizon: null,
    lower: null,
    upper: null,
    extra: {},
    ...partial,
  };
}

describe("corrección y descarte", () => {
  it("recorta negativos a 0", () => {
    const { kept } = processRows(
      [row({ forecast: -4, actual: 3 })],
      [],
      { n: 12 } as SeriesProfile,
      DEFAULT_GATES,
    );
    expect(kept[0].forecast).toBe(0);
    expect(kept[0].disposition).toBe("corrected");
  });

  it("descarta duplicados y conserva el último", () => {
    const { kept, discarded } = processRows(
      [
        row({ line: 1, forecast: 10, date: "2025-01-06" }),
        row({ line: 2, forecast: 12, date: "2025-01-06" }),
      ],
      [],
      { n: 12 } as SeriesProfile,
      DEFAULT_GATES,
    );
    expect(kept).toHaveLength(1);
    expect(kept[0].forecast).toBe(12);
    expect(discarded.some((r) => r.discardReason?.includes("Duplicado"))).toBe(true);
  });
});

describe("recomendación", () => {
  it("prioriza Croston en intermitente", () => {
    const profile = {
      productId: "X",
      productName: "X",
      n: 52,
      nWithActual: 40,
      frequency: "weekly",
      start: null,
      end: null,
      meanForecast: 2,
      meanActual: 2,
      stdForecast: 1,
      stdActual: 3,
      cvForecast: 0.5,
      cvActual: 1.5,
      zeroForecastShare: 0.1,
      zeroActualShare: 0.7,
      intermittence: 0.7,
      adi: 3,
      cv2: 0.3,
      demandClass: "intermittent",
      trend: "flat",
      seasonalStrength: 0.1,
      seasonLength: 52,
      modelsUsed: ["ses"],
      locations: ["A"],
      channels: ["B"],
    } as SeriesProfile;
    const ranked = recommendModels(profile, {
      n: 40,
      nWithActual: 40,
      me: 0,
      mae: 1,
      mse: 1,
      rmse: 1,
      mape: 80,
      smape: 70,
      wape: 60,
      mdape: 50,
      mpe: 10,
      biasPct: 10,
      trackingSignal: 1,
      mase: 1.4,
      rmsse: 1.3,
      r2: 0,
      corr: 0,
      theilU: 1.2,
      hitRate: 0.2,
      overforecastRate: 0.5,
      underforecastRate: 0.5,
      coverage: 50,
      meanIntervalWidth: 4,
      pinball50: 0.5,
      maxAbsError: 8,
      p90AbsError: 5,
    });
    expect(ranked[0].id).toBe("croston");
  });
});

describe("pipeline de muestra", () => {
  it("evalúa un CSV mínimo de punta a punta", () => {
    const csv = [
      "producto;nombre;fecha;forecast;real;modelo",
      "A;Leche;2025-01-06;10;11;holt_winters",
      "A;Leche;2025-01-13;12;12;holt_winters",
      "A;Leche;2025-01-20;11;10;holt_winters",
      "A;Leche;2025-01-27;13;12;holt_winters",
      "A;Leche;2025-02-03;12;14;holt_winters",
      "A;Leche;2025-02-10;14;13;holt_winters",
      "A;Leche;2025-02-17;13;13;holt_winters",
      "A;Leche;2025-02-24;15;14;holt_winters",
      "B;Yerba;2025-01-06;0;0;ses",
      "B;Yerba;2025-01-13;0;5;ses",
      "B;Yerba;2025-01-20;-3;0;ses",
      "B;Yerba;2025-01-27;0;0;ses",
    ].join("\n");
    const result = runPipeline(csv);
    expect(result.summary.products).toBe(2);
    expect(result.products.find((p) => p.productId === "B")?.rows.some((r) => r.forecast === 0)).toBe(
      true,
    );
    expect(result.cleanedCsv).toContain("producto");
  });
});
