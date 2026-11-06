function monthsBetween(start: string, end: string): string[] {
  const out: string[] = [];
  const [sy, sm] = start.split("-").map(Number);
  const [ey, em] = end.split("-").map(Number);
  let y = sy!;
  let m = sm!;
  while (y < ey! || (y === ey && m <= em!)) {
    out.push(`${y}-${String(m).padStart(2, "0")}-01`);
    m++;
    if (m > 12) {
      m = 1;
      y++;
    }
  }
  return out;
}

function seasonal(i: number, base: number): number {
  const month = i % 12;
  const seas = [0.85, 0.8, 0.9, 1.0, 1.05, 1.1, 0.95, 0.9, 1.05, 1.15, 1.25, 1.4][month]!;
  const trend = 1 + i * 0.008;
  return Math.round(base * seas * trend);
}

/** Long-format sample used in the product demo (planted defects). */
export function sampleForecastCsv(): string {
  const dates = monthsBetween("2024-01", "2025-10");
  const rows: string[] = ["producto,fecha,pronostico,real,modelo,canal"];

  dates.forEach((d, i) => {
    const actual = seasonal(i, 120);
    const fc = Math.round(actual * (0.96 + (i % 3) * 0.02));
    rows.push(`SKU-LISO,${d},${fc},${actual},holt_winters,retail`);
  });

  dates.forEach((d, i) => {
    const actual = i % 4 === 0 ? 18 + (i % 5) : 0;
    const fc = 8;
    rows.push(`SKU-INT,${d},${fc},${actual},ets,retail`);
  });

  dates.forEach((d, i) => {
    const actual = seasonal(i, 80);
    let fc = Math.round(actual * 1.05);
    if (i === 4 || i === 11) fc = -25;
    rows.push(`SKU-NEG,${d},${fc},${actual},sarima,retail`);
  });

  dates.forEach((d, i) => {
    if (i === 6 || i === 7 || i === 15) return;
    const actual = seasonal(i, 60);
    const fc = Math.round(actual * 0.98);
    rows.push(`SKU-GAP,${d},${fc},${actual},ets,mayorista`);
  });

  dates.forEach((d, i) => {
    const actual = seasonal(i, 90);
    let fc = Math.round(actual * 1.02);
    if (i === 10) fc = 8500;
    rows.push(`SKU-OUT,${d},${fc},${actual},prophet,retail`);
  });

  dates.forEach((d, i) => {
    const actual = seasonal(i, 100);
    const fc = Math.round(actual * 1.4);
    rows.push(`SKU-BIAS,${d},${fc},${actual},media_movil,retail`);
  });

  dates.slice(-4).forEach((d, i) => {
    rows.push(`SKU-CORTA,${d},${40 + i},${38 + i},naive,retail`);
  });

  dates.forEach((d, i) => {
    const actual = seasonal(i, 70);
    rows.push(`SKU-CONST,${d},100,${actual},constante,retail`);
  });

  return rows.join("\n") + "\n";
}

export const SAMPLE_WIDE = `producto,2024-01-01,2024-02-01,2024-03-01,2024-04-01
SKU-WIDE,10,12,11,15
SKU-WIDE-B,3,0,4,0
`;
