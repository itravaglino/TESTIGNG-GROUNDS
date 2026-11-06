import type { PortfolioReport } from './types';

export function auditCsv(report: PortfolioReport): string {
  const headers = [
    'producto',
    'nombre',
    'categoria',
    'decision',
    'confianza',
    'patron',
    'grano',
    'wape',
    'wape_corregido',
    'sesgo_volumen',
    'mase',
    'fva_naive',
    'correlacion',
    'periodos',
    'comparables',
    'modelo_sugerido',
    'motivos',
    'mejoras',
  ];
  const rows = report.products.map((product) => [
    product.productId,
    product.productName,
    product.category,
    product.decision,
    product.confidence,
    product.pattern,
    product.grain,
    ratio(product.raw.wape),
    ratio(product.raw.wapeCorrected),
    ratio(product.raw.biasPct),
    ratio(product.raw.mase),
    ratio(product.raw.fvaNaive),
    ratio(product.raw.correlation),
    String(product.raw.periods),
    String(product.raw.overlap),
    product.models.find((model) => model.role === 'usar_ahora')?.name ?? '',
    product.reasons.join(' | '),
    product.improvements.join(' | '),
  ]);
  return toCsv(headers, rows);
}

export function correctedCsv(report: PortfolioReport): string {
  const headers = ['producto', 'nombre', 'categoria', 'fecha', 'real', 'pronostico_original', 'pronostico_publicado', 'origen', 'decision'];
  const rows = report.products.flatMap((product) => product.series.map((row) => [
    product.productId,
    product.productName,
    product.category,
    row.date,
    ratio(row.actual),
    ratio(row.forecast),
    ratio(row.corrected),
    row.origin,
    product.decision,
  ]));
  return toCsv(headers, rows);
}

function toCsv(headers: string[], rows: string[][]): string {
  return `\uFEFF${[headers, ...rows].map((row) => row.map(escapeCell).join(';')).join('\n')}`;
}

function escapeCell(value: string): string {
  if (/[;"\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

function ratio(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '';
  return value.toFixed(4).replace('.', ',');
}
