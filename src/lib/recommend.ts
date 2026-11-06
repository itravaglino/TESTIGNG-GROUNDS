import type { BaselineFit } from './baselines';
import type { Grain, ModelCard, Pattern } from './types';

export function recommendModels(input: {
  pattern: Pattern;
  grain: Grain;
  season: number;
  history: number;
  seasonalStrength: number | null;
  trendStrength: number | null;
  baselines: BaselineFit[];
}): ModelCard[] {
  const cards: ModelCard[] = [];
  const best = input.baselines[0];
  if (best) {
    cards.push({
      role: 'usar_ahora',
      name: best.name,
      detail: 'Es el método simple con menor WAPE de un paso sobre el histórico. Sirve como piso: un forecast que no lo mejora resta valor.',
      wape: best.wape,
    });
  } else {
    cards.push({
      role: 'usar_ahora',
      name: 'Naive',
      detail: 'No hay historia suficiente para ajustar otra cosa. Repetí el último período observado.',
      wape: null,
    });
  }

  const advanced = advancedOption(input);
  if (advanced && advanced.name !== best?.name) cards.push({ role: 'siguiente', ...advanced, wape: null });
  for (const extra of extraOptions(input)) {
    if (cards.some((card) => card.name === extra.name)) continue;
    cards.push({ role: 'siguiente', ...extra, wape: null });
  }
  for (const avoid of avoided(input)) cards.push({ role: 'evitar', ...avoid, wape: null });
  return cards.slice(0, 6);
}

function advancedOption(input: {
  pattern: Pattern;
  season: number;
  history: number;
  seasonalStrength: number | null;
  trendStrength: number | null;
}): { name: string; detail: string } | null {
  const seasonal = (input.seasonalStrength ?? 0) >= 0.35 && input.history >= input.season * 2;
  if (input.pattern === 'intermitente') {
    return { name: 'Croston o SBA', detail: 'La demanda aparece de a saltos y el tamaño es parejo. Croston separa cada cuánto se vende y de a cuánto.' };
  }
  if (input.pattern === 'irregular') {
    return { name: 'TSB o modelo de dos partes', detail: 'Hay pocos eventos y el tamaño varía mucho. TSB actualiza también la probabilidad de que haya venta, no solo el tamaño.' };
  }
  if (input.pattern === 'insuficiente' || input.history < 8) {
    return { name: 'Naive o análogo de categoría', detail: 'Con esta historia un modelo grande memoriza ruido. Usá el último valor o el patrón de un producto parecido.' };
  }
  if (seasonal && (input.trendStrength ?? 0) >= 0.35) {
    return { name: 'Holt-Winters o Prophet', detail: 'Hay tendencia y estacionalidad repetida. Holt-Winters alcanza si la serie es una; Prophet ayuda cuando hay feriados que se mueven.' };
  }
  if (seasonal) {
    return { name: 'Holt-Winters aditivo', detail: `La serie se parece a sí misma cada ${input.season} períodos. Un estacional explícito debería ganarle a un promedio.` };
  }
  if ((input.trendStrength ?? 0) >= 0.4) {
    return { name: 'Holt con tendencia amortiguada', detail: 'La serie sube o baja de forma persistente. Amortiguá la tendencia para que el horizonte largo no se dispare.' };
  }
  if (input.pattern === 'errática') {
    return { name: 'Ensemble simple', detail: 'El tamaño cambia sin un ciclo claro. Promediá naive, media móvil y suavizado en vez de confiar en un solo modelo.' };
  }
  return { name: 'Suavizado exponencial', detail: 'La demanda es continua y sin un ciclo fuerte. SES es estable y fácil de explicar.' };
}

function extraOptions(input: { pattern: Pattern; history: number }): Array<{ name: string; detail: string }> {
  if (input.history >= 36 && (input.pattern === 'suave' || input.pattern === 'errática')) {
    return [{
      name: 'LightGBM con rezagos',
      detail: 'Recién con esta cantidad de historia, y mejor si hay muchas series parecidas, un modelo de árboles con lags, precio y promo puede sumar.',
    }];
  }
  if (input.history >= 80 && input.pattern === 'suave') {
    return [{
      name: 'TFT o N-BEATS',
      detail: 'Un modelo profundo se justifica con historia larga y un catálogo grande. En una sola serie corta no vale el costo.',
    }];
  }
  return [];
}

function avoided(input: { pattern: Pattern; history: number }): Array<{ name: string; detail: string }> {
  const items: Array<{ name: string; detail: string }> = [];
  if (input.pattern === 'intermitente' || input.pattern === 'irregular') {
    items.push({ name: 'Prophet o Holt-Winters', detail: 'Estos modelos esperan una demanda continua. En series con muchos ceros inventan estacionalidad.' });
    items.push({ name: 'Optimizar solo MAPE', detail: 'MAPE explota o se indefine cuando la venta es cero. Medí WAPE, MASE y sesgo.' });
  }
  if (input.history < 30) {
    items.push({ name: 'Red neuronal o AutoARIMA ciego', detail: 'Con poca historia el backtest se ve bien y el mes siguiente se desarma. Quedate en métodos que se pueden explicar en una reunión.' });
  }
  return items.slice(0, 2);
}
