import { percentile } from "./metrics";
import type {
  AccuracyMetrics,
  CanonicalRow,
  ForecastIssue,
  QualityGates,
  SeriesProfile,
} from "./types";

function issue(
  partial: Omit<ForecastIssue, "howToFix"> & { howToFix: string },
): ForecastIssue {
  return partial;
}

export function detectIssues(
  productId: string,
  rows: CanonicalRow[],
  profile: SeriesProfile,
  metrics: AccuracyMetrics,
  gates: QualityGates,
): ForecastIssue[] {
  const out: ForecastIssue[] = [];
  const ordered = [...rows].sort((a, b) => a.timestamp - b.timestamp);
  const keyCount = new Map<string, CanonicalRow[]>();

  for (const row of ordered) {
    if (!Number.isFinite(row.timestamp)) {
      out.push(
        issue({
          code: "UNPARSEABLE_DATE",
          severity: "error",
          productId,
          date: row.date,
          line: row.line,
          message: `Fecha ilegible en la línea ${row.line}: ${row.date}`,
          howToFix: "Use AAAA-MM-DD, DD/MM/AAAA o un serial de Excel.",
        }),
      );
    }
    if (!Number.isFinite(row.forecast)) {
      out.push(
        issue({
          code: "UNPARSEABLE_NUMBER",
          severity: "critical",
          productId,
          date: row.date,
          line: row.line,
          message: `Pronóstico no numérico en la línea ${row.line}`,
          howToFix: "Deje el forecast como número. Evite texto, NA o celdas mezcladas.",
        }),
      );
    } else if (row.forecast < 0) {
      out.push(
        issue({
          code: "NEGATIVE_FORECAST",
          severity: "error",
          productId,
          date: row.date,
          line: row.line,
          message: `Pronóstico negativo (${row.forecast}) el ${row.date}`,
          howToFix: "Para demanda, recorte a cero o use un modelo que no produzca negativos (Croston/TSB o una función de enlace log).",
          value: row.forecast,
        }),
      );
    }
    if (row.actual !== null && row.actual < 0) {
      out.push(
        issue({
          code: "NEGATIVE_ACTUAL",
          severity: "warn",
          productId,
          date: row.date,
          line: row.line,
          message: `Real negativo (${row.actual}) el ${row.date}`,
          howToFix: "Revise devoluciones y ajustes. Si la demanda neta no puede ser negativa, recorte a cero antes de entrenar.",
          value: row.actual,
        }),
      );
    }
    if (row.lower !== null && row.upper !== null && row.lower > row.upper) {
      out.push(
        issue({
          code: "INTERVAL_VIOLATION",
          severity: "error",
          productId,
          date: row.date,
          line: row.line,
          message: `Intervalo invertido el ${row.date}: inferior ${row.lower} > superior ${row.upper}`,
          howToFix: "Recalibre cuantiles. El inferior debe ser menor o igual que el superior.",
        }),
      );
    }
    const key = `${row.date}|${row.location ?? ""}|${row.channel ?? ""}|${row.horizon ?? ""}`;
    const bucket = keyCount.get(key) ?? [];
    bucket.push(row);
    keyCount.set(key, bucket);
  }

  for (const [key, group] of keyCount) {
    if (group.length > 1) {
      out.push(
        issue({
          code: "DUPLICATE_KEY",
          severity: "error",
          productId,
          date: group[0].date,
          line: group[0].line,
          message: `${group.length} filas duplicadas para ${key.replace(/\|/g, " / ")}`,
          howToFix: "Conserve la última emisión del pronóstico y elimine versiones anteriores.",
        }),
      );
    }
  }

  if (profile.n < gates.minPoints) {
    out.push(
      issue({
        code: "TOO_SHORT",
        severity: "critical",
        productId,
        date: null,
        line: null,
        message: `Solo ${profile.n} periodos (mínimo ${gates.minPoints})`,
        howToFix: "Junte historia, baje la granularidad o use un modelo global (Chronos, TimesFM) en vez de un modelo univariado.",
        value: profile.n,
        threshold: gates.minPoints,
      }),
    );
  }

  if (profile.n >= 3 && profile.stdForecast === 0) {
    out.push(
      issue({
        code: "CONSTANT_FORECAST",
        severity: "error",
        productId,
        date: null,
        line: null,
        message: "El pronóstico es constante en toda la serie",
        howToFix: "Eso suele ser una media fija o un naive mal aplicado. Cambie a SES, Croston o un modelo con estacionalidad.",
      }),
    );
  }

  if (profile.zeroForecastShare === 1 || (profile.meanForecast === 0 && profile.n > 0)) {
    out.push(
      issue({
        code: "ALL_ZERO",
        severity: "critical",
        productId,
        date: null,
        line: null,
        message: "Todos los pronósticos son cero",
        howToFix: "Revise el pipeline: unidad, filtro de SKU o un modelo que colapsó a cero.",
      }),
    );
  }

  const finite = ordered.filter((r) => Number.isFinite(r.timestamp));
  if (finite.length >= 3) {
    const diffs: number[] = [];
    for (let i = 1; i < finite.length; i++) diffs.push(finite[i].timestamp - finite[i - 1].timestamp);
    const med = [...diffs].sort((a, b) => a - b)[Math.floor(diffs.length / 2)];
    if (med > 0) {
      for (let i = 1; i < finite.length; i++) {
        if (finite[i].timestamp - finite[i - 1].timestamp > med * 1.6) {
          out.push(
            issue({
              code: "GAP_IN_SERIES",
              severity: "warn",
              productId,
              date: finite[i].date,
              line: finite[i].line,
              message: `Hueco en el calendario entre ${finite[i - 1].date} y ${finite[i].date}`,
              howToFix: "Complete periodos faltantes (cero si no hubo venta, interpolación solo para el forecast).",
            }),
          );
        }
      }
    }
  }

  const fcst = ordered.map((r) => r.forecast).filter(Number.isFinite);
  if (fcst.length >= 8) {
    const med = percentile(fcst, 50) ?? 0;
    const q1 = percentile(fcst, 25) ?? med;
    const q3 = percentile(fcst, 75) ?? med;
    const iqr = q3 - q1 || Math.abs(med) * 0.1 || 1;
    const mean = fcst.reduce((a, b) => a + b, 0) / fcst.length;
    const sd = Math.sqrt(fcst.reduce((s, x) => s + (x - mean) ** 2, 0) / fcst.length) || 1;
    for (const row of ordered) {
      if (!Number.isFinite(row.forecast)) continue;
      const z = Math.abs(row.forecast - mean) / sd;
      if (z >= gates.spikeZ || row.forecast > q3 + 3 * iqr) {
        out.push(
          issue({
            code: "SPIKE",
            severity: "warn",
            productId,
            date: row.date,
            line: row.line,
            message: `Pico de pronóstico ${row.forecast.toFixed(1)} el ${row.date}`,
            howToFix: "Winsorice, separe promociones o use un modelo con regresores de evento.",
            value: row.forecast,
          }),
        );
      }
      if (med > 0 && row.forecast / med >= gates.scaleShiftRatio) {
        out.push(
          issue({
            code: "SCALE_SHIFT",
            severity: "critical",
            productId,
            date: row.date,
            line: row.line,
            message: `Cambio de escala: forecast ${row.forecast} vs mediana ${med.toFixed(1)}`,
            howToFix: "Revise unidades (unidades vs miles), tipo de dato y joins. No use esta fila en operación.",
            value: row.forecast / med,
            threshold: gates.scaleShiftRatio,
          }),
        );
      }
    }
  }

  if (
    profile.meanActual !== null &&
    profile.meanActual > 0 &&
    profile.meanForecast / profile.meanActual >= gates.scaleShiftRatio
  ) {
    out.push(
      issue({
        code: "SCALE_SHIFT",
        severity: "critical",
        productId,
        date: null,
        line: null,
        message: `El pronóstico está ×${(profile.meanForecast / profile.meanActual).toFixed(0)} respecto del real (unidades o miles)`,
        howToFix: "Unifique la unidad (piezas vs miles) o rescalé con media(real)/media(forecast).",
        value: profile.meanForecast / profile.meanActual,
        threshold: gates.scaleShiftRatio,
      }),
    );
  }

  if (metrics.mape !== null && metrics.mape >= gates.mapeFail) {
    out.push(
      issue({
        code: "HIGH_MAPE",
        severity: "error",
        productId,
        date: null,
        line: null,
        message: `MAPE ${metrics.mape.toFixed(1)}% por encima del umbral ${gates.mapeFail}%`,
        howToFix: "Pruebe otro modelo según la clase de demanda, agregue regresores y recorte outliers del entrenamiento.",
        metric: "MAPE",
        value: metrics.mape,
        threshold: gates.mapeFail,
      }),
    );
  } else if (metrics.mape !== null && metrics.mape >= gates.mapeWarn) {
    out.push(
      issue({
        code: "HIGH_MAPE",
        severity: "warn",
        productId,
        date: null,
        line: null,
        message: `MAPE ${metrics.mape.toFixed(1)}% en zona de alerta`,
        howToFix: "Revise sesgo y estacionalidad antes de llevar el SKU a abastecimiento automático.",
        metric: "MAPE",
        value: metrics.mape,
        threshold: gates.mapeWarn,
      }),
    );
  }

  if (metrics.wape !== null && metrics.wape >= gates.wapeFail) {
    out.push(
      issue({
        code: "HIGH_WAPE",
        severity: "error",
        productId,
        date: null,
        line: null,
        message: `WAPE ${metrics.wape.toFixed(1)}% por encima del umbral ${gates.wapeFail}%`,
        howToFix: "El WAPE pesa volumen: concentre el esfuerzo en picos y en el modelo de intermitencia.",
        metric: "WAPE",
        value: metrics.wape,
        threshold: gates.wapeFail,
      }),
    );
  } else if (metrics.wape !== null && metrics.wape >= gates.wapeWarn) {
    out.push(
      issue({
        code: "HIGH_WAPE",
        severity: "warn",
        productId,
        date: null,
        line: null,
        message: `WAPE ${metrics.wape.toFixed(1)}% en zona de alerta`,
        howToFix: "Compare contra naive estacional (MASE). Si MASE > 1, el modelo no agrega valor.",
        metric: "WAPE",
        value: metrics.wape,
        threshold: gates.wapeWarn,
      }),
    );
  }

  if (metrics.trackingSignal !== null && Math.abs(metrics.trackingSignal) >= gates.trackingSignalFail) {
    out.push(
      issue({
        code: "TRACKING_SIGNAL",
        severity: "error",
        productId,
        date: null,
        line: null,
        message: `Señal de seguimiento ${metrics.trackingSignal.toFixed(2)} (límite ±${gates.trackingSignalFail})`,
        howToFix: "Hay sesgo acumulado. Recalibre el nivel, use Holt amortiguado o un factor de sesgo multiplicativo.",
        metric: "trackingSignal",
        value: metrics.trackingSignal,
        threshold: gates.trackingSignalFail,
      }),
    );
  }

  if (metrics.biasPct !== null && Math.abs(metrics.biasPct) >= 15) {
    out.push(
      issue({
        code: "BIAS_SYSTEMATIC",
        severity: Math.abs(metrics.biasPct) >= 30 ? "error" : "warn",
        productId,
        date: null,
        line: null,
        message: `Sesgo de volumen ${metrics.biasPct.toFixed(1)}%`,
        howToFix: "Multiplique el forecast por media(real)/media(forecast) o cambie a un modelo con tendencia amortiguada.",
        metric: "biasPct",
        value: metrics.biasPct,
      }),
    );
  }

  if (metrics.coverage !== null && metrics.coverage < gates.coverageMin) {
    out.push(
      issue({
        code: "LOW_COVERAGE",
        severity: "warn",
        productId,
        date: null,
        line: null,
        message: `Cobertura de intervalo ${metrics.coverage.toFixed(1)}% (objetivo ≥ ${gates.coverageMin}%)`,
        howToFix: "Ensanche los cuantiles o estime intervalos por conformal prediction / quantile regression.",
        metric: "coverage",
        value: metrics.coverage,
        threshold: gates.coverageMin,
      }),
    );
  }

  if (metrics.meanIntervalWidth !== null && profile.meanForecast > 0) {
    const rel = metrics.meanIntervalWidth / profile.meanForecast;
    if (rel < 0.05) {
      out.push(
        issue({
          code: "INTERVAL_TOO_NARROW",
          severity: "warn",
          productId,
          date: null,
          line: null,
          message: "Intervalos demasiado estrechos respecto al nivel de la serie",
          howToFix: "El modelo está sobreconfiado. Use residuales históricos para calibrar.",
        }),
      );
    }
    if (rel > 3) {
      out.push(
        issue({
          code: "INTERVAL_TOO_WIDE",
          severity: "info",
          productId,
          date: null,
          line: null,
          message: "Intervalos muy anchos: poco útiles para stock",
          howToFix: "Agregue regresores o baje a un horizonte más corto.",
        }),
      );
    }
  }

  if (
    (profile.demandClass === "intermittent" || profile.demandClass === "lumpy") &&
    profile.modelsUsed.some((m) => /ses|holt|prophet|arima|ets/i.test(m))
  ) {
    out.push(
      issue({
        code: "INTERMITTENT_MISMATCH",
        severity: "error",
        productId,
        date: null,
        line: null,
        message: `Demanda ${profile.demandClass} modelada con ${profile.modelsUsed.join(", ")}`,
        howToFix: "Pase a Croston, TSB o SBA. Prophet/Holt-Winters se rompen con muchos ceros.",
      }),
    );
  }

  if (profile.trend === "explosive") {
    out.push(
      issue({
        code: "TREND_EXPLOSION",
        severity: "critical",
        productId,
        date: null,
        line: null,
        message: "Tendencia explosiva en el pronóstico",
        howToFix: "Use Holt amortiguado, techos de negocio o un modelo en log. Descarte el tramo explosivo.",
      }),
    );
  }

  if ((profile.seasonalStrength ?? 0) > 0.35 && profile.modelsUsed.some((m) => /ses|naive|croston/i.test(m))) {
    out.push(
      issue({
        code: "SEASONALITY_IGNORED",
        severity: "warn",
        productId,
        date: null,
        line: null,
        message: "Hay estacionalidad y el modelo declarado no la captura",
        howToFix: "Holt-Winters, SARIMA, TBATS, Prophet o features de calendario en LightGBM.",
      }),
    );
  }

  if ((profile.cvActual ?? 0) > 1.2) {
    out.push(
      issue({
        code: "DEMAND_CV_HIGH",
        severity: "info",
        productId,
        date: null,
        line: null,
        message: `CV de la demanda ${(profile.cvActual ?? 0).toFixed(2)}: serie ruidosa`,
        howToFix: "Agregue a semana/mes, separe promociones y evalúe con WAPE/MASE, no con MAPE.",
      }),
    );
  }

  const horizons = new Set(ordered.map((r) => r.horizon).filter((h): h is number => h !== null));
  if (horizons.size > 3) {
    out.push(
      issue({
        code: "HORIZON_INCONSISTENT",
        severity: "info",
        productId,
        date: null,
        line: null,
        message: `Se mezclan ${horizons.size} horizontes en la misma serie`,
        howToFix: "Evalúe cada horizonte por separado. Un h=1 no es comparable con un h=12.",
      }),
    );
  }

  return out;
}
