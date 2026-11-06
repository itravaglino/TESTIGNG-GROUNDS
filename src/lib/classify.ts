import type { Grain, Pattern } from './types';
import { finite, mean, stdev } from './stats';

const ADI_CUTOFF = 1.32;
const CV2_CUTOFF = 0.49;

export type DemandProfile = {
  pattern: Pattern;
  adi: number | null;
  cv2: number | null;
  zeroShare: number | null;
  demandEvents: number;
};

export function classifyDemand(values: Array<number | null>): DemandProfile {
  const clean = values.map((value) => (finite(value) ? value : null)).filter((value): value is number => value != null);
  if (clean.length < 4) {
    return { pattern: 'insuficiente', adi: null, cv2: null, zeroShare: null, demandEvents: clean.filter((v) => v > 0).length };
  }
  const events = clean
    .map((value, index) => (value > 0 ? index : -1))
    .filter((index) => index >= 0);
  const zeroShare = clean.filter((value) => value === 0).length / clean.length;
  if (events.length < 2) {
    return { pattern: 'insuficiente', adi: events.length === 1 ? clean.length : null, cv2: null, zeroShare, demandEvents: events.length };
  }
  let intervalSum = 0;
  for (let i = 1; i < events.length; i += 1) intervalSum += events[i] - events[i - 1];
  const adi = intervalSum / (events.length - 1);
  const sizes = events.map((index) => clean[index]);
  const avg = mean(sizes);
  const sd = stdev(sizes);
  const cv2 = avg && sd != null && Math.abs(avg) > 1e-9 ? (sd / avg) ** 2 : 0;
  let pattern: Pattern;
  if (adi < ADI_CUTOFF && cv2 < CV2_CUTOFF) pattern = 'suave';
  else if (adi < ADI_CUTOFF && cv2 >= CV2_CUTOFF) pattern = 'errática';
  else if (adi >= ADI_CUTOFF && cv2 < CV2_CUTOFF) pattern = 'intermitente';
  else pattern = 'irregular';
  return { pattern, adi, cv2, zeroShare, demandEvents: events.length };
}

export function inferGrain(dates: string[]): { grain: Grain; season: number; stepDays: number | null } {
  const times = dates
    .map((date) => Date.parse(`${date}T00:00:00Z`))
    .filter((time) => Number.isFinite(time))
    .sort((a, b) => a - b);
  if (times.length < 2) return { grain: 'irregular', season: 1, stepDays: null };
  const diffs: number[] = [];
  for (let i = 1; i < times.length; i += 1) diffs.push((times[i] - times[i - 1]) / 86_400_000);
  diffs.sort((a, b) => a - b);
  const step = diffs[Math.floor(diffs.length / 2)];
  if (step <= 2) return { grain: 'diaria', season: 7, stepDays: 1 };
  if (step <= 10) return { grain: 'semanal', season: 52, stepDays: 7 };
  if (step <= 40) return { grain: 'mensual', season: 12, stepDays: 30 };
  if (step <= 120) return { grain: 'trimestral', season: 4, stepDays: 91 };
  return { grain: 'irregular', season: 1, stepDays: step };
}

export function expectedDates(dates: string[], grain: Grain): string[] {
  const sorted = [...dates].sort();
  if (sorted.length < 2 || grain === 'irregular') return sorted;
  if (grain === 'mensual' || grain === 'trimestral') {
    const step = grain === 'mensual' ? 1 : 3;
    const start = monthIndex(sorted[0]);
    const end = monthIndex(sorted[sorted.length - 1]);
    const out: string[] = [];
    for (let cursor = start; cursor <= end; cursor += step) out.push(fromMonthIndex(cursor));
    return out;
  }
  const step = grain === 'diaria' ? 1 : 7;
  const start = Date.parse(`${sorted[0]}T00:00:00Z`);
  const end = Date.parse(`${sorted[sorted.length - 1]}T00:00:00Z`);
  const out: string[] = [];
  for (let cursor = start; cursor <= end; cursor += step * 86_400_000) {
    out.push(new Date(cursor).toISOString().slice(0, 10));
  }
  return out;
}

function monthIndex(iso: string): number {
  const [year, month] = iso.slice(0, 7).split('-').map(Number);
  return year * 12 + (month - 1);
}

function fromMonthIndex(index: number): string {
  const year = Math.floor(index / 12);
  const month = (index % 12) + 1;
  return `${year}-${String(month).padStart(2, '0')}-01`;
}
