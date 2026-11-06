import { finite } from './stats';
import { scoreForecast } from './metrics';

export type BaselineFit = {
  id: string;
  name: string;
  fitted: Array<number | null>;
  future: (horizon: number) => number[];
  wape: number | null;
};

export function fitBaselines(actual: Array<number | null>, season: number): BaselineFit[] {
  const y = actual.map((value) => (finite(value) ? value : null));
  const fits: BaselineFit[] = [
    naiveFit(y),
    seasonalNaiveFit(y, season),
    movingAverageFit(y, 3),
    sesFit(y),
  ];
  if (y.filter(finite).length >= 8) fits.push(holtFit(y));
  const nonzero = y.filter((value) => finite(value) && value > 0).length;
  const zeros = y.filter((value) => value === 0).length;
  if (nonzero >= 2 && zeros >= 2) fits.push(crostonFit(y));
  return fits
    .map((fit) => ({ ...fit, wape: scoreForecast(fit.fitted, y).wape }))
    .filter((fit) => fit.wape != null)
    .sort((a, b) => (a.wape as number) - (b.wape as number));
}

function naiveFit(y: Array<number | null>): BaselineFit {
  const fitted = y.map((_, index) => (index === 0 ? null : y[index - 1]));
  const last = lastFinite(y);
  return {
    id: 'naive',
    name: 'Naive (último valor)',
    fitted,
    future: (horizon) => Array.from({ length: horizon }, () => last ?? 0),
    wape: null,
  };
}

function seasonalNaiveFit(y: Array<number | null>, season: number): BaselineFit {
  const m = Math.max(1, season);
  const fitted = y.map((_, index) => (index >= m ? y[index - m] : null));
  return {
    id: 'estacional',
    name: m === 1 ? 'Naive estacional' : `Naive estacional (cada ${m})`,
    fitted,
    future: (horizon) => {
      const history = y.filter(finite) as number[];
      const cycle = history.slice(-m);
      if (!cycle.length) return Array.from({ length: horizon }, () => 0);
      return Array.from({ length: horizon }, (_, index) => cycle[index % cycle.length]);
    },
    wape: null,
  };
}

function movingAverageFit(y: Array<number | null>, window: number): BaselineFit {
  const fitted: Array<number | null> = [];
  for (let index = 0; index < y.length; index += 1) {
    const slice = y.slice(Math.max(0, index - window), index).filter(finite) as number[];
    fitted.push(slice.length ? slice.reduce((sum, value) => sum + value, 0) / slice.length : null);
  }
  return {
    id: `media_${window}`,
    name: `Media móvil ${window}`,
    fitted,
    future: (horizon) => {
      const tail = (y.filter(finite) as number[]).slice(-window);
      const value = tail.length ? tail.reduce((sum, item) => sum + item, 0) / tail.length : 0;
      return Array.from({ length: horizon }, () => value);
    },
    wape: null,
  };
}

function sesFit(y: Array<number | null>): BaselineFit {
  let bestAlpha = 0.3;
  let best = smooth(y, bestAlpha);
  let bestWape = scoreForecast(best.fitted, y).wape ?? Number.POSITIVE_INFINITY;
  for (let alpha = 0.1; alpha <= 0.9; alpha += 0.1) {
    const candidate = smooth(y, Number(alpha.toFixed(1)));
    const wape = scoreForecast(candidate.fitted, y).wape;
    if (wape != null && wape < bestWape) {
      bestWape = wape;
      best = candidate;
      bestAlpha = Number(alpha.toFixed(1));
    }
  }
  return {
    id: 'ses',
    name: `Suavizado exponencial (α ${bestAlpha.toLocaleString('es-AR')})`,
    fitted: best.fitted,
    future: (horizon) => Array.from({ length: horizon }, () => best.level),
    wape: null,
  };
}

function smooth(y: Array<number | null>, alpha: number): { fitted: Array<number | null>; level: number } {
  const first = y.find(finite) ?? 0;
  let level = first;
  let started = false;
  const fitted: Array<number | null> = [];
  for (const value of y) {
    if (!started) {
      fitted.push(null);
      if (finite(value)) {
        level = value;
        started = true;
      }
      continue;
    }
    fitted.push(level);
    if (finite(value)) level = alpha * value + (1 - alpha) * level;
  }
  return { fitted, level };
}

function holtFit(y: Array<number | null>): BaselineFit {
  let best = holt(y, 0.4, 0.2);
  let bestWape = scoreForecast(best.fitted, y).wape ?? Number.POSITIVE_INFINITY;
  let label = 'Holt (α 0,4 β 0,2)';
  for (const alpha of [0.3, 0.5, 0.8]) {
    for (const beta of [0.1, 0.3]) {
      const candidate = holt(y, alpha, beta);
      const wape = scoreForecast(candidate.fitted, y).wape;
      if (wape != null && wape < bestWape) {
        bestWape = wape;
        best = candidate;
        label = `Holt (α ${alpha.toLocaleString('es-AR')} β ${beta.toLocaleString('es-AR')})`;
      }
    }
  }
  return {
    id: 'holt',
    name: label,
    fitted: best.fitted,
    future: (horizon) => Array.from({ length: horizon }, (_, h) => Math.max(0, best.level + (h + 1) * best.trend)),
    wape: null,
  };
}

function holt(y: Array<number | null>, alpha: number, beta: number): { fitted: Array<number | null>; level: number; trend: number } {
  const observed = y.filter(finite) as number[];
  let level = observed[0] ?? 0;
  let trend = observed.length > 1 ? observed[1] - observed[0] : 0;
  let seen = 0;
  const fitted: Array<number | null> = [];
  for (const value of y) {
    if (!finite(value)) {
      fitted.push(seen ? level + trend : null);
      continue;
    }
    if (seen === 0) {
      fitted.push(null);
      level = value;
      seen += 1;
      continue;
    }
    const forecast = level + trend;
    fitted.push(forecast);
    const nextLevel = alpha * value + (1 - alpha) * (level + trend);
    trend = beta * (nextLevel - level) + (1 - beta) * trend;
    level = nextLevel;
    seen += 1;
  }
  return { fitted, level, trend };
}

function crostonFit(y: Array<number | null>): BaselineFit {
  let bestAlpha = 0.2;
  let best = croston(y, bestAlpha, true);
  let bestWape = scoreForecast(best.fitted, y).wape ?? Number.POSITIVE_INFINITY;
  for (const alpha of [0.1, 0.2, 0.3, 0.5]) {
    for (const sba of [true, false]) {
      const candidate = croston(y, alpha, sba);
      const wape = scoreForecast(candidate.fitted, y).wape;
      if (wape != null && wape < bestWape) {
        bestWape = wape;
        best = candidate;
        bestAlpha = alpha;
      }
    }
  }
  return {
    id: best.sba ? 'sba' : 'croston',
    name: best.sba ? `SBA de Croston (α ${bestAlpha.toLocaleString('es-AR')})` : `Croston (α ${bestAlpha.toLocaleString('es-AR')})`,
    fitted: best.fitted,
    future: (horizon) => Array.from({ length: horizon }, () => Math.max(0, best.rate)),
    wape: null,
  };
}

function croston(
  y: Array<number | null>,
  alpha: number,
  sba: boolean,
): { fitted: Array<number | null>; rate: number; sba: boolean } {
  let size = 0;
  let interval = 1;
  let since = 1;
  let ready = false;
  const fitted: Array<number | null> = [];
  for (const value of y) {
    const demand = finite(value) ? Math.max(0, value) : 0;
    if (!ready) {
      fitted.push(null);
      if (demand > 0) {
        size = demand;
        interval = Math.max(1, since);
        since = 1;
        ready = true;
      } else since += 1;
      continue;
    }
    const factor = sba ? 1 - alpha / 2 : 1;
    fitted.push((size / interval) * factor);
    if (demand > 0) {
      size = alpha * demand + (1 - alpha) * size;
      interval = alpha * since + (1 - alpha) * interval;
      since = 1;
    } else since += 1;
  }
  const factor = sba ? 1 - alpha / 2 : 1;
  return { fitted, rate: ready ? (size / interval) * factor : 0, sba };
}

function lastFinite(values: Array<number | null>): number | null {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (finite(values[index])) return values[index] as number;
  }
  return null;
}
