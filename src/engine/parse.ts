import type { ColumnMap, ColumnRole, ParseIssue, ParseResult, ParsedRow } from "./types";

const ALIASES: Record<ColumnRole, string[]> = {
  product: [
    "producto", "product", "sku", "item", "articulo", "artículo", "codigo", "código",
    "id_producto", "product_id", "item_id", "material", "ean", "plu",
  ],
  date: [
    "fecha", "date", "periodo", "período", "period", "semana", "week", "mes", "month",
    "anio", "año", "yearmonth", "ds", "time",
  ],
  forecast: [
    "forecast", "pronostico", "pronóstico", "prediccion", "predicción", "fcst",
    "qty_fcst", "qty_forecast", "demanda_pronosticada", "unidades_pronostico",
    "yhat", "pred", "previsto",
  ],
  actual: [
    "real", "actual", "venta", "ventas", "demanda", "qty", "quantity", "unidades",
    "sales", "y", "obs", "observado", "consumo",
  ],
  model: ["modelo", "model", "algoritmo", "engine", "metodo", "método"],
  channel: ["canal", "channel", "tienda", "store", "cliente", "customer"],
  warehouse: ["deposito", "depósito", "almacen", "almacén", "warehouse", "cd", "bodega"],
  lower: ["lower", "lo", "p10", "inf", "intervalo_inf", "yhat_lower"],
  upper: ["upper", "hi", "p90", "sup", "intervalo_sup", "yhat_upper"],
  unit: ["unidad", "unit", "uom", "um"],
};

function norm(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

export function detectDelimiter(text: string): string {
  const sample = text.split(/\r?\n/).slice(0, 8).join("\n");
  const candidates = [",", ";", "\t", "|"];
  let best = ",";
  let bestScore = -1;
  for (const d of candidates) {
    const lines = sample.split(/\r?\n/).filter(Boolean);
    if (lines.length === 0) continue;
    const counts = lines.map((l) => splitCsvLine(l, d).length);
    const first = counts[0] ?? 0;
    if (first < 2) continue;
    const consistent = counts.every((c) => c === first);
    const score = first * (consistent ? 10 : 1);
    if (score > bestScore) {
      bestScore = score;
      best = d;
    }
  }
  return best;
}

export function splitCsvLine(line: string, delimiter: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === delimiter && !inQuotes) {
      out.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

export function parseNumber(raw: string, decimalComma: boolean): number | null {
  const t = raw.trim();
  if (t === "" || t === "-" || /^na$|^n\/a$|^null$|^none$|^nan$/i.test(t)) return null;
  let s = t.replace(/\s/g, "");
  if (decimalComma) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (s.includes(",") && !s.includes(".")) {
    s = s.replace(",", ".");
  } else {
    s = s.replace(/,/g, "");
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_YM = /^(\d{4})-(\d{2})$/;
const DMY = /^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$/;
const YMD_SLASH = /^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/;
const YM = /^(\d{4})(\d{2})$/;
const WEEK = /^(\d{4})-?w(\d{1,2})$/i;

export function parseDate(raw: string): Date | null {
  const t = raw.trim();
  if (!t) return null;
  let m = t.match(ISO);
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return Number.isNaN(d.getTime()) ? null : d;
  }
  m = t.match(ISO_YM);
  if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, 1));
  m = t.match(YMD_SLASH);
  if (m) return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  m = t.match(WEEK);
  if (m) {
    const year = +m[1];
    const week = +m[2];
    const d = new Date(Date.UTC(year, 0, 1 + (week - 1) * 7));
    return d;
  }
  m = t.match(YM);
  if (m && +m[2] >= 1 && +m[2] <= 12) return new Date(Date.UTC(+m[1], +m[2] - 1, 1));
  m = t.match(DMY);
  if (m) {
    const a = +m[1];
    const b = +m[2];
    let y = +m[3];
    if (y < 100) y += 2000;
    const dayFirst = a > 12 || b <= 12;
    const day = dayFirst ? a : b;
    const month = dayFirst ? b : a;
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    return new Date(Date.UTC(y, month - 1, day));
  }
  const n = Number(t);
  if (Number.isFinite(n) && n > 20000 && n < 80000) {
    const excel = new Date(Date.UTC(1899, 11, 30 + n));
    return excel;
  }
  const native = new Date(t);
  return Number.isNaN(native.getTime()) ? null : native;
}

function isDateHeader(h: string): boolean {
  return parseDate(h) !== null;
}

function mapHeaders(headers: string[]): ColumnMap {
  const map: ColumnMap = {};
  const used = new Set<string>();
  const roles = Object.keys(ALIASES) as ColumnRole[];
  for (const header of headers) {
    const n = norm(header);
    for (const role of roles) {
      if (map[role]) continue;
      if (ALIASES[role].some((a) => n === a || n.endsWith(`_${a}`) || n.startsWith(`${a}_`))) {
        map[role] = header;
        used.add(header);
        break;
      }
    }
  }
  return map;
}

function looksWide(headers: string[]): boolean {
  const dateCols = headers.filter(isDateHeader);
  return dateCols.length >= 3 && dateCols.length >= headers.length - 4;
}

function detectDecimalComma(lines: string[][], forecastIdx: number, delimiter: string): boolean {
  if (delimiter === ";") {
    let commas = 0;
    let dots = 0;
    for (const row of lines.slice(0, 40)) {
      const v = row[forecastIdx] ?? "";
      if (v.includes(",")) commas++;
      if (/\d\.\d/.test(v) && !v.includes(",")) dots++;
    }
    return commas >= dots;
  }
  return false;
}

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function parseForecastCsv(text: string): ParseResult {
  const issues: ParseIssue[] = [];
  const cleaned = text.replace(/^\uFEFF/, "").trim();
  if (!cleaned) {
    return {
      format: "long",
      delimiter: ",",
      decimalComma: false,
      map: {},
      headers: [],
      rows: [],
      skipped: 0,
      issues: [{ severity: "fatal", message: "El archivo está vacío." }],
    };
  }

  const delimiter = detectDelimiter(cleaned);
  const rawLines = cleaned.split(/\r?\n/).filter((l) => l.trim() !== "");
  const table = rawLines.map((l) => splitCsvLine(l, delimiter));
  const headers = table[0] ?? [];
  const body = table.slice(1);

  if (looksWide(headers)) {
    return parseWide(headers, body, delimiter, issues);
  }

  const map = mapHeaders(headers);
  if (!map.product) {
    issues.push({
      severity: "fatal",
      message: "No encontré columna de producto (producto, sku, item, código).",
    });
  }
  if (!map.date) {
    issues.push({
      severity: "fatal",
      message: "No encontré columna de fecha (fecha, periodo, semana, mes).",
    });
  }
  if (!map.forecast) {
    const numeric = headers.find((h) => {
      const n = norm(h);
      return !map.product && false || ["cantidad", "value", "valor", "qty_pred"].includes(n);
    });
    if (numeric) map.forecast = numeric;
    else {
      issues.push({
        severity: "fatal",
        message: "No encontré columna de pronóstico (forecast, pronostico, predicción, yhat).",
      });
    }
  }

  if (issues.some((i) => i.severity === "fatal")) {
    return {
      format: "long",
      delimiter,
      decimalComma: delimiter === ";",
      map,
      headers,
      rows: [],
      skipped: body.length,
      issues,
    };
  }

  const idx = (name?: string) => (name ? headers.indexOf(name) : -1);
  const fIdx = idx(map.forecast);
  const decimalComma = detectDecimalComma(body, fIdx, delimiter);

  const rows: ParsedRow[] = [];
  let skipped = 0;
  body.forEach((cols, i) => {
    const line = i + 2;
    const product = (cols[idx(map.product)] ?? "").trim();
    const dateRaw = cols[idx(map.date)] ?? "";
    const period = parseDate(dateRaw);
    if (!product || !period) {
      skipped++;
      issues.push({
        severity: "warn",
        message: `Fila ${line}: producto o fecha inválidos.`,
        line,
      });
      return;
    }
    const takeNum = (role: keyof ColumnMap) => {
      const j = idx(map[role]);
      return j >= 0 ? parseNumber(cols[j] ?? "", decimalComma) : null;
    };
    const takeStr = (role: keyof ColumnMap) => {
      const j = idx(map[role]);
      const v = j >= 0 ? (cols[j] ?? "").trim() : "";
      return v || null;
    };
    rows.push({
      product,
      date: ymd(period),
      period,
      forecast: takeNum("forecast"),
      actual: takeNum("actual"),
      model: takeStr("model"),
      channel: takeStr("channel"),
      warehouse: takeStr("warehouse"),
      lower: takeNum("lower"),
      upper: takeNum("upper"),
      unit: takeStr("unit"),
      sourceLine: line,
    });
  });

  if (rows.length === 0) {
    issues.push({ severity: "fatal", message: "No quedó ninguna fila válida después del parseo." });
  }

  return {
    format: "long",
    delimiter,
    decimalComma,
    map,
    headers,
    rows,
    skipped,
    issues,
  };
}

function parseWide(
  headers: string[],
  body: string[][],
  delimiter: string,
  issues: ParseIssue[],
): ParseResult {
  const dateIdx: { header: string; period: Date; j: number }[] = [];
  let productIdx = 0;
  const extra: { role: ColumnRole; j: number }[] = [];
  headers.forEach((h, j) => {
    const d = parseDate(h);
    if (d) dateIdx.push({ header: h, period: d, j });
    else {
      const n = norm(h);
      if (ALIASES.product.includes(n) || j === 0) productIdx = j;
      const roles = Object.keys(ALIASES) as ColumnRole[];
      for (const role of roles) {
        if (role === "product" || role === "date" || role === "forecast") continue;
        if (ALIASES[role].includes(n)) extra.push({ role, j });
      }
    }
  });

  const decimalComma = delimiter === ";";
  const rows: ParsedRow[] = [];
  body.forEach((cols, i) => {
    const product = (cols[productIdx] ?? "").trim();
    if (!product) return;
    const extras: Partial<ParsedRow> = {};
    for (const e of extra) {
      const v = cols[e.j] ?? "";
      if (e.role === "actual") extras.actual = parseNumber(v, decimalComma);
      if (e.role === "model") extras.model = v.trim() || null;
      if (e.role === "channel") extras.channel = v.trim() || null;
    }
    for (const d of dateIdx) {
      const forecast = parseNumber(cols[d.j] ?? "", decimalComma);
      rows.push({
        product,
        date: ymd(d.period),
        period: d.period,
        forecast,
        actual: extras.actual ?? null,
        model: extras.model ?? null,
        channel: extras.channel ?? null,
        warehouse: null,
        lower: null,
        upper: null,
        unit: null,
        sourceLine: i + 2,
      });
    }
  });

  if (rows.length === 0) {
    issues.push({ severity: "fatal", message: "Formato ancho detectado pero sin filas válidas." });
  } else {
    issues.push({
      severity: "info",
      message: `Detecté formato ancho (${dateIdx.length} fechas como columnas) y lo convertí a largo.`,
    });
  }

  return {
    format: "wide",
    delimiter,
    decimalComma,
    map: { product: headers[productIdx], date: "(columnas)", forecast: "(valores)" },
    headers,
    rows,
    skipped: 0,
    issues,
  };
}
