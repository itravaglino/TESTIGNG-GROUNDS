import { describe, expect, it } from 'vitest';
import * as XLSX from 'xlsx';
import { analyzePortfolio } from './analyze';
import { correctedCsv } from './export';
import { scoreForecast } from './metrics';
import { parseCsv, parseDate, parseNumber, parseXlsx } from './parse';
import { sampleCsv, sampleProducts } from './sample';
import { classifyDemand } from './classify';

describe('parser', () => {
  it('lee números y fechas de Argentina', () => {
    expect(parseNumber('1.234,50')).toBeCloseTo(1234.5);
    expect(parseNumber('15%')).toBeCloseTo(0.15);
    expect(parseNumber('')).toBeNull();
    expect(parseDate('15/03/2025')).toBe('2025-03-15');
    expect(parseDate('2025-03')).toBe('2025-03-01');
    expect(parseDate('45292')).toBe('2024-01-01');
  });

  it('lee un excel', async () => {
    const sheet = XLSX.utils.aoa_to_sheet([
      ['producto', 'fecha', 'pronostico', 'real'],
      ['A', '2025-01-01', 10, 8],
      ['A', '2025-02-01', 12, 11],
    ]);
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, sheet, 'Hoja1');
    const data = XLSX.write(book, { type: 'array', bookType: 'xlsx' }) as ArrayBuffer;
    const parsed = await parseXlsx(data);
    expect(parsed.products[0].productId).toBe('A');
    expect(parsed.products[0].points[0].forecast).toBe(10);
    expect(parsed.products[0].points[1].actual).toBe(11);
  });

  it('acepta punto y coma, encabezados en español y duplicados', () => {
    const parsed = parseCsv('SKU;Pronóstico;Fecha;Venta real\nA;10;01/01/2025;8\nA;14;01/01/2025;8\nA;12;01/02/2025;11\n');
    expect(parsed.products).toHaveLength(1);
    expect(parsed.products[0].duplicateDates).toBe(1);
    expect(parsed.products[0].points[0].forecast).toBe(12);
    expect(parsed.products[0].points[0].actual).toBe(8);
    expect(parsed.warnings.some((warning) => warning.message.includes('repetidas'))).toBe(true);
  });
});

describe('métricas', () => {
  it('calcula WAPE, sesgo y acierto', () => {
    const score = scoreForecast([11, 10, 12, 13], [10, 12, 11, 13]);
    expect(score.n).toBe(4);
    expect(score.mae).toBeCloseTo(1);
    expect(score.wape).toBeCloseTo(4 / 46);
    expect(score.bias).toBeCloseTo(0);
    expect(score.hit20).toBe(1);
  });

  it('clasifica intermitente y suave', () => {
    const smooth = Array.from({ length: 12 }, () => 10);
    expect(classifyDemand(smooth).pattern).toBe('suave');
    const intermittent = Array.from({ length: 16 }, (_, index) => (index % 4 === 0 ? 20 : 0));
    expect(classifyDemand(intermittent).pattern).toBe('intermitente');
  });
});

describe('auditoría de muestra', () => {
  const report = analyzePortfolio(sampleProducts());
  const byId = Object.fromEntries(report.products.map((product) => [product.productId, product]));

  it('separa mantener, corregir y descartar', () => {
    expect(byId['LECHE-1L'].decision).toBe('mantener');
    expect(byId['YERBA-1K'].decision).toBe('corregir');
    expect(byId['YERBA-1K'].corrections.some((item) => item.id === 'ajuste_sesgo')).toBe(true);
    expect(byId['GASEOSA-225'].decision).toBe('corregir');
    expect(byId['ALFAJOR'].decision).toBe('corregir');
    expect(byId['ALFAJOR'].corrections.some((item) => item.id === 'reemplazo_proyeccion')).toBe(true);
    expect(byId['ACEITE-900'].decision).toBe('corregir');
    expect(byId['ACEITE-900'].corrections.some((item) => item.id === 'llenar_huecos')).toBe(true);
    expect(byId['SKU-NUEVO'].decision).toBe('descartar');
    expect(byId['HARINA-ROTA'].decision).toBe('descartar');
  });

  it('recomienda un método acorde al patrón', () => {
    expect(['intermitente', 'irregular']).toContain(byId.BOMBA.pattern);
    expect(byId.BOMBA.decision).not.toBe('descartar');
    const names = byId.BOMBA.models.map((model) => model.name).join(' ');
    expect(names).toMatch(/Croston|SBA|TSB/);
    expect(byId['LECHE-1L'].models.some((model) => /Holt|estacional|Suavizado/i.test(model.name))).toBe(true);
    expect(byId['LECHE-1L'].metrics.length).toBeGreaterThan(30);
    expect(byId['YERBA-1K'].raw.wapeCorrected).toBeLessThan(byId['YERBA-1K'].raw.wape ?? 1);
  });

  it('no publica número para lo descartado y reimporta el csv', () => {
    const harina = byId['HARINA-ROTA'];
    expect(harina.series.every((row) => row.corrected == null)).toBe(true);
    const exported = correctedCsv(report);
    const parsed = parseCsv(exported);
    expect(parsed.products.length).toBe(report.products.length);
    const roundTrip = parseCsv(sampleCsv());
    expect(roundTrip.products).toHaveLength(8);
  });
});
