import { fitBaselines, type BaselineFit } from './baselines';
import { classifyDemand, expectedDates, inferGrain } from './classify';
import { adjustForecast } from './correct';
import { coefficientOfVariation, coverage, fva, mase, scoreForecast, theilU } from './metrics';
import { recommendModels } from './recommend';
import { acf, finite, pearson } from './stats';
import type {
  CanonicalPoint,
  Confidence,
  Correction,
  Decision,
  MetricView,
  PortfolioReport,
  ProductInput,
  ProductReport,
  SeriesRow,
} from './types';

const THRESHOLDS = [
  'Mantener: WAPE hasta 40% y sesgo de volumen dentro de ±20%, con al menos 6 períodos comparables.',
  'Corregir: el número se puede rescatar recortando negativos, bajando picos, ajustando sesgo o reemplazándolo por un método simple mejor.',
  'Descartar: el archivo está roto, la historia no alcanza para corregir, o ni el forecast ni un método simple merecen publicarse.',
  'En demanda intermitente el WAPE se infla por los ceros. Ahí manda el MASE contra el estacional y Croston/SBA.',
];

export function analyzePortfolio(products: ProductInput[]): PortfolioReport {
  const reports = products.map(analyzeProduct);
  const order: Record<Decision, number> = { descartar: 0, corregir: 1, mantener: 2 };
  reports.sort((a, b) => order[a.decision] - order[b.decision] || (b.raw.wape ?? -1) - (a.raw.wape ?? -1));
  const volume = reports.reduce((sum, report) => sum + volumeOf(report), 0);
  return {
    products: reports,
    totals: {
      products: reports.length,
      mantener: reports.filter((report) => report.decision === 'mantener').length,
      corregir: reports.filter((report) => report.decision === 'corregir').length,
      descartar: reports.filter((report) => report.decision === 'descartar').length,
      wape: weightedWape(reports, 'wape', volume),
      wapeCorrected: weightedWape(reports, 'wapeCorrected', volume),
      volume,
    },
    processNotes: processNotes(reports),
    thresholds: THRESHOLDS,
  };
}

function analyzeProduct(product: ProductInput): ProductReport {
  const calendar = buildCalendar(product.points);
  const actual = calendar.map((point) => point.actual);
  const forecast = calendar.map((point) => point.forecast);
  const observed = actual.filter(finite);
  const profileSource = observed.length >= 4 ? actual : forecast;
  const profile = classifyDemand(profileSource);
  const grainInfo = inferGrain(product.points.map((point) => point.date));
  const season = grainInfo.season;
  const seasonalStrength = observed.length > season + 2 ? acf(observed, Math.min(season, observed.length - 3)) : null;
  const trendStrength = Math.abs(pearson(observed, observed.map((_, index) => index)) ?? 0) || null;
  const baselines = observed.length >= 3 ? fitBaselines(actual, season) : [];
  const best = baselines[0] ?? null;
  const adjusted = adjustForecast(forecast, actual);
  const gapFill = fillForecastGaps(calendar, adjusted.values, season);
  const corrections = [...adjusted.corrections];
  if ((product.duplicateDates ?? 0) > 0) {
    corrections.unshift({
      id: 'promedio_duplicados',
      detail: `Había ${product.duplicateDates} fecha(s) repetida(s). Se usó el promedio.`,
    });
  }
  if (gapFill.filled) corrections.push(gapFill.correction);

  const originalScore = scoreForecast(forecast, actual);
  const adjustedScore = scoreForecast(gapFill.values, actual);
  const naive = baselines.find((item) => item.id === 'naive') ?? null;
  const seasonal = baselines.find((item) => item.id === 'estacional') ?? null;
  const intermittent = profile.pattern === 'intermitente' || profile.pattern === 'irregular';
  const userMase = mase(gapFill.values, actual, season);
  const bestMase = best ? mase(best.fitted, actual, season) : null;
  const negativeShare = share(forecast, (value) => value < 0);
  const gaps = calendar.filter((point) => point.inserted).length;
  const gapShare = calendar.length ? gaps / calendar.length : 0;
  const overlap = originalScore.n;

  let values = gapFill.values;
  let replaced = false;
  if (
    best &&
    shouldReplace({
      intermittent,
      userWape: adjustedScore.wape,
      bestWape: best.wape,
      userMase,
      bestMase,
      overlap,
    })
  ) {
    values = projectBaseline(calendar, best);
    replaced = true;
    corrections.push({
      id: 'reemplazo_proyeccion',
      detail: `El pronóstico original pierde contra ${best.name}. Se reemplazó por esa proyección, calculada solo con historia previa.`,
    });
  }

  const shippedScore = scoreForecast(values, actual);
  const decision = decide({
    overlap,
    gaps,
    gapShare,
    negativeShare,
    duplicateDates: product.duplicateDates ?? 0,
    forecastPoints: forecast.filter(finite).length,
    originalWape: originalScore.wape,
    shippedWape: shippedScore.wape,
    biasPct: adjustedScore.biasPct,
    correlation: originalScore.correlation,
    intermittent,
    userMase,
    best,
    corrections: corrections.length,
    brokenMajority: negativeShare > 0.6 || gapShare > 0.5,
  });

  const shipped = decision === 'descartar' ? values.map(() => null) : values;
  const series = calendar.map((point, index) => toSeriesRow(point, forecast[index], shipped[index], decision, replaced));
  const confidence = confidenceOf(overlap, profile.pattern, decision);
  const models = recommendModels({
    pattern: profile.pattern,
    grain: grainInfo.grain,
    season,
    history: observed.length,
    seasonalStrength,
    trendStrength,
    baselines,
  });
  const raw = {
    overlap,
    periods: calendar.length,
    gaps,
    duplicates: product.duplicateDates ?? 0,
    negativeShare,
    wape: originalScore.wape,
    wapeCorrected: decision === 'descartar' ? null : shippedScore.wape,
    biasPct: originalScore.biasPct,
    mase: userMase,
    fvaNaive: fva(originalScore.wape, naive?.wape ?? null),
    correlation: originalScore.correlation,
    bestBaseline: best?.name ?? null,
    bestBaselineWape: best?.wape ?? null,
  };
  const advice = explain({
    decision,
    productName: product.productName,
    pattern: profile.pattern,
    corrections,
    original: originalScore,
    shipped: shippedScore,
    best,
    naiveWape: naive?.wape ?? null,
    seasonalWape: seasonal?.wape ?? null,
    negativeShare,
    gaps,
    overlap,
    confidence,
    replaced,
    models,
  });

  const interval = coverage(
    actual,
    calendar.map((point) => point.lower),
    calendar.map((point) => point.upper),
  );

  return {
    productId: product.productId,
    productName: product.productName,
    category: product.category,
    decision,
    confidence,
    pattern: profile.pattern,
    grain: grainInfo.grain,
    season,
    reasons: advice.reasons,
    improvements: advice.improvements,
    corrections: decision === 'descartar' ? corrections.filter((item) => item.id !== 'reemplazo_proyeccion') : corrections,
    models,
    metrics: metricViews({
      original: originalScore,
      shipped: decision === 'descartar' ? originalScore : shippedScore,
      maseValue: userMase,
      theil: theilU(forecast, actual, naive?.fitted ?? forecast.map(() => null)),
      fvaNaive: raw.fvaNaive,
      fvaSeasonal: fva(originalScore.wape, seasonal?.wape ?? null),
      fvaBest: fva(originalScore.wape, best?.wape ?? null),
      profile,
      seasonalStrength,
      trendStrength,
      grain: grainInfo.grain,
      season,
      periods: calendar.length,
      overlap,
      gaps,
      duplicates: product.duplicateDates ?? 0,
      negativeShare,
      cvForecast: coefficientOfVariation(forecast),
      cvActual: coefficientOfVariation(actual),
      scale: scaleRatio(forecast, actual),
      interval,
      intermittent,
    }),
    raw,
    series,
  };
}

function shouldReplace(input: {
  intermittent: boolean;
  userWape: number | null;
  bestWape: number | null;
  userMase: number | null;
  bestMase: number | null;
  overlap: number;
}): boolean {
  if (input.overlap < 4 || input.bestWape == null || input.userWape == null) return false;
  if (input.intermittent) {
    if (input.userMase == null || input.bestMase == null) return false;
    return input.bestMase + 0.15 < input.userMase && input.userMase > 1.15;
  }
  return input.bestWape <= 0.5 && input.bestWape < input.userWape * 0.85 && input.userWape - input.bestWape >= 0.08;
}

function decide(input: {
  overlap: number;
  gaps: number;
  gapShare: number;
  negativeShare: number;
  duplicateDates: number;
  forecastPoints: number;
  originalWape: number | null;
  shippedWape: number | null;
  biasPct: number | null;
  correlation: number | null;
  intermittent: boolean;
  userMase: number | null;
  best: BaselineFit | null;
  corrections: number;
  brokenMajority: boolean;
}): Decision {
  if (input.forecastPoints === 0) return 'descartar';
  if (input.brokenMajority) return 'descartar';
  if (input.overlap < 4) {
    if (input.overlap === 0 && input.negativeShare <= 0.35 && input.gapShare <= 0.25 && input.forecastPoints >= 4) return 'mantener';
    if (input.negativeShare > 0 || input.gapShare > 0.1 || input.duplicateDates > 0) return 'corregir';
    return input.forecastPoints < 4 ? 'descartar' : 'mantener';
  }
  if (input.intermittent) {
    if ((input.userMase ?? 99) <= 1.2 && input.negativeShare === 0) return input.corrections ? 'corregir' : 'mantener';
    if ((input.best?.wape ?? 99) > 1.2 && (input.userMase ?? 99) > 2) return 'descartar';
    return 'corregir';
  }
  const wape = input.shippedWape;
  const clean = input.negativeShare === 0 && input.gapShare <= 0.1 && Math.abs(input.biasPct ?? 0) <= 0.2;
  if (wape != null && wape <= 0.4 && clean) return input.corrections ? 'corregir' : 'mantener';
  if (wape != null && wape <= 0.55) return input.corrections ? 'corregir' : 'mantener';
  if (input.best && (input.best.wape ?? 1) <= 0.5 && wape != null && wape <= 0.7) return 'corregir';
  if (wape != null && wape > 0.75 && (input.correlation == null || input.correlation < 0.25) && (input.best?.wape ?? 1) > 0.6) {
    return 'descartar';
  }
  if (wape != null && wape > 0.85) return 'descartar';
  return 'corregir';
}

function confidenceOf(overlap: number, pattern: ProductReport['pattern'], decision: Decision): Confidence {
  if (overlap === 0 || decision === 'descartar' && overlap < 6) return 'baja';
  if (overlap >= 12 && pattern !== 'intermitente' && pattern !== 'irregular' && pattern !== 'insuficiente') return 'alta';
  if (overlap >= 6) return 'media';
  return 'baja';
}

function buildCalendar(points: CanonicalPoint[]): Array<CanonicalPoint & { inserted: boolean }> {
  const grain = inferGrain(points.map((point) => point.date));
  const byDate = new Map(points.map((point) => [point.date.slice(0, 10), point]));
  const expected = expectedDates([...byDate.keys()], grain.grain);
  const dates = expected.length >= byDate.size ? expected : [...byDate.keys()].sort();
  return dates.map((date) => {
    const found = byDate.get(date) ?? closest(byDate, date, grain.grain);
    if (found && found.date.slice(0, 10) === date) return { ...found, date, inserted: false };
    return { date, forecast: null, actual: null, lower: null, upper: null, inserted: true };
  });
}

function closest(byDate: Map<string, CanonicalPoint>, date: string, grain: ProductReport['grain']): CanonicalPoint | null {
  if (grain !== 'mensual' && grain !== 'trimestral') return null;
  const key = date.slice(0, 7);
  for (const [candidate, point] of byDate) {
    if (candidate.slice(0, 7) === key) return { ...point, date };
  }
  return null;
}

function fillForecastGaps(
  calendar: Array<CanonicalPoint & { inserted: boolean }>,
  values: Array<number | null>,
  season: number,
): { values: Array<number | null>; filled: boolean; correction: Correction } {
  const next = values.slice();
  let filled = 0;
  for (let pass = 0; pass < 2; pass += 1) {
    for (let index = 0; index < next.length; index += 1) {
      if (next[index] != null || !calendar[index].inserted) continue;
      const seasonal = index >= season ? next[index - season] : null;
      const previous = [...next.slice(0, index)].reverse().find(finite) ?? null;
      const following = next.slice(index + 1).find(finite) ?? null;
      const replacement = finite(seasonal)
        ? seasonal
        : finite(previous) && finite(following)
          ? ((previous as number) + (following as number)) / 2
          : finite(previous)
            ? previous
            : following;
      if (finite(replacement)) {
        next[index] = replacement as number;
        filled += 1;
      }
    }
  }
  return {
    values: next,
    filled: filled > 0,
    correction: {
      id: 'llenar_huecos',
      detail: `Se completaron ${filled} períodos vacíos con el valor estacional o el vecino más cercano.`,
    },
  };
}

function projectBaseline(
  calendar: Array<CanonicalPoint & { inserted: boolean }>,
  baseline: BaselineFit,
): Array<number | null> {
  const fitted = baseline.fitted;
  let horizon = 0;
  for (let index = calendar.length - 1; index >= 0 && calendar[index].actual == null; index -= 1) horizon += 1;
  const future = baseline.future(Math.max(horizon, 1));
  const futureStart = calendar.length - horizon;
  return calendar.map((_, index) => {
    if (index >= futureStart) return future[index - futureStart] ?? null;
    if (finite(fitted[index])) return fitted[index];
    return null;
  });
}

function toSeriesRow(
  point: CanonicalPoint,
  forecast: number | null,
  corrected: number | null,
  decision: Decision,
  replaced: boolean,
): SeriesRow {
  if (decision === 'descartar') {
    return { date: point.date, actual: point.actual, forecast, corrected: null, origin: 'vacio' };
  }
  const origin = replaced ? 'reemplazo' : corrected !== forecast ? 'ajustado' : 'original';
  return { date: point.date, actual: point.actual, forecast, corrected, origin };
}

function explain(input: {
  decision: Decision;
  productName: string;
  pattern: ProductReport['pattern'];
  corrections: Correction[];
  original: ReturnType<typeof scoreForecast>;
  shipped: ReturnType<typeof scoreForecast>;
  best: BaselineFit | null;
  naiveWape: number | null;
  seasonalWape: number | null;
  negativeShare: number;
  gaps: number;
  overlap: number;
  confidence: Confidence;
  replaced: boolean;
  models: ProductReport['models'];
}): { reasons: string[]; improvements: string[] } {
  const reasons: string[] = [];
  const improvements: string[] = [];
  const wape = input.original.wape;
  if (input.overlap === 0) {
    reasons.push('No hay venta real en las mismas fechas, así que esto es una revisión de forma y no de precisión.');
    improvements.push('Sumá la columna de venta real del mismo grano y las mismas fechas para medir WAPE, sesgo y valor agregado.');
  } else if (input.overlap < 6) {
    reasons.push(`Solo hay ${input.overlap} períodos comparables. La conclusión queda en confianza ${input.confidence}.`);
    improvements.push('Esperá a juntar al menos 6 períodos, idealmente dos ciclos estacionales, antes de cambiar de modelo.');
  }
  if (wape != null) reasons.push(`El WAPE del pronóstico original es ${pct(wape)}.`);
  if (input.original.biasPct != null && Math.abs(input.original.biasPct) >= 0.15) {
    reasons.push(
      input.original.biasPct > 0
        ? `Sobreestima el volumen un ${pct(input.original.biasPct)}.`
        : `Subestima el volumen un ${pct(Math.abs(input.original.biasPct))}.`,
    );
    improvements.push('Revisá el supuesto de crecimiento o el factor comercial. Un sesgo estable se corrige con un multiplicador, no con un modelo nuevo.');
  }
  if (input.naiveWape != null && wape != null) {
    const delta = fva(wape, input.naiveWape);
    if (delta != null && delta < -0.05) {
      reasons.push(`Resta valor contra el naive: ese piso tiene WAPE ${pct(input.naiveWape)}.`);
      improvements.push('Publicá el naive como challenger oficial. Si el proceso no lo gana, el forecast no sale.');
    } else if (delta != null && delta > 0.05) {
      reasons.push(`Mejora al naive en ${pct(delta)} de su error.`);
    }
  }
  if (
    input.best &&
    input.best.wape != null &&
    wape != null &&
    input.best.wape + 0.02 < wape &&
    wape <= 0.4 &&
    !input.replaced
  ) {
    reasons.push(`El método simple más cercano (${input.best.name}) llega a ${pct(input.best.wape)}. La diferencia no cambia la decisión.`);
  }
  if (input.negativeShare > 0) {
    reasons.push(`${pct(input.negativeShare)} de los pronósticos son negativos.`);
    improvements.push('La demanda no se pronostica en negativo. Recortá a cero en el origen y revisá la fórmula que los produce.');
  }
  if (input.gaps > 0) {
    reasons.push(`Faltan ${input.gaps} períodos dentro del calendario.`);
    improvements.push('Completá el calendario antes de medir. Un hueco se lee como exactitud falsa o como quiebre de stock.');
  }
  if (input.pattern === 'intermitente' || input.pattern === 'irregular') {
    reasons.push(`El patrón de demanda es ${input.pattern}.`);
    improvements.push('No uses MAPE ni un modelo continuo. Segmentá estos productos y pronosticalos con Croston, SBA o TSB.');
  }
  if (input.replaced && input.best) {
    reasons.push(`Se descarta el número original y se propone ${input.best.name}, con WAPE de un paso ${pct(input.best.wape)}.`);
  }
  if (input.decision === 'descartar') {
    reasons.push('No hay una corrección defendible. Conviene no publicar número para este producto.');
    improvements.push('Revisá si el código, la unidad y el grano son los mismos en historia y forecast. Si el dato está bien, tratá la serie como excepción manual.');
  } else if (input.decision === 'mantener') {
    reasons.push('El pronóstico se puede usar. Las correcciones automáticas no mejoran lo suficiente como para cambiarlo.');
    improvements.push('Guardá este resultado como línea de base y volvé a medirlo al cierre del período.');
  } else {
    reasons.push('El pronóstico se puede publicar después de las correcciones, no en su forma original.');
  }
  const next = input.models.find((model) => model.role === 'siguiente');
  if (next) improvements.push(`Siguiente modelo a probar para ${input.productName}: ${next.name}. ${next.detail}`);
  const avoid = input.models.find((model) => model.role === 'evitar');
  if (avoid) improvements.push(`Evitá ${avoid.name}. ${avoid.detail}`);
  return { reasons: unique(reasons).slice(0, 6), improvements: unique(improvements).slice(0, 5) };
}

function metricViews(input: {
  original: ReturnType<typeof scoreForecast>;
  shipped: ReturnType<typeof scoreForecast>;
  maseValue: number | null;
  theil: number | null;
  fvaNaive: number | null;
  fvaSeasonal: number | null;
  fvaBest: number | null;
  profile: ReturnType<typeof classifyDemand>;
  seasonalStrength: number | null;
  trendStrength: number | null;
  grain: ProductReport['grain'];
  season: number;
  periods: number;
  overlap: number;
  gaps: number;
  duplicates: number;
  negativeShare: number;
  cvForecast: number | null;
  cvActual: number | null;
  scale: number | null;
  interval: ReturnType<typeof coverage>;
  intermittent: boolean;
}): MetricView[] {
  const o = input.original;
  const toneWape = (value: number | null): MetricView['tone'] => {
    if (value == null) return 'neutro';
    if (input.intermittent) return value <= 1 ? 'ok' : 'warn';
    if (value <= 0.3) return 'ok';
    if (value <= 0.55) return 'warn';
    return 'bad';
  };
  return [
    metric('wape', 'precisión', 'WAPE', pct(o.wape), 'Error absoluto sobre el volumen real. Es la métrica principal.', toneWape(o.wape)),
    metric('wape_corr', 'precisión', 'WAPE corregido', pct(input.shipped.wape), 'El mismo WAPE después de recortes, sesgo o reemplazo.', toneWape(input.shipped.wape)),
    metric('smape', 'precisión', 'sMAPE', pct(o.smape), 'Error simétrico. Tolera mejor los ceros que el MAPE.', toneWape(o.smape)),
    metric('mape', 'precisión', 'MAPE', pct(o.mape), 'Error porcentual promedio. Ignora los períodos con venta cero.', o.mape != null && o.mape > 0.5 ? 'warn' : 'neutro'),
    metric('mdape', 'precisión', 'MdAPE', pct(o.mdape), 'Mediana del error porcentual. No lo dominan uno o dos picos.', 'neutro'),
    metric('mae', 'precisión', 'MAE', num(o.mae), 'Error absoluto medio, en unidades de la serie.', 'neutro'),
    metric('rmse', 'precisión', 'RMSE', num(o.rmse), 'Raíz del error cuadrático. Penaliza más los desvíos grandes.', 'neutro'),
    metric('p50', 'precisión', 'Error absoluto p50', num(o.p50ae), 'La mitad de los períodos se equivocan por menos de este valor.', 'neutro'),
    metric('p90', 'precisión', 'Error absoluto p90', num(o.p90ae), 'Solo uno de cada diez períodos supera este error.', 'neutro'),
    metric('mase', 'precisión', 'MASE', num(input.maseValue), 'MAE dividido por el error del naive estacional. Menor a 1 gana ese piso.', input.maseValue == null ? 'neutro' : input.maseValue > 1 ? 'warn' : 'ok'),
    metric('theil', 'precisión', 'U de Theil', num(input.theil), 'RMSE del forecast dividido por el RMSE del naive. Menor a 1 es mejor que repetir el último valor.', input.theil == null ? 'neutro' : input.theil > 1 ? 'bad' : 'ok'),
    metric('hit10', 'precisión', 'Acierto ±10%', pct(o.hit10), 'Períodos cuyo error porcentual entra en 10%.', 'neutro'),
    metric('hit20', 'precisión', 'Acierto ±20%', pct(o.hit20), 'Períodos cuyo error porcentual entra en 20%.', 'neutro'),
    metric('hit30', 'precisión', 'Acierto ±30%', pct(o.hit30), 'Períodos cuyo error porcentual entra en 30%.', 'neutro'),
    metric('bias', 'sesgo', 'Sesgo medio', num(o.bias), 'Promedio de pronóstico menos real. Positivo es sobreestimar.', toneBias(o.biasPct)),
    metric('bias_pct', 'sesgo', 'Sesgo de volumen', pct(o.biasPct), 'Suma de errores sobre la suma de reales.', toneBias(o.biasPct)),
    metric('mpe', 'sesgo', 'MPE', pct(o.mpe), 'Error porcentual con signo. Un valor positivo repite la sobreestimación.', toneBias(o.mpe)),
    metric('ts', 'sesgo', 'Tracking signal', num(o.trackingSignal), 'Error acumulado dividido por el MAD. Por encima de 4 el sesgo ya no es ruido.', o.trackingSignal != null && Math.abs(o.trackingSignal) > 4 ? 'bad' : 'ok'),
    metric('over', 'sesgo', 'Períodos sobreestimados', pct(o.overRate), 'Parte de los períodos en los que el pronóstico quedó arriba del real.', 'neutro'),
    metric('fva_naive', 'valor', 'FVA contra naive', pct(input.fvaNaive), 'Cuánto del error del naive elimina este forecast. Negativo significa que resta valor.', toneFva(input.fvaNaive)),
    metric('fva_seas', 'valor', 'FVA contra estacional', pct(input.fvaSeasonal), 'La misma cuenta contra repetir la estación anterior.', toneFva(input.fvaSeasonal)),
    metric('fva_best', 'valor', 'FVA contra el mejor simple', pct(input.fvaBest), 'Contra el mejor método simple medido en un paso.', toneFva(input.fvaBest)),
    metric('corr', 'valor', 'Correlación', num(o.correlation), 'Qué tan juntos se mueven pronóstico y real. Cerca de 1 acompañan la forma.', o.correlation != null && o.correlation < 0.2 ? 'bad' : 'neutro'),
    metric('cov', 'valor', 'Cobertura del intervalo', pct(input.interval.coverage), 'Parte de los reales que caen entre el piso y el techo, si vinieron en el archivo.', input.interval.n ? 'neutro' : 'neutro'),
    metric('width', 'valor', 'Ancho medio del intervalo', num(input.interval.meanWidth), 'Promedio de techo menos piso. Un intervalo enorme siempre cubre y no informa.', 'neutro'),
    metric('periods', 'estructura', 'Períodos', String(input.periods), 'Largo del calendario analizado, huecos incluidos.', 'neutro'),
    metric('overlap', 'estructura', 'Períodos comparables', String(input.overlap), 'Fechas donde hay pronóstico y real al mismo tiempo.', input.overlap < 6 ? 'warn' : 'ok'),
    metric('gaps', 'estructura', 'Huecos', String(input.gaps), 'Períodos que faltaban dentro del rango.', input.gaps ? 'warn' : 'ok'),
    metric('dups', 'estructura', 'Fechas duplicadas', String(input.duplicates), 'Filas repetidas del mismo producto y fecha.', input.duplicates ? 'warn' : 'ok'),
    metric('neg', 'estructura', 'Pronósticos negativos', pct(input.negativeShare), 'Parte del forecast por debajo de cero.', input.negativeShare ? 'bad' : 'ok'),
    metric('cv_f', 'estructura', 'CV del pronóstico', num(input.cvForecast), 'Desvío del forecast dividido por su media.', 'neutro'),
    metric('cv_a', 'estructura', 'CV de la venta', num(input.cvActual), 'Desvío de la venta dividido por su media.', 'neutro'),
    metric('scale', 'estructura', 'Escala forecast / real', num(input.scale), 'Relación entre el volumen pronosticado y el real. Lejos de 1 hay un problema de unidades o de sesgo.', input.scale != null && (input.scale < 0.6 || input.scale > 1.5) ? 'warn' : 'ok'),
    metric('pattern', 'patrón', 'Clase de demanda', input.profile.pattern, 'Clasificación de Syntetos-Boylan: suave, errática, intermitente o irregular.', 'neutro'),
    metric('adi', 'patrón', 'ADI', num(input.profile.adi), 'Cada cuántos períodos aparece una venta. Desde 1,32 se trata como intermitente.', 'neutro'),
    metric('cv2', 'patrón', 'CV²', num(input.profile.cv2), 'Variación del tamaño de las ventas no nulas. Desde 0,49 el tamaño es inestable.', 'neutro'),
    metric('zeros', 'patrón', 'Períodos en cero', pct(input.profile.zeroShare), 'Parte de la historia sin venta.', 'neutro'),
    metric('events', 'patrón', 'Eventos de demanda', String(input.profile.demandEvents), 'Cantidad de períodos con venta positiva.', 'neutro'),
    metric('grain', 'patrón', 'Grano', input.grain, 'Frecuencia inferida por la distancia mediana entre fechas.', 'neutro'),
    metric('season', 'patrón', 'Largo de estación', String(input.season), 'Períodos que forman un ciclo: 7, 12, 52 o 4 según el grano.', 'neutro'),
    metric('seas', 'patrón', 'Fuerza estacional', num(input.seasonalStrength), 'Autocorrelación en el lag de la estación. Desde 0,35 conviene un modelo estacional.', 'neutro'),
    metric('trend', 'patrón', 'Fuerza de tendencia', num(input.trendStrength), 'Correlación absoluta de la serie con el tiempo.', 'neutro'),
  ];
}

function metric(
  id: string,
  group: MetricView['group'],
  label: string,
  value: string,
  help: string,
  tone: MetricView['tone'],
): MetricView {
  return { id, group, label, value, help, tone };
}

function processNotes(reports: ProductReport[]): string[] {
  const notes: string[] = [];
  const discarded = reports.filter((report) => report.decision === 'descartar');
  const biased = reports.filter((report) => report.raw.biasPct != null && Math.abs(report.raw.biasPct) > 0.2);
  const intermittent = reports.filter((report) => report.pattern === 'intermitente' || report.pattern === 'irregular');
  const noActual = reports.filter((report) => report.raw.overlap === 0);
  if (discarded.length) notes.push(`${discarded.length} producto(s) no deberían llevar número hasta corregir el dato o la serie.`);
  if (biased.length) notes.push(`${biased.length} producto(s) tienen sesgo de volumen mayor a 20%. Eso suele ser un supuesto comercial, no un problema de algoritmo.`);
  if (intermittent.length) notes.push(`${intermittent.length} producto(s) son intermitentes o irregulares. Separalos del modelo que uses para los productos de demanda continua.`);
  if (noActual.length) notes.push(`${noActual.length} producto(s) llegaron sin venta real. Esos resultados no miden precisión.`);
  notes.push('Medí siempre contra naive y naive estacional. Un modelo nuevo tiene que ganarles en WAPE y en sesgo, no solo en el promedio de un backtest.');
  notes.push('Congelá el horizonte y la foto de historia antes de comparar. Si no, el forecast se reescribe con datos que todavía no existían.');
  return notes;
}

function volumeOf(report: ProductReport): number {
  return report.series.reduce((sum, row) => sum + (finite(row.actual) ? Math.abs(row.actual as number) : 0), 0);
}

function weightedWape(reports: ProductReport[], key: 'wape' | 'wapeCorrected', volume: number): number | null {
  if (volume <= 0) return null;
  let acc = 0;
  let used = 0;
  for (const report of reports) {
    const value = report.raw[key];
    const weight = volumeOf(report);
    if (value == null || weight === 0) continue;
    acc += value * weight;
    used += weight;
  }
  return used ? acc / used : null;
}

function share(values: Array<number | null>, predicate: (value: number) => boolean): number {
  const clean = values.filter(finite) as number[];
  if (!clean.length) return 0;
  return clean.filter(predicate).length / clean.length;
}

function scaleRatio(forecast: Array<number | null>, actual: Array<number | null>): number | null {
  let sumF = 0;
  let sumA = 0;
  for (let i = 0; i < Math.min(forecast.length, actual.length); i += 1) {
    if (finite(forecast[i]) && finite(actual[i])) {
      sumF += Math.abs(forecast[i] as number);
      sumA += Math.abs(actual[i] as number);
    }
  }
  if (sumA === 0) return null;
  return sumF / sumA;
}

function pct(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('es-AR', { style: 'percent', maximumFractionDigits: 1 }).format(value);
}

function num(value: number | null): string {
  if (value == null) return '—';
  if (!Number.isFinite(value)) return '∞';
  return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 }).format(value);
}

function toneBias(value: number | null): MetricView['tone'] {
  if (value == null) return 'neutro';
  if (Math.abs(value) <= 0.1) return 'ok';
  if (Math.abs(value) <= 0.2) return 'warn';
  return 'bad';
}

function toneFva(value: number | null): MetricView['tone'] {
  if (value == null) return 'neutro';
  if (value >= 0.05) return 'ok';
  if (value >= -0.05) return 'warn';
  return 'bad';
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
