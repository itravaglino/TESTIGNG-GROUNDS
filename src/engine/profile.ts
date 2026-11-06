import type { CanonicalRow, ForecastFrequency, SeriesProfile } from "./types";

function mean(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}
function std(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((s, x) => s + (x - m) ** 2, 0) / xs.length);
}

function medianDiff(timestamps: number[]): number | null {
  if (timestamps.length < 2) return null;
  const diffs = [];
  for (let i = 1; i < timestamps.length; i++) diffs.push(timestamps[i] - timestamps[i - 1]);
  diffs.sort((a, b) => a - b);
  return diffs[Math.floor(diffs.length / 2)];
}

export function inferFrequency(timestamps: number[]): ForecastFrequency {
  const d = medianDiff(timestamps);
  if (d === null) return "unknown";
  const day = 86400000;
  if (d < day * 2) return "daily";
  if (d < day * 10) return "weekly";
  if (d < day * 45) return "monthly";
  if (d < day * 120) return "quarterly";
  return "unknown";
}

export function seasonFor(freq: ForecastFrequency): number {
  if (freq === "daily") return 7;
  if (freq === "weekly") return 52;
  if (freq === "monthly") return 12;
  if (freq === "quarterly") return 4;
  return 1;
}

function autocorr(xs: number[], lag: number): number | null {
  if (xs.length <= lag + 2) return null;
  const a = xs.slice(0, xs.length - lag);
  const b = xs.slice(lag);
  const ma = mean(a);
  const mb = mean(b);
  let num = 0;
  let da = 0;
  let db = 0;
  for (let i = 0; i < a.length; i++) {
    const x = a[i] - ma;
    const y = b[i] - mb;
    num += x * y;
    da += x * x;
    db += y * y;
  }
  if (da === 0 || db === 0) return null;
  return num / Math.sqrt(da * db);
}

function demandClass(adi: number | null, cv2: number | null): SeriesProfile["demandClass"] {
  if (adi === null || cv2 === null) return "unknown";
  if (adi < 1.32 && cv2 < 0.49) return "smooth";
  if (adi < 1.32 && cv2 >= 0.49) return "erratic";
  if (adi >= 1.32 && cv2 < 0.49) return "intermittent";
  return "lumpy";
}

export function profileSeries(productId: string, productName: string, rows: CanonicalRow[]): SeriesProfile {
  const ordered = [...rows].sort((a, b) => a.timestamp - b.timestamp);
  const forecasts = ordered.map((r) => r.forecast).filter(Number.isFinite);
  const actuals = ordered.map((r) => r.actual).filter((v): v is number => v !== null && Number.isFinite(v));
  const ts = ordered.map((r) => r.timestamp).filter(Number.isFinite);
  const frequency = inferFrequency(ts);
  const seasonLength = seasonFor(frequency);
  const meanForecast = mean(forecasts);
  const meanActual = actuals.length ? mean(actuals) : null;
  const stdForecast = std(forecasts);
  const stdActual = actuals.length ? std(actuals) : null;
  const zerosA = actuals.filter((v) => v === 0).length;
  const demand = actuals.filter((v) => v > 0);
  const nA = actuals.length;
  const adi = nA > 0 && demand.length > 0 ? nA / demand.length : nA > 0 ? Infinity : null;
  const cv2 = demand.length > 1 ? (std(demand) / mean(demand)) ** 2 : demand.length === 1 ? 0 : null;
  const intermittence = nA > 0 ? zerosA / nA : null;
  let slope = 0;
  if (forecasts.length >= 4) {
    const n = forecasts.length;
    let sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (let i = 0; i < n; i++) {
      sx += i;
      sy += forecasts[i];
      sxx += i * i;
      sxy += i * forecasts[i];
    }
    const den = n * sxx - sx * sx;
    slope = den === 0 ? 0 : (n * sxy - sx * sy) / den;
  }
  const rel = meanForecast !== 0 ? slope / Math.abs(meanForecast) : 0;
  let trend: SeriesProfile["trend"] = "flat";
  if (!Number.isFinite(rel)) trend = "unknown";
  else if (rel > 0.25) trend = "explosive";
  else if (rel > 0.02) trend = "up";
  else if (rel < -0.02) trend = "down";
  const ac = autocorr(actuals.length >= 8 ? actuals : forecasts, Math.min(seasonLength, Math.floor((actuals.length || forecasts.length) / 3)));
  return {
    productId,
    productName,
    n: ordered.length,
    nWithActual: actuals.length,
    frequency,
    start: ordered[0]?.date ?? null,
    end: ordered[ordered.length - 1]?.date ?? null,
    meanForecast,
    meanActual,
    stdForecast,
    stdActual,
    cvForecast: meanForecast !== 0 ? stdForecast / Math.abs(meanForecast) : null,
    cvActual: meanActual && meanActual !== 0 && stdActual !== null ? stdActual / Math.abs(meanActual) : null,
    zeroForecastShare: forecasts.length ? forecasts.filter((v) => v === 0).length / forecasts.length : 0,
    zeroActualShare: nA ? zerosA / nA : null,
    intermittence,
    adi: adi === Infinity ? 99 : adi,
    cv2,
    demandClass: demandClass(adi === Infinity ? 99 : adi, cv2),
    trend,
    seasonalStrength: ac,
    seasonLength,
    modelsUsed: [...new Set(ordered.map((r) => r.model).filter((v): v is string => !!v))],
    locations: [...new Set(ordered.map((r) => r.location).filter((v): v is string => !!v))],
    channels: [...new Set(ordered.map((r) => r.channel).filter((v): v is string => !!v))],
  };
}
