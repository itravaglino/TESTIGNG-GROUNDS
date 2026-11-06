import { describe, expect, it } from "vitest";
import { parseForecastCsv, parseNumber, splitCsvLine } from "./parse";
import { maeOf, mapeOf, maseOf, wapeOf } from "./metrics";
import { runQa } from "./pipeline";
import { sampleForecastCsv, SAMPLE_WIDE } from "./sample";
import { classifyDemand } from "./classify";

describe("parse", () => {
  it("parsea punto y coma y decimal coma", () => {
    const csv = "producto;fecha;pronostico;real\nA;2024-01-01;1.234,5;1.000,0\n";
    const r = parseForecastCsv(csv);
    expect(r.delimiter).toBe(";");
    expect(r.decimalComma).toBe(true);
    expect(r.rows).toHaveLength(1);
    expect(r.rows[0]!.forecast).toBeCloseTo(1234.5);
    expect(r.rows[0]!.actual).toBeCloseTo(1000);
  });

  it("parseNumber con decimal coma", () => {
    expect(parseNumber("1.234,56", true)).toBeCloseTo(1234.56);
  });

  it("respeta comillas", () => {
    expect(splitCsvLine('"a,b",c', ",")).toEqual(["a,b", "c"]);
  });

  it("convierte formato ancho", () => {
    const r = parseForecastCsv(SAMPLE_WIDE);
    expect(r.format).toBe("wide");
    expect(r.rows.length).toBe(8);
  });
});

describe("metrics", () => {
  it("MAE de [1,2] vs [1,3] es 0.5", () => {
    expect(maeOf([{ f: 1, a: 1 }, { f: 2, a: 3 }])).toBeCloseTo(0.5);
  });

  it("MAPE es undefined si todos los reales son 0", () => {
    expect(mapeOf([{ f: 1, a: 0 }, { f: 2, a: 0 }])).toBeNull();
  });

  it("WAPE pondera por volumen", () => {
    const w = wapeOf([
      { f: 10, a: 10 },
      { f: 0, a: 100 },
    ]);
    expect(w).toBeCloseTo((100 / 110) * 100);
  });

  it("MASE vs naive lag-1", () => {
    const ps = [
      { f: 2, a: 1 },
      { f: 3, a: 2 },
    ];
    const actuals = [1, 2];
    const mase = maseOf(ps, actuals);
    expect(mase).not.toBeNull();
    expect(mase!).toBeGreaterThan(0);
  });
});

describe("classify", () => {
  it("detecta demanda intermitente", () => {
    const xs = [0, 0, 0, 5, 0, 0, 0, 4, 0, 0, 0, 6];
    const c = classifyDemand(xs);
    expect(c.demandClass).toBe("intermittent");
    expect(c.adi!).toBeGreaterThan(1.32);
  });
});

describe("pipeline", () => {
  it("corrige negativos y no los deja en el forecast limpio", () => {
    const csv = `producto,fecha,pronostico,real
X,2024-01-01,10,10
X,2024-02-01,-5,11
X,2024-03-01,12,12
X,2024-04-01,11,10
X,2024-05-01,10,9
X,2024-06-01,13,12
X,2024-07-01,12,11
X,2024-08-01,14,13
`;
    const qa = runQa(csv);
    const p = qa.products[0]!;
    expect(p.series.every((s) => s.forecast === null || s.forecast >= 0)).toBe(true);
    expect(p.corrections.some((c) => c.id === "clip_neg")).toBe(true);
    expect(p.verdict).toBe("correct");
  });

  it("descarta historia demasiado corta", () => {
    const csv = `producto,fecha,pronostico,real
Z,2024-01-01,1,1
Z,2024-02-01,2,2
Z,2024-03-01,3,3
`;
    const qa = runQa(csv);
    expect(qa.products[0]!.verdict).toBe("discard");
  });

  it("duplicados: last-wins", () => {
    const csv = `producto,fecha,pronostico,real
D,2024-01-01,1,1
D,2024-01-01,9,1
D,2024-02-01,2,2
D,2024-03-01,3,3
D,2024-04-01,3,3
D,2024-05-01,3,3
D,2024-06-01,3,3
D,2024-07-01,3,3
D,2024-08-01,3,3
`;
    const qa = runQa(csv);
    const jan = qa.products[0]!.series.find((s) => s.date.startsWith("2024-01"));
    expect(jan?.forecastRaw).toBe(9);
  });

  it("muestra: 8 productos, Croston en intermitente, outlier y sesgo", () => {
    const qa = runQa(sampleForecastCsv());
    expect(qa.products).toHaveLength(8);
    const by = Object.fromEntries(qa.products.map((p) => [p.product, p]));
    expect(by["SKU-CORTA"]!.verdict).toBe("discard");
    expect(by["SKU-NEG"]!.corrections.some((c) => c.id === "clip_neg")).toBe(true);
    expect(by["SKU-INT"]!.demandClass).toBe("intermittent");
    expect(by["SKU-INT"]!.models.some((m) => m.id === "croston")).toBe(true);
    expect(by["SKU-OUT"]!.issues.some((i) => i.id === "outliers" || i.id === "spike")).toBe(true);
    expect(by["SKU-BIAS"]!.metrics.find((m) => m.id === "pbias")!.value!).toBeGreaterThan(20);
    expect(by["SKU-LISO"]!.verdict).toBe("keep");
    expect(by["SKU-BIAS"]!.verdict).toBe("correct");
    expect(by["SKU-CONST"]!.verdict).toBe("correct");
    expect(by["SKU-INT"]!.verdict).toBe("correct");
    expect(qa.portfolio.wape).not.toBeNull();
  });
});
