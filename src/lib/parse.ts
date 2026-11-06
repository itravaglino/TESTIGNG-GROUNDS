import type { CanonicalPoint, ColumnKey, ColumnMapping, ParseResult, ParseWarning, ProductInput } from './types';

const ALIASES: Record<ColumnKey, string[]> = {
  productId: ['producto', 'sku', 'item', 'codigo', 'cod', 'product', 'product_id', 'productid', 'articulo', 'material', 'id_producto', 'id'],
  productName: ['nombre', 'descripcion', 'description', 'product_name', 'desc', 'detalle'],
  category: ['categoria', 'category', 'familia', 'linea', 'rubro', 'segmento'],
  date: ['fecha', 'date', 'periodo', 'semana', 'mes', 'period', 'fecha_pronostico', 'calmonth', 'anio_mes', 'año_mes'],
  forecast: ['pronostico', 'forecast', 'fcst', 'prediccion', 'yhat', 'forecast_qty', 'cantidad_pronostico', 'unidades_pronostico', 'qty_fcst'],
  actual: ['real', 'actual', 'venta', 'ventas', 'demanda', 'demand', 'qty_real', 'unidades', 'unidades_reales', 'sell_out', 'historia'],
  lower: ['lower', 'piso', 'limite_inferior', 'intervalo_inf', 'forecast_lower', 'minimo'],
  upper: ['upper', 'techo', 'limite_superior', 'intervalo_sup', 'forecast_upper', 'maximo'],
};

export function parseCsv(text: string): ParseResult {
  const cleaned = text.replace(/^\uFEFF/, '');
  const delimiter = detectDelimiter(cleaned);
  const matrix = cleaned
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0)
    .map((line) => splitDelimited(line, delimiter));
  return parseMatrix(matrix, null);
}

export async function parseXlsx(data: ArrayBuffer): Promise<ParseResult> {
  const XLSX = await import('xlsx');
  const book = XLSX.read(data, { type: 'array', cellDates: true });
  const sheetName = book.SheetNames[0] ?? null;
  if (!sheetName) {
    return { products: [], mapping: {}, headers: [], warnings: [{ level: 'alerta', message: 'El Excel no tiene hojas.' }], droppedRows: 0, sheetName: null };
  }
  const sheet = book.Sheets[sheetName];
  const matrix = XLSX.utils.sheet_to_json(sheet, { header: 1, raw: true, defval: '', blankrows: false }) as unknown[][];
  return parseMatrix(matrix.map((row) => row.map(cellToString)), sheetName);
}

export function parseMatrix(matrix: string[][], sheetName: string | null): ParseResult {
  const warnings: ParseWarning[] = [];
  if (!matrix.length) {
    return { products: [], mapping: {}, headers: [], warnings: [{ level: 'alerta', message: 'El archivo está vacío.' }], droppedRows: 0, sheetName };
  }
  const headerIndex = matrix.findIndex((row) => row.filter((cell) => normalizeHeader(cell)).length >= 2);
  if (headerIndex < 0) {
    return { products: [], mapping: {}, headers: [], warnings: [{ level: 'alerta', message: 'No encontré una fila de encabezados.' }], droppedRows: 0, sheetName };
  }
  const headers = matrix[headerIndex].map((cell) => cell.trim());
  const mapping = mapHeaders(headers);
  if (mapping.productId == null) warnings.push({ level: 'alerta', message: 'Falta la columna de producto (sku, producto, código o material).' });
  if (mapping.date == null) warnings.push({ level: 'alerta', message: 'Falta la columna de fecha o período.' });
  if (mapping.forecast == null && mapping.actual == null) {
    warnings.push({ level: 'alerta', message: 'Hace falta una columna de pronóstico o de venta real.' });
  }
  if (mapping.forecast == null) warnings.push({ level: 'info', message: 'No hay pronóstico: se puede recomendar modelo, pero no auditar un forecast.' });
  if (mapping.actual == null) warnings.push({ level: 'info', message: 'No hay venta real: la auditoría es estructural y la confianza queda baja.' });

  const grouped = new Map<string, { name: string; category: string; rows: Map<string, CanonicalPoint>; dup: number }>();
  let droppedRows = 0;
  let dmyAssumed = false;
  for (const row of matrix.slice(headerIndex + 1)) {
    if (row.every((cell) => !cell.trim())) continue;
    if (mapping.productId == null || mapping.date == null) {
      droppedRows += 1;
      continue;
    }
    const productId = row[mapping.productId]?.trim() ?? '';
    const date = parseDate(row[mapping.date] ?? '', () => {
      dmyAssumed = true;
    });
    if (!productId || !date) {
      droppedRows += 1;
      continue;
    }
    const point: CanonicalPoint = {
      date,
      forecast: mapping.forecast == null ? null : parseNumber(row[mapping.forecast] ?? ''),
      actual: mapping.actual == null ? null : parseNumber(row[mapping.actual] ?? ''),
      lower: mapping.lower == null ? null : parseNumber(row[mapping.lower] ?? ''),
      upper: mapping.upper == null ? null : parseNumber(row[mapping.upper] ?? ''),
    };
    if (point.forecast == null && point.actual == null) {
      droppedRows += 1;
      continue;
    }
    const bucket = grouped.get(productId) ?? {
      name: mapping.productName == null ? productId : row[mapping.productName]?.trim() || productId,
      category: mapping.category == null ? 'Sin categoría' : row[mapping.category]?.trim() || 'Sin categoría',
      rows: new Map<string, CanonicalPoint>(),
      dup: 0,
    };
    const previous = bucket.rows.get(date);
    if (previous) {
      bucket.dup += 1;
      bucket.rows.set(date, averagePoint(previous, point));
    } else {
      bucket.rows.set(date, point);
    }
    grouped.set(productId, bucket);
  }
  if (dmyAssumed) warnings.push({ level: 'info', message: 'Las fechas con día y mes ambiguos se leyeron como día/mes/año.' });
  const products: ProductInput[] = [...grouped.entries()].map(([productId, bucket]) => ({
    productId,
    productName: bucket.name,
    category: bucket.category,
    duplicateDates: bucket.dup,
    points: [...bucket.rows.values()].sort((a, b) => a.date.localeCompare(b.date)),
  }));
  const duplicateProducts = [...grouped.values()].filter((bucket) => bucket.dup > 0).length;
  if (duplicateProducts) {
    warnings.push({
      level: 'alerta',
      message: `${duplicateProducts} producto(s) tienen fechas repetidas. Se promediaron los valores en conflicto.`,
    });
  }
  products.sort((a, b) => a.productName.localeCompare(b.productName, 'es'));
  return { products, mapping, headers, warnings, droppedRows, sheetName };
}

export function mapHeaders(headers: string[]): ColumnMapping {
  const mapping: ColumnMapping = {};
  const used = new Set<number>();
  headers.forEach((header, index) => {
    const norm = normalizeHeader(header);
    const best = bestColumn(norm);
    if (best && mapping[best] == null && !used.has(index)) {
      mapping[best] = index;
      used.add(index);
    }
  });
  return mapping;
}

function bestColumn(norm: string): ColumnKey | null {
  let bestKey: ColumnKey | null = null;
  let bestLength = 0;
  for (const key of Object.keys(ALIASES) as ColumnKey[]) {
    for (const alias of ALIASES[key]) {
      const hit = norm === alias || norm.startsWith(`${alias}_`) || norm.endsWith(`_${alias}`);
      if (hit && alias.length > bestLength) {
        bestKey = key;
        bestLength = alias.length;
      }
    }
  }
  return bestKey;
}

function averagePoint(a: CanonicalPoint, b: CanonicalPoint): CanonicalPoint {
  return {
    date: a.date,
    forecast: meanNullable(a.forecast, b.forecast),
    actual: meanNullable(a.actual, b.actual),
    lower: meanNullable(a.lower, b.lower),
    upper: meanNullable(a.upper, b.upper),
  };
}

function meanNullable(a: number | null, b: number | null): number | null {
  if (a == null) return b;
  if (b == null) return a;
  return (a + b) / 2;
}

export function normalizeHeader(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '');
}

export function parseNumber(raw: string): number | null {
  const original = raw.trim();
  if (!original || original === '-' || /^(na|n\/a|null|none)$/i.test(original)) return null;
  const percent = original.includes('%');
  let text = original.replace(/\s/g, '').replace('%', '');
  if (text.includes(',') && text.includes('.')) {
    text = text.lastIndexOf(',') > text.lastIndexOf('.') ? text.replace(/\./g, '').replace(',', '.') : text.replace(/,/g, '');
  } else if (text.includes(',')) {
    const parts = text.split(',');
    text = parts[parts.length - 1].length === 3 && parts.length > 1 ? text.replace(/,/g, '') : text.replace(',', '.');
  }
  const value = Number(text);
  if (!Number.isFinite(value)) return null;
  return percent ? value / 100 : value;
}

export function parseDate(raw: string, onAmbiguous?: () => void): string | null {
  const value = raw.trim();
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10);
  if (/^\d{5}(\.\d+)?$/.test(value)) {
    const serial = Number(value);
    const utc = new Date(Date.UTC(1899, 11, 30) + Math.round(serial) * 86_400_000);
    return utc.toISOString().slice(0, 10);
  }
  const monthMatch = value.match(/^(\d{4})[/-](\d{1,2})$/);
  if (monthMatch) return `${monthMatch[1]}-${monthMatch[2].padStart(2, '0')}-01`;
  const parts = value.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$/);
  if (parts) {
    let day = Number(parts[1]);
    let month = Number(parts[2]);
    let year = Number(parts[3]);
    if (year < 100) year += year > 50 ? 1900 : 2000;
    if (day > 12 && month <= 12) {
      // already DMY
    } else if (month > 12 && day <= 12) {
      const swap = day;
      day = month;
      month = swap;
    } else if (day <= 12 && month <= 12) {
      onAmbiguous?.();
    }
    if (month < 1 || month > 12 || day < 1 || day > 31) return null;
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }
  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime()) && /[a-z]/i.test(value)) return parsed.toISOString().slice(0, 10);
  return null;
}

function detectDelimiter(text: string): string {
  const sample = text.split(/\r?\n/).slice(0, 5).join('\n');
  const scores = [',', ';', '\t'].map((delimiter) => ({
    delimiter,
    score: sample.split(delimiter).length,
  }));
  scores.sort((a, b) => b.score - a.score);
  return scores[0].score > 1 ? scores[0].delimiter : ',';
}

function splitDelimited(line: string, delimiter: string): string[] {
  const cells: string[] = [];
  let current = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else quoted = !quoted;
    } else if (char === delimiter && !quoted) {
      cells.push(current.trim());
      current = '';
    } else current += char;
  }
  cells.push(current.trim());
  return cells;
}

function cellToString(value: unknown): string {
  if (value == null) return '';
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return String(value);
}
