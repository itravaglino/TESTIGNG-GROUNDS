const SENTINELS = new Set([
  "",
  "-",
  "—",
  "n/a",
  "na",
  "s/d",
  "sd",
  "null",
  "#n/a",
  "#¡valor!",
  "#value!",
  "#div/0!",
  "#valor!",
]);

export type NumberLocale = "es" | "en" | "undecided";

export function isSentinel(raw: string): boolean {
  return SENTINELS.has(raw.trim().toLowerCase());
}

export function voteLocale(tokens: string[]): NumberLocale {
  let es = 0;
  let en = 0;
  for (const token of tokens) {
    const t = stripDecor(token);
    if (!t) continue;
    if (/\d+\.\d{3},\d+/.test(t) || /\d+,\d{1,2}$/.test(t)) es += 1;
    if (/\d+,\d{3}\.\d+/.test(t) || (/\d+\.\d{1,2}$/.test(t) && !t.includes(","))) en += 1;
  }
  if (es > en) return "es";
  if (en > es) return "en";
  return "es";
}

function stripDecor(raw: string): string {
  return raw
    .replace(/ARS|USD|U\$S|R\$|EUR/gi, "")
    .replace(/[$€]/g, "")
    .replace(/[\s\u00a0\u202f]/g, "")
    .trim();
}

export function parseNumber(raw: string | number | null | undefined, locale: NumberLocale = "es"): number | null {
  if (raw == null) return null;
  if (typeof raw === "number") return Number.isFinite(raw) ? raw : null;
  const original = String(raw).trim();
  if (!original || isSentinel(original)) return null;
  let t = stripDecor(original);
  let neg = false;
  if (/^\(.*\)$/.test(t)) {
    neg = true;
    t = t.slice(1, -1);
  }
  if (t.endsWith("-")) {
    neg = true;
    t = t.slice(0, -1);
  }
  let pct = false;
  if (t.endsWith("%")) {
    pct = true;
    t = t.slice(0, -1);
  }
  if (!t || /[a-zA-Z]/.test(t)) return null;

  let value: number;
  if (locale === "es") {
    if (t.includes(".") && t.includes(",")) {
      value = Number(t.replace(/\./g, "").replace(",", "."));
    } else if (t.includes(",")) {
      const frac = t.split(",")[1] ?? "";
      if (frac.length === 3 && !t.includes(".")) value = Number(t.replace(/,/g, ""));
      else value = Number(t.replace(",", "."));
    } else if (/^\d{1,3}(\.\d{3})+$/.test(t)) {
      value = Number(t.replace(/\./g, ""));
    } else {
      value = Number(t);
    }
  } else {
    if (t.includes(",") && t.includes(".")) {
      value = Number(t.replace(/,/g, ""));
    } else if (t.includes(",") && /^\d{1,3}(,\d{3})+$/.test(t)) {
      value = Number(t.replace(/,/g, ""));
    } else {
      value = Number(t);
    }
  }
  if (!Number.isFinite(value)) return null;
  if (neg) value = -value;
  if (pct) value = value / 100;
  return value;
}
