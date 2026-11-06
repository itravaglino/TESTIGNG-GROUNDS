import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runPipeline } from "../pipeline";

describe("muestra plantada", () => {
  const csv = readFileSync(new URL("../../../public/sample-forecast.csv", import.meta.url), "utf8");

  it("detecta los 8 productos y defectos conocidos", () => {
    const result = runPipeline(csv);
    expect(result.summary.products).toBe(8);
    const byId = Object.fromEntries(result.products.map((p) => [p.productId, p]));
    expect(byId["SKU-1003"].issues.some((i) => i.code === "SCALE_SHIFT")).toBe(true);
    expect(byId["SKU-1004"].issues.some((i) => i.code === "NEGATIVE_FORECAST")).toBe(true);
    expect(byId["SKU-1005"].issues.some((i) => i.code === "GAP_IN_SERIES")).toBe(true);
    expect(byId["SKU-1006"].issues.some((i) => i.code === "CONSTANT_FORECAST")).toBe(true);
    expect(byId["SKU-1008"].issues.some((i) => i.code === "DUPLICATE_KEY")).toBe(true);
    expect(result.cleanedCsv.split("\n").length).toBeGreaterThan(10);
    expect(result.discardedCsv.split("\n").length).toBeGreaterThan(1);
  });
});
