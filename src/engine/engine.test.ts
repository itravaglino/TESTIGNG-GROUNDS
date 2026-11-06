import { describe, expect, it } from "vitest";
import { analyzeCsv } from "./analyze";
import { parseNumber } from "./numbers";
import { parseCsvText } from "./parse";

function flagsOf(csv: string, sku?: string) {
  const report = analyzeCsv(csv);
  const p = sku ? report.products.find((x) => x.productId === sku) : report.products[0];
  expect(p).toBeTruthy();
  return { report, p: p!, ids: p!.flags.map((f) => f.id) };
}

describe("number locale", () => {
  it("parses European thousands and decimals", () => {
    expect(parseNumber("1.234,56", "es")).toBeCloseTo(1234.56);
    expect(parseNumber("1,234.56", "en")).toBeCloseTo(1234.56);
  });
});

describe("fixtures", () => {
  it("1 seasonal keep", () => {
    const csv = `sku,date,actual,forecast
S1,2023-01,100,
S1,2023-02,80,
S1,2023-03,60,
S1,2023-04,70,
S1,2023-05,90,
S1,2023-06,120,
S1,2023-07,150,
S1,2023-08,140,
S1,2023-09,110,
S1,2023-10,90,
S1,2023-11,80,
S1,2023-12,100,
S1,2024-01,110,100
S1,2024-02,88,80
S1,2024-03,66,60
S1,2024-04,77,70
S1,2024-05,99,90
S1,2024-06,132,120
S1,2024-07,165,150
S1,2024-08,154,140
S1,2024-09,121,110
S1,2024-10,99,90
S1,2024-11,88,80
S1,2024-12,110,100`;
    const { p } = flagsOf(csv, "S1");
    expect(p.verdict).toBe("keep");
    const wape = p.metrics.find((m) => m.id === "wape")?.value;
    expect(wape).toBeCloseTo(9.09, 1);
    expect(["holt_winters", "seasonal_naive", "theta", "ses"]).toContain(p.recommended.id);
  });

  it("2 intermittent mape off croston/tsb", () => {
    const months = [
      [0, 0.7], [0, 0.7], [0, 0.7], [5, 0.7], [0, 0.7], [0, 0.7], [0, 0.7], [0, 0.7], [2, 0.7], [0, 0.7], [0, 0.7], [0, 0.7],
      [0, 0.7], [8, 0.7], [0, 0.7], [0, 0.7], [0, 0.7], [0, 0.7], [0, 0.7], [1, 0.7], [0, 0.7], [0, 0.7], [0, 0.7], [0, 0.7],
    ];
    const lines = ["sku,date,actual,forecast"];
    months.forEach(([a, f], i) => {
      const y = i < 12 ? 2023 : 2024;
      const m = String((i % 12) + 1).padStart(2, "0");
      lines.push(`P1,${y}-${m},${a},${f}`);
    });
    const { p, ids } = flagsOf(lines.join("\n"), "P1");
    expect(p.verdict).toBe("keep");
    expect(ids).toContain("INT_01");
    expect(ids).toContain("MET_MAPE_OFF");
    expect(["sba", "tsb", "croston", "pz"]).toContain(p.recommended.id);
    expect(p.metrics.find((m) => m.id === "wape")?.defined).toBe(true);
  });

  it("3 negatives clip", () => {
    const csv = `sku,date,actual,forecast
N1,2024-01,10,-3
N1,2024-02,12,8
N1,2024-03,9,-1
N1,2024-04,11,10`;
    const { p, ids } = flagsOf(csv, "N1");
    expect(ids).toContain("NEG_01");
    expect(p.mutations.some((m) => m.code === "NEG_CLIP")).toBe(true);
    expect(p.verdict).not.toBe("discard");
  });

  it("4 identity leak discard", () => {
    const csv = `sku,date,actual,forecast
L1,2024-01,10,10
L1,2024-02,20,20
L1,2024-03,15,15
L1,2024-04,30,30
L1,2024-05,12,12
L1,2024-06,18,18`;
    const { p, ids } = flagsOf(csv, "L1");
    expect(ids).toContain("LEAK_01");
    expect(p.verdict).toBe("discard");
  });

  it("5 constant vs trend", () => {
    const csv = `sku,date,actual,forecast
T1,2024-01,40,100
T1,2024-02,50,100
T1,2024-03,60,100
T1,2024-04,70,100
T1,2024-05,80,100
T1,2024-06,90,100
T1,2024-07,100,100
T1,2024-08,110,100
T1,2024-09,120,100
T1,2024-10,130,100
T1,2024-11,140,100
T1,2024-12,150,100`;
    const { p, ids } = flagsOf(csv, "T1");
    expect(ids).toContain("TRD_01");
    expect(["damped_holt", "holt"]).toContain(p.recommended.id);
    expect(p.verdict).toMatch(/discard|review/);
  });

  it("6 duplicate conflict", () => {
    const csv = `sku,date,actual,forecast
A,2024-01,10,12
A,2024-01,15,9
A,2024-02,11,11`;
    const { ids } = flagsOf(csv, "A");
    expect(ids.some((id) => id.startsWith("DUP"))).toBe(true);
  });

  it("7 european decimals", () => {
    const csv = `sku;date;actual;forecast
E1;2024-01;"1.234,56";"1.200,00"
E1;2024-02;"980,50";"1.000,00"`;
    const parsed = parseCsvText(csv);
    expect(parsed.rows[0].actual).toBeCloseTo(1234.56);
    const { p } = flagsOf(csv, "E1");
    const wape = p.metrics.find((m) => m.id === "wape")?.value;
    expect(wape).toBeCloseTo(2.44, 0);
  });

  it("8 wide months", () => {
    const csv = `sku,series,2024-01,2024-02,2024-03,2024-04
W1,actual,10,20,30,40
W1,forecast,12,18,33,36`;
    const parsed = parseCsvText(csv);
    expect(parsed.orientation).toBe("wide");
    expect(parsed.rows.length).toBe(4);
    const { p } = flagsOf(csv, "W1");
    const wape = p.metrics.find((m) => m.id === "wape")?.value;
    expect(wape).toBeCloseTo(11, 0);
  });

  it("9 short analog", () => {
    const csv = `sku,date,actual,forecast
NEW,2024-01,5,
NEW,2024-02,8,6`;
    const { p, ids } = flagsOf(csv, "NEW");
    expect(ids).toContain("SHORT_01");
    expect(p.verdict).toBe("review");
    expect(p.recommended.id).toBe("analog");
  });

  it("10 outlier spike", () => {
    const lines = ["sku,date,actual,forecast"];
    for (let i = 1; i <= 12; i++) {
      const a = i === 6 ? 1000 : 10;
      lines.push(`O1,2024-${String(i).padStart(2, "0")},${a},10`);
    }
    const { ids } = flagsOf(lines.join("\n"), "O1");
    expect(ids).toContain("OUT_01");
  });

  it("11 two models pick holt", () => {
    const csv = `sku,date,model,actual,forecast
A,2024-01,naive,100,80
A,2024-01,holt,100,98
A,2024-02,naive,110,80
A,2024-02,holt,110,108
A,2024-03,naive,120,80
A,2024-03,holt,120,119
A,2024-04,naive,130,80
A,2024-04,holt,130,128`;
    const report = analyzeCsv(csv);
    const holt = report.products.find((p) => p.model === "holt")!;
    const naive = report.products.find((p) => p.model === "naive")!;
    expect(holt.winnerAmongUploaded).toBe(true);
    expect(holt.metrics.find((m) => m.id === "wape")!.value!).toBeLessThan(naive.metrics.find((m) => m.id === "wape")!.value!);
  });

  it("12 discontinued zeros", () => {
    const csv = `sku,date,actual,forecast
Z1,2024-01,0,0
Z1,2024-02,0,0
Z1,2024-03,0,0
Z1,2024-04,0,0
Z1,2024-05,0,0
Z1,2024-06,0,0`;
    const { p, ids } = flagsOf(csv, "Z1");
    expect(ids).toContain("DISC_01");
    expect(p.verdict).toBe("discard");
    expect(ids).not.toContain("LEAK_01");
  });
});
