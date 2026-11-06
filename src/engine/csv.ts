import type { ProcessedRow } from "./types";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/[;"\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

const HEADER = [
  "producto",
  "nombre",
  "fecha",
  "forecast",
  "forecast_original",
  "real",
  "modelo",
  "ubicacion",
  "canal",
  "horizonte",
  "lower",
  "upper",
  "disposicion",
  "correccion",
  "motivo_descarte",
];

export function rowsToCsv(rows: ProcessedRow[]): string {
  const lines = [HEADER.join(";")];
  for (const row of rows) {
    lines.push(
      [
        row.productId,
        row.productName,
        row.date,
        Number.isFinite(row.forecast) ? row.forecast.toFixed(4) : "",
        Number.isFinite(row.originalForecast) ? row.originalForecast.toFixed(4) : "",
        row.actual === null ? "" : row.actual.toFixed(4),
        row.model ?? "",
        row.location ?? "",
        row.channel ?? "",
        row.horizon ?? "",
        row.lower ?? "",
        row.upper ?? "",
        row.disposition,
        row.correction ?? "",
        row.discardReason ?? "",
      ]
        .map(cell)
        .join(";"),
    );
  }
  return lines.join("\n");
}
