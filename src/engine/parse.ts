import { headerLooksLikePeriod, inferPeriodType, parseDate } from "./dates";
import { parseNumber, voteLocale, type NumberLocale } from "./numbers";
import type { Diagnostic, ForecastRow, ParseResult, PeriodType } from "./types";

function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

const PRODUCT_ID = new Set([
  "sku",
  "sku_id",
  "product_id",
  "productid",
  "item",
  "item_code",
  "itemcode",
  "item_id",
  "codigo",
  "cod",
  "cod_prod",
  "cod_producto",
  "codigo_producto",
  "codigo_articulo",
  "codigo_de_producto",
  "articulo",
  "art",
  "nro_articulo",
  "numero_articulo",
  "material",
  "cod_material",
  "codigo_material",
  "referencia",
  "ref",
  "ean",
  "barcode",
]);

const PRODUCT_NAME = new Set([
  "producto",
  "product",
  "product_name",
  "nombre",
  "nombre_producto",
  "descripcion",
  "desc",
  "detalle",
  "item_description",
]);

const DATE_COLS = new Set(["fecha", "date", "periodo", "period", "fecha_forecast", "fecha_pronostico", "timestamp"]);
const MODEL_COLS = new Set(["modelo", "model", "version", "escenario", "scenario", "fuente", "algoritmo", "metodo"]);
const SERIES_COLS = new Set(["series", "serie", "tipo", "medida", "metric", "variable"]);

const FORECAST = new Set([
  "forecast",
  "fcst",
  "fcast",
  "pronostico",
  "prediccion",
  "prevision",
  "yhat",
  "y_hat",
  "estimado",
  "estimacion",
  "qty_forecast",
  "forecast_qty",
  "plan",
]);
const ACTUAL = new Set([
  "actual",
  "real",
  "ventas",
  "venta",
  "demanda",
  "history",
  "historico",
  "realizado",
  "qty_real",
  "sell_out",
  "sellout",
  "sell_in",
  "sellin",
  "facturado",
  "consumo",
]);
const LO = new Set(["lo", "lower", "lower_bound", "lim_inf", "limite_inferior", "min", "minimo", "p10", "q10"]);
const HI = new Set(["hi", "upper", "upper_bound", "lim_sup", "limite_superior", "max", "maximo", "p90", "q90"]);
const BUDGET = new Set(["budget", "presupuesto", "ppto", "budget_qty"]);

export function parseCsvText(text: string): ParseResult {
  const diagnostics: Diagnostic[] = [];
  const delimiter = detectDelimiter(text);
  const table = parseDelimited(text, delimiter);
  if (table.length === 0) {
    return empty("El archivo no contiene filas de datos.", delimiter);
  }
  const headerIdx = 0;
  const headers = table[headerIdx].map((h) => h.trim());
  const folded = headers.map(fold);
  const body = table.slice(headerIdx + 1).filter((row) => row.some((c) => c.trim() !== ""));

  const periodCols: number[] = [];
  headers.forEach((header, i) => {
    const leaf = header.includes("::") ? header.split("::").pop()!.trim() : header;
    if (headerLooksLikePeriod(leaf) || headerLooksLikePeriod(header) || /^\d{4}[-_]\d{2}$/.test(leaf)) periodCols.push(i);
  });

  const seriesIdx = folded.findIndex((h) => SERIES_COLS.has(h));
  const idIdx = folded.findIndex((h) => PRODUCT_ID.has(h) || h === "sku");
  const nameIdx = folded.findIndex((h) => PRODUCT_NAME.has(h));
  const dateIdx = folded.findIndex((h) => DATE_COLS.has(h));
  const modelIdx = folded.findIndex((h) => MODEL_COLS.has(h));

  let orientation: "long" | "wide" = periodCols.length >= 3 ? "wide" : "long";
  if (dateIdx >= 0) orientation = "long";
  if (seriesIdx >= 0 && periodCols.length >= 2) orientation = "wide";

  const roles = classifyRoles(folded, headers, orientation, periodCols, diagnostics);
  const numberLocale = voteFileLocale(body, roles);

  let rows: ForecastRow[] = [];
  if (orientation === "wide") {
    rows = meltWide({
      headers,
      folded,
      body,
      periodCols,
      idIdx: idIdx >= 0 ? idIdx : nameIdx,
      nameIdx,
      seriesIdx,
      roles,
      numberLocale,
      diagnostics,
    });
  } else {
    rows = parseLong({
      headers,
      folded,
      body,
      roles,
      idIdx: idIdx >= 0 ? idIdx : nameIdx,
      nameIdx,
      dateIdx,
      modelIdx,
      numberLocale,
      diagnostics,
    });
  }

  const dates = rows.map((r) => r.date);
  const locked: PeriodType =
    rows.find((r) => r.periodType !== "unknown" && r.periodType !== "day")?.periodType ?? "unknown";
  const periodType = inferPeriodType(dates, locked);
  rows = rows.map((r) => ({
    ...r,
    periodType: r.periodType === "day" && periodType === "month" ? "month" : r.periodType === "unknown" ? periodType : r.periodType,
    date: periodType === "month" ? r.date.slice(0, 8) + "01" : r.date,
  }));

  const used = headers.filter((_, i) => roles[i] !== "ignore" || periodCols.includes(i));
  const ignored = headers.filter((_, i) => roles[i] === "ignore" && !periodCols.includes(i));

  if (rows.length === 0) {
    diagnostics.push({
      code: "empty_parse",
      severity: "error",
      message: "No se pudo interpretar ninguna fila. Revise encabezados y separador.",
    });
  }

  return {
    rows,
    diagnostics,
    delimiter,
    orientation,
    columnsUsed: used,
    ignoredColumns: ignored.filter(Boolean),
  };
}

function empty(message: string, delimiter: string): ParseResult {
  return {
    rows: [],
    diagnostics: [{ code: "empty", severity: "error", message }],
    delimiter,
    orientation: "long",
    columnsUsed: [],
    ignoredColumns: [],
  };
}

function detectDelimiter(text: string): string {
  const lines = text.split(/\r?\n/).filter((l) => l.trim()).slice(0, 20);
  const counts = { ",": 0, ";": 0, "\t": 0, "|": 0 };
  for (const line of lines) {
    for (const d of Object.keys(counts) as (keyof typeof counts)[]) {
      counts[d] += splitLine(line, d).length;
    }
  }
  const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (ranked[0][1] === ranked[1][1] && counts[";"] > 0) return ";";
  return ranked[0][0];
}

function splitLine(line: string, delimiter: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else inQ = !inQ;
    } else if (ch === delimiter && !inQ) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

function parseDelimited(text: string, delimiter: string): string[][] {
  return text
    .split(/\r?\n/)
    .filter((l) => l.trim() !== "")
    .map((l) => splitLine(l, delimiter).map((c) => c.trim()));
}

type Role =
  | "productId"
  | "productName"
  | "date"
  | "forecast"
  | "actual"
  | "model"
  | "lo"
  | "hi"
  | "budget"
  | "series"
  | "attr"
  | "ignore"
  | "period";

function classifyRoles(
  folded: string[],
  headers: string[],
  orientation: "long" | "wide",
  periodCols: number[],
  diagnostics: Diagnostic[],
): Role[] {
  void headers;
  const roles: Role[] = folded.map(() => "ignore");
  folded.forEach((h, i) => {
    if (PRODUCT_ID.has(h)) roles[i] = "productId";
    else if (PRODUCT_NAME.has(h)) roles[i] = "productName";
    else if (DATE_COLS.has(h)) roles[i] = "date";
    else if (MODEL_COLS.has(h)) roles[i] = "model";
    else if (SERIES_COLS.has(h)) roles[i] = "series";
    else if (FORECAST.has(h)) roles[i] = "forecast";
    else if (ACTUAL.has(h)) roles[i] = "actual";
    else if (LO.has(h)) roles[i] = "lo";
    else if (HI.has(h)) roles[i] = "hi";
    else if (BUDGET.has(h)) roles[i] = "budget";
    else if (periodCols.includes(i)) roles[i] = "period";
    else if (h) roles[i] = "attr";
  });

  folded.forEach((h, i) => {
    const m = h.match(/^(forecast|pronostico|prediccion|yhat|presupuesto|budget)[_]+(.+)$/);
    if (m) {
      roles[i] = m[1].startsWith("ppto") || m[1] === "presupuesto" || m[1] === "budget" ? "budget" : "forecast";
      headers[i] = headers[i];
    }
    const parent = headers[i].split("::");
    if (parent.length === 2) {
      const leaf = fold(parent[1]);
      if (FORECAST.has(leaf) || ACTUAL.has(leaf)) {
        /* handled in melt */
      }
    }
  });

  if (!roles.includes("forecast") && !roles.includes("period") && orientation === "long") {
    const qty = folded.findIndex((h) => h === "qty" || h === "cantidad" || h === "unidades");
    if (qty >= 0) {
      roles[qty] = "forecast";
      diagnostics.push({
        code: "ambiguous_qty",
        severity: "warn",
        message: "La columna de cantidad se tomó como pronóstico.",
      });
    }
  }
  if (!roles.includes("productId") && !roles.includes("productName")) {
    diagnostics.push({
      code: "missing_product",
      severity: "error",
      message: "Falta una columna de producto o SKU.",
    });
  }
  return roles;
}

function voteFileLocale(body: string[][], roles: Role[]): NumberLocale {
  const tokens: string[] = [];
  for (const row of body) {
    row.forEach((cell, i) => {
      if (roles[i] === "forecast" || roles[i] === "actual" || roles[i] === "lo" || roles[i] === "hi" || roles[i] === "period") {
        if (cell) tokens.push(cell);
      }
    });
  }
  return voteLocale(tokens);
}

function parseLong(args: {
  headers: string[];
  folded: string[];
  body: string[][];
  roles: Role[];
  idIdx: number;
  nameIdx: number;
  dateIdx: number;
  modelIdx: number;
  numberLocale: NumberLocale;
  diagnostics: Diagnostic[];
}): ForecastRow[] {
  const { body, roles, idIdx, nameIdx, dateIdx, modelIdx, numberLocale, diagnostics, headers } = args;
  const forecastIdx = roles.findIndex((r) => r === "forecast");
  const actualIdx = roles.findIndex((r) => r === "actual");
  const loIdx = roles.findIndex((r) => r === "lo");
  const hiIdx = roles.findIndex((r) => r === "hi");
  const budgetIdx = roles.findIndex((r) => r === "budget");
  const attrIdx = roles.map((r, i) => (r === "attr" ? i : -1)).filter((i) => i >= 0);
  const out: ForecastRow[] = [];

  body.forEach((row, ri) => {
    const sourceRow = ri + 2;
    const productId = (idIdx >= 0 ? row[idIdx] : row[nameIdx] ?? "").trim();
    const productName = nameIdx >= 0 ? row[nameIdx].trim() || null : null;
    if (!productId) {
      diagnostics.push({
        code: "DQ-R01",
        severity: "discard",
        message: "Falta el código de producto. La fila se descartó.",
        row: sourceRow,
      });
      return;
    }
    if (dateIdx < 0) {
      diagnostics.push({
        code: "DQ-R02",
        severity: "discard",
        message: "Falta la columna de fecha.",
        row: sourceRow,
      });
      return;
    }
    const parsed = parseDate(row[dateIdx]);
    if (!parsed) {
      diagnostics.push({
        code: "DQ-R02",
        severity: "discard",
        message: `Falta la fecha o no se pudo interpretar (${row[dateIdx]}). La fila se descartó.`,
        row: sourceRow,
      });
      return;
    }
    const model = (modelIdx >= 0 ? row[modelIdx].trim() : "") || "default";
    const attrs: Record<string, string | number | null> = {};
    for (const i of attrIdx) attrs[fold(headers[i]) || `col_${i}`] = row[i] || null;

    const forecast = forecastIdx >= 0 ? parseNumber(row[forecastIdx], numberLocale) : null;
    const actual = actualIdx >= 0 ? parseNumber(row[actualIdx], numberLocale) : null;
    const lo = loIdx >= 0 ? parseNumber(row[loIdx], numberLocale) : null;
    const hi = hiIdx >= 0 ? parseNumber(row[hiIdx], numberLocale) : null;

    out.push({
      productId,
      productName,
      date: parsed.date,
      periodType: parsed.periodType,
      forecast,
      actual,
      model,
      lo,
      hi,
      attributes: attrs,
      sourceRow,
    });

    if (budgetIdx >= 0) {
      const b = parseNumber(row[budgetIdx], numberLocale);
      if (b != null) {
        out.push({
          productId,
          productName,
          date: parsed.date,
          periodType: parsed.periodType,
          forecast: b,
          actual,
          model: "budget",
          lo: null,
          hi: null,
          attributes: { ...attrs, actualShared: 1 },
          sourceRow,
        });
      }
    }
  });
  return out;
}

function meltWide(args: {
  headers: string[];
  folded: string[];
  body: string[][];
  periodCols: number[];
  idIdx: number;
  nameIdx: number;
  seriesIdx: number;
  roles: Role[];
  numberLocale: NumberLocale;
  diagnostics: Diagnostic[];
}): ForecastRow[] {
  const { headers, body, periodCols, idIdx, nameIdx, seriesIdx, roles, numberLocale, diagnostics } = args;
  const attrIdx = roles.map((r, i) => (r === "attr" ? i : -1)).filter((i) => i >= 0);
  const out: ForecastRow[] = [];
  const buckets = new Map<string, ForecastRow>();

  body.forEach((row, ri) => {
    const sourceRow = ri + 2;
    const productId = (idIdx >= 0 ? row[idIdx] : "").trim();
    if (!productId) {
      diagnostics.push({
        code: "DQ-R01",
        severity: "discard",
        message: "Falta el código de producto. La fila se descartó.",
        row: sourceRow,
      });
      return;
    }
    const productName = nameIdx >= 0 ? row[nameIdx].trim() || null : null;
    const seriesKind = seriesIdx >= 0 ? fold(row[seriesIdx]) : "";
    const attrs: Record<string, string | number | null> = {};
    for (const i of attrIdx) attrs[fold(headers[i]) || `col_${i}`] = row[i] || null;

    for (const ci of periodCols) {
      const header = headers[ci];
      const leaf = header.includes("::") ? header.split("::").pop()!.trim() : header;
      const parsed = parseDate(leaf) ?? parseDate(header);
      if (!parsed) continue;
      let model = "default";
      let role: "forecast" | "actual" = "forecast";
      if (header.includes("::")) {
        const left = header.split("::")[0].trim();
        model = left.replace(/^real\s+/i, "").trim() || model;
        if (/^real/i.test(left) || /^actual/i.test(left)) role = "actual";
      }
      if (/^real\b/i.test(header) || /^actual\b/i.test(header)) role = "actual";
      const mA = header.match(/^(Modelo\s+[^:]+|modelo\s+[^:]+)/i);
      if (mA && header.includes("::")) model = header.split("::")[0].trim();

      if (seriesKind === "actual" || seriesKind === "real" || seriesKind === "ventas") role = "actual";
      if (seriesKind === "forecast" || seriesKind === "pronostico") role = "forecast";

      const value = parseNumber(row[ci], voteLocale([row[ci]]) === "en" ? "en" : numberLocale);
      const key = `${productId}|${parsed.date}|${model}`;
      const prev = buckets.get(key) ?? {
        productId,
        productName,
        date: parsed.date,
        periodType: parsed.periodType,
        forecast: null,
        actual: null,
        model,
        lo: null,
        hi: null,
        attributes: { ...attrs, actualShared: 1 },
        sourceRow,
      };
      if (role === "actual") prev.actual = value;
      else prev.forecast = value;
      buckets.set(key, prev);
    }
  });

  for (const row of buckets.values()) out.push(row);
  return out;
}
