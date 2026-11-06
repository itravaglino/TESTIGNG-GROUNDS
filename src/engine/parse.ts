import type {
  ColumnRole,
  ForecastPoint,
  ForecastRow,
  FormatReport,
  ParseError,
  ParseResult,
} from "./types";

const ALIASES: Record<ColumnRole, string[]> = {
  product_id: [
    "product_id", "sku", "item", "producto", "codigo", "código", "product",
    "id_producto", "idproducto", "material", "articulo", "artículo", "item_id",
    "cod_prod", "plu",
  ],
  product_name: [
    "product_name", "nombre", "descripcion", "descripción", "description",
    "item_name", "desc", "producto_nombre",
  ],
  date: [
    "date", "fecha", "week", "period", "ds", "periodo", "semana", "mes",
    "month", "fecha_periodo", "anio_semana", "año_semana",
  ],
  forecast: [
    "forecast", "forecast_qty", "pred", "yhat", "demanda_pronosticada",
    "qty_fcst", "pronostico", "pronóstico", "fcst", "forecast_units",
    "qty_forecast", "unidades_pronostico", "forecast_quantity",
  ],
  actual: [
    "actual", "y", "actual_qty", "demanda_real", "sales", "ventas", "real",
    "qty_actual", "unidades", "cantidad_real", "sold",
  ],
  location: [
    "location", "loc", "store", "tienda", "warehouse", "deposito", "depósito",
    "centro", "site", "cd", "almacen", "almacén",
  ],
  model: ["model", "modelo", "model_name", "algorithm", "algoritmo"],
  price: ["price", "precio", "unit_price", "pvp", "costo"],
  lower: ["yhat_lower", "lo", "p10", "interval_low", "lower", "inf", "piso"],
  upper: ["yhat_upper", "hi", "p90", "interval_high", "upper", "sup", "techo"],
  ignore: [],
};

function normHeader(h: string): string {
  return h
    .replace(/^\uFEFF/, "")
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function detectDelimiter(headerLine: string): string {
  const counts = [
    { d: ",", n: (headerLine.match(/,/g) ?? []).length },
    { d: ";", n: (headerLine.match(/;/g) ?? []).length },
    { d: "\t", n: (headerLine.match(/\t/g) ?? []).length },
  ];
  counts.sort((a, b) => b.n - a.n);
  return counts[0].n > 0 ? counts[0].d : ",";
}

function parseCsvLine(line: string, delimiter: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === delimiter) {
      out.push(cur.trim());
      cur = "";
    } else {
      cur += ch;
    }
  }
  out.push(cur.trim());
  return out;
}

function mapRole(header: string, taken: Set<ColumnRole>): ColumnRole {
  const n = normHeader(header);
  const roles = Object.keys(ALIASES) as ColumnRole[];
  for (const role of roles) {
    if (role === "ignore" || taken.has(role)) continue;
    if (ALIASES[role].includes(n)) return role;
  }
  return "ignore";
}

export function parseNumber(raw: string): number | undefined {
  const t = raw.trim();
  if (t === "" || /^(na|n\/a|null|nan|-)$/i.test(t)) return undefined;
  if (/^-?\d{1,3}(\.\d{3})+,\d+$/.test(t)) {
    const v = Number(t.replace(/\./g, "").replace(",", "."));
    return Number.isFinite(v) ? v : undefined;
  }
  if (t.includes(",") && !t.includes(".")) {
    const v = Number(t.replace(/\s/g, "").replace(",", "."));
    return Number.isFinite(v) ? v : undefined;
  }
  const v = Number(t.replace(/,/g, ""));
  return Number.isFinite(v) ? v : undefined;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

export function toIsoDate(d: Date): string {
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

export function parseDate(raw: string): Date | undefined {
  const t = raw.trim();
  if (!t) return undefined;

  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (iso) {
    const d = new Date(Date.UTC(+iso[1], +iso[2] - 1, +iso[3]));
    return Number.isNaN(d.getTime()) ? undefined : d;
  }

  const ymw = /^(\d{4})-W?(\d{1,2})$/i.exec(t);
  if (ymw && +ymw[2] <= 53) {
    const year = +ymw[1];
    const week = +ymw[2];
    if (t.toUpperCase().includes("W") || week > 12) {
      return weekToDate(year, week);
    }
    return new Date(Date.UTC(year, week - 1, 1));
  }

  const yyyyww = /^(\d{4})(\d{2})$/.exec(t);
  if (yyyyww && +yyyyww[2] >= 1 && +yyyyww[2] <= 53) {
    return weekToDate(+yyyyww[1], +yyyyww[2]);
  }

  const dmy = /^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/.exec(t);
  if (dmy) {
    const a = +dmy[1];
    const b = +dmy[2];
    const y = +dmy[3];
    const dayFirst = a > 12 || b <= 12;
    const day = dayFirst ? a : b;
    const month = dayFirst ? b : a;
    if (month < 1 || month > 12 || day < 1 || day > 31) return undefined;
    return new Date(Date.UTC(y, month - 1, day));
  }

  const mmm = Date.parse(t);
  if (!Number.isNaN(mmm)) {
    const d = new Date(mmm);
    return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  }
  return undefined;
}

function weekToDate(year: number, week: number): Date {
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const day = jan4.getUTCDay() || 7;
  const monday = new Date(jan4);
  monday.setUTCDate(jan4.getUTCDate() - day + 1 + (week - 1) * 7);
  return monday;
}

export function parseForecastCsv(text: string): ParseResult {
  const cleaned = text.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = cleaned.split("\n").filter((l, i, arr) => !(l.trim() === "" && i === arr.length - 1));
  const errors: ParseError[] = [];
  if (lines.length === 0 || lines.every((l) => l.trim() === "")) {
    return {
      rows: [],
      report: {
        delimiter: ",",
        headers: [],
        mapping: {},
        unmappedHeaders: [],
        rowCount: 0,
        acceptedRows: 0,
        errors: [{ row: 0, message: "Archivo vacío" }],
        hasActuals: false,
      },
    };
  }

  const delimiter = detectDelimiter(lines[0]);
  const headers = parseCsvLine(lines[0], delimiter);
  const taken = new Set<ColumnRole>();
  const mapping: Record<string, ColumnRole> = {};
  for (const h of headers) {
    const role = mapRole(h, taken);
    mapping[h] = role;
    if (role !== "ignore") taken.add(role);
  }
  const unmappedHeaders = headers.filter((h) => mapping[h] === "ignore");

  if (!taken.has("product_id") || !taken.has("date") || !taken.has("forecast")) {
    errors.push({
      row: 1,
      message:
        "Faltan columnas obligatorias. Se necesita producto (sku/producto), fecha y pronóstico.",
    });
  }

  const roleIndex = (role: ColumnRole): number =>
    headers.findIndex((h) => mapping[h] === role);

  const idx = {
    productId: roleIndex("product_id"),
    name: roleIndex("product_name"),
    date: roleIndex("date"),
    forecast: roleIndex("forecast"),
    actual: roleIndex("actual"),
    location: roleIndex("location"),
    model: roleIndex("model"),
    price: roleIndex("price"),
    lower: roleIndex("lower"),
    upper: roleIndex("upper"),
  };

  const rows: ForecastRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trim() === "") continue;
    const cols = parseCsvLine(lines[i], delimiter);
    const cell = (j: number) => (j >= 0 ? (cols[j] ?? "") : "");
    const productId = cell(idx.productId).trim();
    const date = parseDate(cell(idx.date));
    const forecast = parseNumber(cell(idx.forecast));
    if (!productId || !date || forecast === undefined) {
      errors.push({
        row: i + 1,
        message: `Fila inválida (producto=${productId || "?"}, fecha=${cell(idx.date)}, pronóstico=${cell(idx.forecast)})`,
      });
      continue;
    }
    const actual = idx.actual >= 0 ? parseNumber(cell(idx.actual)) : undefined;
    const lower = idx.lower >= 0 ? parseNumber(cell(idx.lower)) : undefined;
    const upper = idx.upper >= 0 ? parseNumber(cell(idx.upper)) : undefined;
    const price = idx.price >= 0 ? parseNumber(cell(idx.price)) : undefined;
    const point: ForecastPoint = {
      date,
      isoDate: toIsoDate(date),
      forecast,
      actual,
      lower,
      upper,
      price,
      model: cell(idx.model) || undefined,
      raw: Object.fromEntries(headers.map((h, j) => [h, cols[j] ?? ""])),
    };
    rows.push({
      productId,
      productName: cell(idx.name) || productId,
      location: cell(idx.location) || "GLOBAL",
      point,
    });
  }

  const report: FormatReport = {
    delimiter: delimiter === "\t" ? "tab" : delimiter === "," ? "coma" : delimiter === ";" ? "punto y coma" : delimiter,
    headers,
    mapping,
    unmappedHeaders,
    rowCount: Math.max(0, lines.length - 1),
    acceptedRows: rows.length,
    errors: errors.slice(0, 80),
    hasActuals: rows.some((r) => r.point.actual !== undefined),
  };
  return { rows, report };
}
