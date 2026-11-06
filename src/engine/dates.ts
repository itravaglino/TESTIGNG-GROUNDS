import type { PeriodType } from "./types";

const MONTHS: Record<string, number> = {
  ene: 1,
  enero: 1,
  jan: 1,
  january: 1,
  feb: 2,
  febrero: 2,
  fev: 2,
  february: 2,
  mar: 3,
  marzo: 3,
  march: 3,
  abr: 4,
  abril: 4,
  apr: 4,
  april: 4,
  may: 5,
  mayo: 5,
  mai: 5,
  jun: 6,
  junio: 6,
  june: 6,
  jul: 7,
  julio: 7,
  july: 7,
  ago: 8,
  agosto: 8,
  aug: 8,
  august: 8,
  sep: 9,
  set: 9,
  sept: 9,
  septiembre: 9,
  setembro: 9,
  september: 9,
  oct: 10,
  octubre: 10,
  out: 10,
  october: 10,
  nov: 11,
  noviembre: 11,
  november: 11,
  dic: 12,
  diciembre: 12,
  dez: 12,
  dec: 12,
  december: 12,
};

export function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function iso(y: number, m: number, d: number): string | null {
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
  return `${y}-${pad(m)}-${pad(d)}`;
}

function expandYear(y: number): number {
  if (y < 100) return y <= 69 ? 2000 + y : 1900 + y;
  return y;
}

export function parseDate(raw: string | number | null | undefined): { date: string; periodType: PeriodType } | null {
  if (raw == null) return null;
  if (typeof raw === "number") {
    if (Number.isInteger(raw) && raw >= 199001 && raw <= 210012) {
      const s = String(raw);
      if (s.length === 6) {
        const y = Number(s.slice(0, 4));
        const m = Number(s.slice(4, 6));
        const d = iso(y, m, 1);
        return d ? { date: d, periodType: "month" } : null;
      }
    }
    if (raw >= 20000 && raw <= 80000) {
      return excelSerial(raw);
    }
    return null;
  }
  const t = String(raw).trim();
  if (!t) return null;

  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    const d = iso(Number(m[1]), Number(m[2]), Number(m[3]));
    return d ? { date: d, periodType: "day" } : null;
  }
  m = t.match(/^(\d{4})[-/](\d{1,2})$/);
  if (m) {
    const d = iso(Number(m[1]), Number(m[2]), 1);
    return d ? { date: d, periodType: "month" } : null;
  }
  m = t.match(/^(\d{6})$/);
  if (m) {
    const y = Number(m[1].slice(0, 4));
    const mo = Number(m[1].slice(4, 6));
    const d = iso(y, mo, 1);
    return d ? { date: d, periodType: "month" } : null;
  }
  m = t.match(/^(\d{8})$/);
  if (m) {
    const y = Number(m[1].slice(0, 4));
    const mo = Number(m[1].slice(4, 6));
    const day = Number(m[1].slice(6, 8));
    const d = iso(y, mo, day);
    return d ? { date: d, periodType: "day" } : null;
  }
  m = t.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/);
  if (m) {
    const a = Number(m[1]);
    const b = Number(m[2]);
    const y = expandYear(Number(m[3]));
    if (a > 12 && b <= 12) {
      const d = iso(y, b, a);
      return d ? { date: d, periodType: "day" } : null;
    }
    if (b > 12 && a <= 12) {
      const d = iso(y, a, b);
      return d ? { date: d, periodType: "day" } : null;
    }
    const d = iso(y, b, a);
    return d ? { date: d, periodType: "day" } : null;
  }
  m = t.match(/^([A-Za-zÀ-ÿ]{3,9})[.\s-]+(\d{2,4})$/);
  if (m) {
    const mo = MONTHS[fold(m[1])];
    if (mo) {
      const d = iso(expandYear(Number(m[2])), mo, 1);
      return d ? { date: d, periodType: "month" } : null;
    }
  }
  m = t.match(/^(\d{4})[-]?[Ww](\d{1,2})$/);
  if (m) {
    return isoWeek(Number(m[1]), Number(m[2]));
  }
  if (/^\d+(\.\d+)?$/.test(t)) {
    const n = Number(t);
    if (n >= 20000 && n <= 80000) return excelSerial(n);
    if (Number.isInteger(n) && t.length === 6) {
      const y = Number(t.slice(0, 4));
      const mo = Number(t.slice(4, 6));
      const d = iso(y, mo, 1);
      return d ? { date: d, periodType: "month" } : null;
    }
  }
  return null;
}

function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

function excelSerial(serial: number): { date: string; periodType: PeriodType } | null {
  const whole = Math.floor(serial);
  if (whole === 60) return null;
  const utc = Date.UTC(1899, 11, 30) + whole * 86400000;
  const dt = new Date(utc);
  const d = iso(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
  return d ? { date: d, periodType: "day" } : null;
}

function isoWeek(year: number, week: number): { date: string; periodType: PeriodType } | null {
  const simple = new Date(Date.UTC(year, 0, 4));
  const day = simple.getUTCDay() || 7;
  const monday = new Date(simple);
  monday.setUTCDate(simple.getUTCDate() - day + 1 + (week - 1) * 7);
  const d = iso(monday.getUTCFullYear(), monday.getUTCMonth() + 1, monday.getUTCDate());
  return d ? { date: d, periodType: "week" } : null;
}

export function headerLooksLikePeriod(header: string): { date: string; periodType: PeriodType } | null {
  return parseDate(header);
}

export function medianGapDays(dates: string[]): number | null {
  const uniq = [...new Set(dates)].sort();
  if (uniq.length < 2) return null;
  const gaps: number[] = [];
  for (let i = 1; i < uniq.length; i++) {
    const a = Date.parse(uniq[i - 1] + "T00:00:00Z");
    const b = Date.parse(uniq[i] + "T00:00:00Z");
    gaps.push((b - a) / 86400000);
  }
  gaps.sort((x, y) => x - y);
  return gaps[Math.floor((gaps.length - 1) / 2)] ?? null;
}

export function inferPeriodType(dates: string[], locked: PeriodType | "unknown"): PeriodType {
  if (locked !== "unknown") return locked;
  const gap = medianGapDays(dates);
  if (gap == null) return "unknown";
  if (gap === 1) return "day";
  if (gap >= 6 && gap <= 8) return "week";
  if (gap >= 27 && gap <= 32) return "month";
  if (gap >= 89 && gap <= 92) return "quarter";
  if (gap >= 360 && gap <= 370) return "year";
  return "unknown";
}

export function seasonLag(periodType: PeriodType): number {
  if (periodType === "week") return 52;
  if (periodType === "day") return 7;
  if (periodType === "quarter") return 4;
  return 12;
}
