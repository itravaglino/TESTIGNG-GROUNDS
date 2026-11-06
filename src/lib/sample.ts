import type { ProductInput } from './types';

function month(index: number): string {
  const year = 2024 + Math.floor(index / 12);
  const monthNumber = (index % 12) + 1;
  return `${year}-${String(monthNumber).padStart(2, '0')}-01`;
}

function series(
  productId: string,
  productName: string,
  category: string,
  indexes: number[],
  value: (index: number) => { forecast: number | null; actual: number | null },
): ProductInput {
  return {
    productId,
    productName,
    category,
    points: indexes.map((index) => ({ date: month(index), lower: null, upper: null, ...value(index) })),
  };
}

const ALL = Array.from({ length: 24 }, (_, index) => index);

export function sampleProducts(): ProductInput[] {
  return [
    series('LECHE-1L', 'Leche entera 1L', 'Lácteos', ALL, (index) => {
      const actual = 100 + (index % 12 < 6 ? 30 : -10);
      return { actual, forecast: actual + 2 };
    }),
    series('YERBA-1K', 'Yerba 1kg', 'Almacén', ALL, () => ({ actual: 80, forecast: 120 })),
    series('GASEOSA-225', 'Gaseosa 2.25', 'Bebidas', ALL, (index) => ({
      actual: 60,
      forecast: index === 4 || index === 9 ? -20 : index === 16 ? 500 : 60,
    })),
    series('ALFAJOR', 'Alfajor triple', 'Golosiñas', ALL, (index) => ({
      actual: 100 + (index % 12) * 2,
      forecast: index % 2 === 0 ? 20 : 400,
    })),
    series('BOMBA', 'Repuesto bomba', 'Repuestos', ALL, (index) => ({
      actual: index % 4 === 0 ? 24 + (index > 11 ? 6 : 0) : 0,
      forecast: 8,
    })),
    series('ACEITE-900', 'Aceite 900ml', 'Almacén', ALL.filter((index) => ![5, 6, 10].includes(index)), (index) => {
      const actual = 40 + (index % 6) * 3;
      return { actual, forecast: actual + 1 };
    }),
    series('SKU-NUEVO', 'SKU nuevo sin historia', 'Lanzamientos', [0, 1, 2], (index) => ({
      actual: 10 + index,
      forecast: 80 + index * 5,
    })),
    series('HARINA-ROTA', 'Harina 000 rota', 'Almacén', ALL.slice(0, 12), () => ({ actual: 25, forecast: -10 })),
  ];
}

export function sampleCsv(): string {
  const lines = ['producto;nombre;categoria;fecha;pronostico;real'];
  for (const product of sampleProducts()) {
    for (const point of product.points) {
      lines.push(
        [product.productId, product.productName, product.category, point.date, cell(point.forecast), cell(point.actual)].join(';'),
      );
    }
  }
  return lines.join('\n');
}

export function templateCsv(): string {
  return [
    'producto;nombre;categoria;fecha;pronostico;real',
    'SKU-001;Ejemplo;Categoría;2025-01-01;120;100',
    'SKU-001;Ejemplo;Categoría;2025-02-01;110;108',
  ].join('\n');
}

function cell(value: number | null): string {
  if (value == null) return '';
  return String(value).replace('.', ',');
}
