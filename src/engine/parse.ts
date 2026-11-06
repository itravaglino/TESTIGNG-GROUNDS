import type { CanonicalRow, ColumnMapping, ParseDiagnostic } from "./types";

const PRODUCT_ID = [
  "producto", "product", "productid", "product_id", "sku", "item", "articulo",
  "codigo", "idproducto", "material", "serieid", "serie_id", "id",
];
const PRODUCT_NAME = ["nombre", "descripcion", "productname", "product_name", "item_name", "name"];
const DATE = ["fecha", "date", "period", "periodo", "semana", "month", "mes", "week", "ds", "time"];
const FORECAST = [
  "forecast", "prediccion", "prediccion", "pronostico", "pronóstico", "yhat",
  "fcst", "qty_fcst", "demandaprevista", "forecast_qty", "pred", "forecastqty",
];
const ACTUAL = ["actual", "real", "y", "qty", "demand", "demanda", "ventas", "venta", "observacion", "actual_qty"];
const MODEL = ["modelo", "model", "algorithm", "algo"];
const LOCATION = ["ubicacion", "ubicacion", "location", "warehouse", "deposito", "store", "tienda", "site"];
const CHANNEL = ["canal", "channel", "customer", "cliente"];
const HORIZON = ["horizonte", "horizon", "lag", "h", "step"];
const LOWER = ["lower", "lo", "pi_lo", "p10", "q10", "min", "limite_inferior", "limiteinferior"];
const UPPER = ["upper", "hi", "pi_hi", "p90", "q90", "max", "limite_superior", "limitesuperior"];

function fold(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function pick(header: string[], aliases: string[]): string | null {
  const folded = header.map(fold);
  const wanted = aliases.map(fold);
  for (let i = 0; i < folded.length; i++) {
    if (wanted.includes(folded[i])) return header[i];
  }
  return null;
}

function detectDelimiter(text: string): string {
  const first = text.split(/\r?\n/).find((l) => l.trim() && !l.startsWith("sep=")) ?? "";
  const candidates = [";", ",", "\t", "|"];
  let best = ",";
  let bestCount = -1;
  for (const d of candidates) {
    const count = first.split(d).length;
    if (count > bestCount) {
      best = d;
      bestCount = count;
    }
  }
  const hint = text.match(/^sep=(.)/i);
  return hint ? hint[1] : best;
}

function splitLine(line: string, delimiter: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else quoted = !quoted;
    } else if (ch === delimiter && !quoted) {
      out.push(cur.trim());
      cur = "";
    } else cur += ch;
  }
  out.push(cur.trim());
  return out;
}

export function parseNumber(raw: string): number | null {
  const s = raw.trim();
  if (!s || s === "-" || s.toLowerCase() === "na" || s.toLowerCase() === "null") return null;
  let t = s.replace(/\s/g, "");
  const neg = /^\(.*\)$/.test(t);
  if (neg) t = t.slice(1, -1);
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(t)) t = t.replace(/\./g, "").replace(",", ".");
  else if (/^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(t)) t = t.replace(/,/g, "");
  else if (/^-?\d+,\d+$/.test(t)) t = t.replace(",", ".");
  const n = Number(t);
  if (!Number.isFinite(n)) return null;
  return neg ? -n : n;
}

function excelSerial(n: number): Date | null {
  if (n < 20000 || n > 80000) return null;
  const utc = Date.UTC(1899, 11, 30) + Math.round(n) * 86400000;
  return new Date(utc);
}

export function parseDate(raw: string): { iso: string; ts: number } | null {
  const s = raw.trim();
  if (!s) return null;
  const serial = parseNumber(s);
  if (serial !== null && /^\d{5}(\.\d+)?$/.test(s)) {
    const d = excelSerial(serial);
    if (d) return isoNoon(d);
  }
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return isoNoon(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])));
  m = s.match(/^(\d{4})-(\d{2})$/);
  if (m) return isoNoon(new Date(Date.UTC(+m[1], +m[2] - 1, 1)));
  m = s.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/);
  if (m) {
    const a = +m[1];
    const b = +m[2];
    const y = +m[3];
    const dmy = a > 12 || b <= 12;
    const day = dmy ? a : b;
    const month = dmy ? b : a;
    if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
      return isoNoon(new Date(Date.UTC(y, month - 1, day)));
    }
  }
  m = s.match(/^(\d{4})W(\d{2})$/i);
  if (m) {
    const d = weekDate(+m[1], +m[2]);
    return isoNoon(d);
  }
  const t = Date.parse(s);
  if (Number.isFinite(t)) return isoNoon(new Date(t));
  return null;
}

function weekDate(year: number, week: number): Date {
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const day = jan4.getUTCDay() || 7;
  const monday = new Date(jan4);
  monday.setUTCDate(jan4.getUTCDate() - day + 1 + (week - 1) * 7);
  return monday;
}

function isoNoon(d: Date): { iso: string; ts: number } | null {
  if (!Number.isFinite(d.getTime())) return null;
  const iso = d.toISOString().slice(0, 10);
  return { iso, ts: Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 12) };
}

export function parseForecastCsv(text: string): { rows: CanonicalRow[]; parse: ParseDiagnostic } {
  const cleaned = text.replace(/^\uFEFF/, "");
  const delimiter = detectDelimiter(cleaned);
  const lines = cleaned.split(/\r?\n/);
  const headerLine = lines.find((l) => l.trim() && !/^sep=/i.test(l.trim())) ?? "";
  const header = splitLine(headerLine, delimiter).filter((h) => h.length > 0);
  const mapping: ColumnMapping = {
    productId: pick(header, PRODUCT_ID) ?? "",
    productName: pick(header, PRODUCT_NAME),
    date: pick(header, DATE) ?? "",
    forecast: pick(header, FORECAST) ?? "",
    actual: pick(header, ACTUAL),
    model: pick(header, MODEL),
    location: pick(header, LOCATION),
    channel: pick(header, CHANNEL),
    horizon: pick(header, HORIZON),
    lower: pick(header, LOWER),
    upper: pick(header, UPPER),
  };
  const warnings: string[] = [];
  if (!mapping.productId || !mapping.date || !mapping.forecast) {
    throw new Error(
      "Faltan columnas obligatorias. Se necesita producto (o sku), fecha y forecast/pronóstico.",
    );
  }
  const headerIndex = lines.indexOf(headerLine);
  const rows: CanonicalRow[] = [];
  let skippedEmpty = 0;
  for (let i = headerIndex + 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) {
      skippedEmpty++;
      continue;
    }
    const cells = splitLine(line, delimiter);
    const values: Record<string, string> = {};
    header.forEach((h, idx) => {
      values[h] = cells[idx] ?? "";
    });
    const productId = (values[mapping.productId] ?? "").trim();
    const dateRaw = values[mapping.date] ?? "";
    const forecastRaw = values[mapping.forecast] ?? "";
    if (!productId && !dateRaw && !forecastRaw) {
      skippedEmpty++;
      continue;
    }
    const dated = parseDate(dateRaw);
    const forecast = parseNumber(forecastRaw);
    const extra: Record<string, string> = {};
    for (const [k, v] of Object.entries(values)) extra[k] = v;
    const actual = mapping.actual ? parseNumber(values[mapping.actual] ?? "") : null;
    rows.push({
      line: i + 1,
      productId: productId || "SIN-ID",
      productName:
        (mapping.productName ? values[mapping.productName] : "")?.trim() || productId || "SIN-ID",
      date: dated?.iso ?? dateRaw,
      timestamp: dated?.ts ?? NaN,
      forecast: forecast ?? NaN,
      actual,
      model: mapping.model ? values[mapping.model]?.trim() || null : null,
      location: mapping.location ? values[mapping.location]?.trim() || null : null,
      channel: mapping.channel ? values[mapping.channel]?.trim() || null : null,
      horizon: mapping.horizon ? parseNumber(values[mapping.horizon] ?? "") : null,
      lower: mapping.lower ? parseNumber(values[mapping.lower] ?? "") : null,
      upper: mapping.upper ? parseNumber(values[mapping.upper] ?? "") : null,
      extra,
    });
    if (!dated) warnings.push(`Línea ${i + 1}: fecha ilegible (${dateRaw})`);
    if (forecast === null) warnings.push(`Línea ${i + 1}: forecast ilegible (${forecastRaw})`);
  }
  return {
    rows,
    parse: { mapping, delimiter, header, skippedEmpty, warnings },
  };
}
