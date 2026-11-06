import type { Flag, MetricValue, SeriesFeatures, Tip } from "./types";
import { metricMap } from "./metrics";

export function tipsFor(features: SeriesFeatures, flags: Flag[], metrics: MetricValue[]): Tip[] {
  const m = metricMap(metrics);
  const tips: Tip[] = [];
  const wape = m.wape;
  const pbias = m.pbias;
  const mape = m.mape;

  if (features.demandClass === "intermittent" || features.demandClass === "lumpy") {
    tips.push({
      id: "intermittent",
      title: "Deje de rankear este SKU por MAPE",
      body: "Recalcule el error con MASE y WAPE. Separe tamaño de pedido y probabilidad de ocurrencia. Pruebe SBA; TSB si hay riesgo de obsolescencia.",
    });
  }
  if (pbias != null && pbias > 10) {
    tips.push({
      id: "over",
      title: "Corrija el sobrepronóstico antes de cambiar de modelo",
      body: "Aplique un factor = media(real) / media(pronóstico) acotado si el sesgo es estable. Revise que el stock de seguridad no esté duplicado dentro del pronóstico.",
    });
  }
  if (pbias != null && pbias < -10) {
    tips.push({
      id: "under",
      title: "Hay subpronóstico sistemático",
      body: "Marque quiebres como censura y no los use como demanda. Si el nivel subió y se mantiene, reinicie el nivel del modelo.",
    });
  }
  if (features.seasonal && flags.some((f) => f.id === "FLAT_01")) {
    tips.push({
      id: "season",
      title: "Falta estacionalidad en el modelo",
      body: "Exija un ingenuo estacional antes de cualquier modelo avanzado. Holt-Winters aditivo si el pico es estable; multiplicativo si crece con el nivel.",
    });
  }
  if (flags.some((f) => f.id === "OUT_01")) {
    tips.push({
      id: "outlier",
      title: "Separe picos de la demanda base",
      body: "Winsorice o quite el outlier del entrenamiento y guarde el dato crudo. Si el pico es promo, sume el uplift solo cuando el calendario futuro lo confirme.",
    });
  }
  if (flags.some((f) => f.id === "SHORT_01") || features.n < 8) {
    tips.push({
      id: "new",
      title: "SKU con historia corta: use análogos",
      body: "Elija 3–5 análogos por marca, formato, precio y canal. Escale el perfil de lanzamiento. A las 8–12 semanas mezcle historia propia.",
    });
  }
  if (features.cv != null && features.cv > 0.8 && features.n >= 8) {
    tips.push({
      id: "grain",
      title: "Demasiado ruido en el bucket actual",
      body: "Pronostique al bucket de decisión (a menudo mensual). Desagregue a semana solo con un perfil fijo si la ejecución lo exige.",
    });
  }
  if (flags.some((f) => f.id === "LEAK_01")) {
    tips.push({
      id: "leak",
      title: "Esto no es un pronóstico independiente",
      body: "Vuelva a publicar una línea base estadística. El presupuesto o la venta copiada no reemplazan un baseline.",
    });
  }
  if (flags.some((f) => f.id === "TRD_01")) {
    tips.push({
      id: "trend",
      title: "Incorpore tendencia amortiguada",
      body: "Compare ingenuo, SES y Holt amortiguado en el horizonte de compra. Una tendencia lineal a 12 meses suele sobrepasar.",
    });
  }
  if (m.tracking_signal != null && Math.abs(m.tracking_signal) > 4 && Math.abs(pbias ?? 0) > 10) {
    tips.push({
      id: "ts",
      title: "La señal de rastreo está fuera de control",
      body: "El sesgo no es un mes suelto. Recalibre el nivel o retire overrides que siempre suman el mismo signo.",
    });
  }
  if (wape != null && wape > 30 && features.demandClass === "smooth") {
    tips.push({
      id: "bakeoff",
      title: "Haga un torneo corto de modelos",
      body: "Ingenuo, ingenuo estacional, SES, Holt amortiguado y Holt-Winters, con origen rodante al lead time. Gana el más simple que no pierda.",
    });
  }
  if (mape != null && mape > 40 && (features.zerosShare ?? 0) > 0.3) {
    tips.push({
      id: "mape_trap",
      title: "El MAPE alto es una trampa de ceros",
      body: "No cambie el modelo solo porque el MAPE explota. Mire MASE y el sesgo de nivel.",
    });
  }
  if (!tips.length) {
    tips.push({
      id: "keep",
      title: "Mantenga el modelo y vigile el sesgo",
      body: "El pronóstico está dentro de umbrales operables. Reevalúe cada trimestre, no cada semana, y mida en el horizonte de compra.",
    });
  }
  return tips.slice(0, 6);
}
