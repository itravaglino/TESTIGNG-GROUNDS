import type { Correction } from './types';
import { scoreForecast } from './metrics';
import { clamp, finite, median } from './stats';

export type AdjustedForecast = {
  values: Array<number | null>;
  corrections: Correction[];
  factor: number | null;
};

export function adjustForecast(forecast: Array<number | null>, actual: Array<number | null>): AdjustedForecast {
  const corrections: Correction[] = [];
  let values = forecast.slice();
  const demandIsNonNegative = actual.every((value) => value == null || value >= -1e-9);
  if (demandIsNonNegative && values.some((value) => finite(value) && (value as number) < 0)) {
    const count = values.filter((value) => finite(value) && (value as number) < 0).length;
    values = values.map((value) => (finite(value) ? Math.max(0, value) : value));
    corrections.push({
      id: 'clip_negativos',
      detail: `Se recortaron ${count} pronósticos negativos a cero.`,
    });
  }
  const winsorized = winsorize(values);
  if (winsorized.changed) {
    values = winsorized.values;
    corrections.push({
      id: 'winsorizar',
      detail: `Se reemplazaron ${winsorized.count} picos del pronóstico por la mediana de la serie.`,
    });
  }
  const factor = biasFactor(values, actual);
  if (factor != null && Math.abs(factor - 1) >= 0.08) {
    const scaled = values.map((value) => (finite(value) ? (value as number) * factor : value));
    const before = scoreForecast(values, actual).wape;
    const after = scoreForecast(scaled, actual).wape;
    if (before != null && after != null && after <= before * 0.95) {
      values = scaled;
      corrections.push({
        id: 'ajuste_sesgo',
        detail: `Se multiplicó el pronóstico por ${factor.toLocaleString('es-AR', { maximumFractionDigits: 2 })} para corregir el sesgo de volumen.`,
      });
      return { values, corrections, factor };
    }
  }
  return { values, corrections, factor: null };
}

function winsorize(values: Array<number | null>): { values: Array<number | null>; changed: boolean; count: number } {
  const clean = values.filter(finite) as number[];
  if (clean.length < 8) return { values, changed: false, count: 0 };
  const mid = median(clean);
  if (mid == null) return { values, changed: false, count: 0 };
  const deviations = clean.map((value) => Math.abs(value - mid));
  const mad = median(deviations);
  let count = 0;
  const next = values.map((value) => {
    if (!finite(value)) return value;
    const outlier =
      mad != null && mad >= 1e-9
        ? (0.6745 * Math.abs((value as number) - mid)) / mad > 3.5
        : Math.abs(mid) > 1e-9 && Math.abs((value as number) - mid) / Math.abs(mid) > 0.5;
    if (outlier) {
      count += 1;
      return mid;
    }
    return value;
  });
  return { values: next, changed: count > 0, count };
}

function biasFactor(forecast: Array<number | null>, actual: Array<number | null>): number | null {
  let sumF = 0;
  let sumA = 0;
  let n = 0;
  for (let i = 0; i < Math.min(forecast.length, actual.length); i += 1) {
    if (finite(forecast[i]) && (forecast[i] as number) > 0 && finite(actual[i]) && (actual[i] as number) >= 0) {
      sumF += forecast[i] as number;
      sumA += actual[i] as number;
      n += 1;
    }
  }
  if (n < 4 || sumF <= 0) return null;
  return clamp(sumA / sumF, 0.4, 1.8);
}
