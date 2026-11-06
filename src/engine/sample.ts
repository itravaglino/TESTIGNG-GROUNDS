import { toIsoDate } from "./parse";

function mondayWeeks(n: number, start = "2025-01-06"): Date[] {
  const [y, m, d] = start.split("-").map(Number);
  const dates: Date[] = [];
  const cur = new Date(Date.UTC(y, m - 1, d));
  for (let i = 0; i < n; i++) {
    dates.push(new Date(cur.getTime()));
    cur.setUTCDate(cur.getUTCDate() + 7);
  }
  return dates;
}

function noise(i: number, amp: number): number {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return ((x - Math.floor(x)) * 2 - 1) * amp;
}

export function buildSampleCsv(): string {
  const weeks = mondayWeeks(52);
  const header = "sku,nombre,fecha,pronostico,ventas,deposito";
  const lines = [header];

  const push = (
    sku: string,
    nombre: string,
    fcst: (i: number, date: Date) => number,
    actual: (i: number, date: Date) => number,
    skip?: (i: number) => boolean,
  ) => {
    weeks.forEach((date, i) => {
      if (skip?.(i)) return;
      lines.push(
        [sku, nombre, toIsoDate(date), String(Math.round(fcst(i, date) * 100) / 100), String(Math.round(actual(i, date))), "CABA"].join(","),
      );
    });
  };

  push(
    "SKU-LECHE-1L",
    "Leche entera 1L",
    (i) => 220 + 18 * Math.sin((2 * Math.PI * i) / 52) + noise(i, 6),
    (i) => 218 + 18 * Math.sin((2 * Math.PI * i) / 52) + noise(i + 3, 8),
  );

  push(
    "SKU-PAN-BAG",
    "Pan baguette",
    (i) => (i === 10 || i === 27 ? -15 : 80 + noise(i, 5)),
    (i) => 78 + noise(i + 1, 6),
  );

  push(
    "SKU-YOGUR",
    "Yogur firme",
    (i) => 140 + 10 * Math.sin(i / 4) + noise(i, 4),
    (i) => 138 + 10 * Math.sin(i / 4) + noise(i, 5),
    (i) => i === 8 || i === 9 || i === 33,
  );

  push(
    "SKU-ACEITE",
    "Aceite 1.5L",
    (i) => (i === 14 ? 900 : 55 + noise(i, 4)),
    (i) => 54 + noise(i + 2, 5),
  );

  push(
    "SKU-FILTRO",
    "Filtro de aire",
    (i) => ([0, 1, 0, 0, 2, 0, 0, 1, 0, 0, 3, 0][i % 12] ?? 0),
    (i) => ([0, 0, 0, 1, 0, 0, 2, 0, 0, 0, 1, 0][i % 12] ?? 0),
  );

  push(
    "SKU-NUEVO",
    "Barra protein lanzamiento",
    (i) => 40 + i,
    (i) => 35 + i,
    (i) => i < 46,
  );

  push(
    "SKU-ZERO",
    "SKU deslistado",
    () => 0,
    () => 0,
  );

  push(
    "SKU-CAJAS",
    "Gaseosa pack",
    (i) => 12 * (90 + noise(i, 3)),
    (i) => 88 + noise(i, 4),
  );

  push(
    "SKU-CONST",
    "Arroz 1kg",
    () => 100,
    (i) => 70 + 40 * Math.sin((2 * Math.PI * i) / 52) + noise(i, 8),
  );

  push(
    "SKU-LUMPY",
    "Repuesto motor",
    (i) => (i % 7 === 0 ? 12 + noise(i, 2) : 0),
    (i) => (i % 7 === 0 ? 8 + Math.abs(noise(i, 6)) : 0),
  );

  push(
    "SKU-HELADO",
    "Helado 1kg",
    () => 60,
    (i) => 40 + 55 * Math.sin((2 * Math.PI * (i - 8)) / 52) + noise(i, 5),
  );

  push(
    "SKU-BIAS",
    "Cerveza lata",
    (i) => 1.3 * (150 + 20 * Math.sin((2 * Math.PI * i) / 26) + noise(i, 4)),
    (i) => 150 + 20 * Math.sin((2 * Math.PI * i) / 26) + noise(i, 5),
  );

  return lines.join("\n");
}

export const FORMAT_SPEC = `Columnas mínimas:
- sku / producto / product_id
- fecha (YYYY-MM-DD, DD/MM/YYYY, YYYY-WW)
- pronostico / forecast / yhat

Opcionales:
- ventas / actual / demanda_real  (habilita WAPE, sesgo, MASE…)
- nombre, deposito/tienda, modelo, precio, lower, upper

Separador: coma, punto y coma o tab. Decimales con coma o punto.`;
