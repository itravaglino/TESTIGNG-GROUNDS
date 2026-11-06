import type { ForecastPoint, Issue, SeriesProfile } from "./types";
import { fillDateGrid, mean, sortPoints, stdev } from "./profile";

function issue(
  code: string,
  severity: Issue["severity"],
  title: string,
  detail: string,
  howToFix: string,
  affectedDates?: string[],
): Issue {
  return { code, severity, title, detail, howToFix, affectedDates };
}

export function diagnoseSeries(points: ForecastPoint[], profile: SeriesProfile): Issue[] {
  const s = sortPoints(points);
  const issues: Issue[] = [];
  if (s.length === 0) {
    return [issue("empty", "fatal", "Serie vacía", "No hay puntos de pronóstico.", "Revisar el SKU en el archivo origen.")];
  }

  const negatives = s.filter((p) => p.forecast < 0);
  if (negatives.length) {
    issues.push(issue(
      "negative",
      "error",
      "Pronósticos negativos",
      `${negatives.length} período(s) con demanda negativa.`,
      "Recortar a 0 o usar un modelo con soporte no negativo (Croston, log-link, ReLU).",
      negatives.map((p) => p.isoDate),
    ));
  }

  const bad = s.filter((p) => !Number.isFinite(p.forecast));
  if (bad.length) {
    issues.push(issue(
      "nan",
      "fatal",
      "Valores no numéricos",
      `${bad.length} pronóstico(s) NaN/Inf.`,
      "Eliminar o interpolar esos períodos antes de planificar.",
      bad.map((p) => p.isoDate),
    ));
  }

  const byDate = new Map<string, number>();
  for (const p of s) byDate.set(p.isoDate, (byDate.get(p.isoDate) ?? 0) + 1);
  const dups = [...byDate.entries()].filter(([, n]) => n > 1).map(([d]) => d);
  if (dups.length) {
    issues.push(issue("duplicate", "error", "Fechas duplicadas", `${dups.length} fecha(s) repetida(s).`, "Agregar por fecha (promedio o suma según el grano).", dups));
  }

  let unsorted = false;
  for (let i = 1; i < points.length; i++) {
    if (points[i].date.getTime() < points[i - 1].date.getTime()) unsorted = true;
  }
  if (unsorted) {
    issues.push(issue("unsorted", "info", "Serie desordenada", "Las fechas no vienen cronológicas.", "Ordenar por fecha. El sistema lo hace al corregir."));
  }

  if (profile.cadence !== "irregular" && s.length >= 3) {
    const grid = fillDateGrid(s[0].date, s[s.length - 1].date, profile.stepDays);
    const have = new Set(s.map((p) => p.isoDate));
    const missing = grid.filter((d) => !have.has(d));
    if (missing.length / grid.length > 0.08) {
      issues.push(issue(
        "gaps",
        "warn",
        "Huecos en el calendario",
        `Faltan ${missing.length} de ${grid.length} períodos (${profile.cadence}).`,
        "Completar con interpolación o naive estacional; no dejar semanas mudas en el MRP.",
        missing.slice(0, 12),
      ));
    }
  }

  if (s.length < 8) {
    issues.push(issue(
      "short",
      s.length < 4 ? "fatal" : "error",
      "Historia demasiado corta",
      `Solo ${s.length} puntos. No alcanza para validar estacionalidad.`,
      "Usar productos análogos, prior + SES, o esperar más historia antes de un modelo complejo.",
    ));
  }

  if (s.every((p) => p.forecast === 0)) {
    issues.push(issue("all_zero_fcst", "fatal", "Pronóstico todo en cero", "El modelo no genera demanda.", "Descartar y reemplazar por Croston/TSB o un mínimo de seguridad."));
  }

  const actuals = s.filter((p) => p.actual !== undefined);
  if (actuals.length && actuals.every((p) => p.actual === 0) && mean(s.map((p) => p.forecast)) > 1) {
    issues.push(issue("zero_actual_high_fcst", "fatal", "Real en cero y pronóstico alto", "No hay ventas y el forecast pide stock.", "Confirmar delist / quiebre de datos. No planificar con esta serie."));
  }

  const f = s.map((p) => p.forecast);
  const fStd = stdev(f);
  const a = actuals.map((p) => p.actual as number);
  if (fStd < 1e-6 && a.length >= 8 && stdev(a) > 1e-3) {
    issues.push(issue(
      "constant",
      "error",
      "Pronóstico constante",
      `ŷ no varía (σ=${fStd.toFixed(4)}) mientras la demanda real sí.`,
      "Incorporar estacionalidad, promociones y un modelo con tendencia (Holt-Winters o boosting con lags).",
    ));
  }

  if (s.length >= 8) {
    const q = [...f].sort((x, y) => x - y);
    const q1 = q[Math.floor(q.length * 0.25)];
    const q3 = q[Math.floor(q.length * 0.75)];
    const iqr = q3 - q1;
    const spikes = s.filter((p) => p.forecast > q3 + 3 * iqr || p.forecast < q1 - 3 * iqr);
    if (iqr > 0 && spikes.length) {
      issues.push(issue(
        "spikes",
        "warn",
        "Picos anómalos en el forecast",
        `${spikes.length} punto(s) fuera de 3×IQR.`,
        "Winsorizar, revisar promociones/feriados, o usar pérdida Huber / modelos robustos.",
        spikes.map((p) => p.isoDate),
      ));
    }
  }

  if (actuals.length >= 8) {
    const meanA = mean(a);
    const meanF = mean(f);
    if (meanA > 0 && (meanF / meanA > 8 || meanA / Math.max(meanF, 1e-9) > 8)) {
      issues.push(issue(
        "scale",
        "fatal",
        "Error de escala",
        `Media forecast ${meanF.toFixed(1)} vs media real ${meanA.toFixed(1)} (ratio ${((meanF / meanA) || 0).toFixed(1)}).`,
        "Revisar unidad (cajas vs unidades), factor de conversión y moneda. No usar hasta alinear la escala.",
      ));
    }

    let bestLag = 0;
    let bestCorr = -Infinity;
    const preds = s.map((p) => p.forecast);
    const actFull = s.map((p) => (p.actual === undefined ? NaN : p.actual));
    for (let lag = 0; lag <= 4; lag++) {
      const xs: number[] = [];
      const ys: number[] = [];
      for (let i = lag; i < s.length; i++) {
        if (!Number.isFinite(actFull[i])) continue;
        xs.push(preds[i - lag]);
        ys.push(actFull[i]);
      }
      if (xs.length < 6) continue;
      const mx = mean(xs);
      const my = mean(ys);
      let num = 0, dx = 0, dy = 0;
      for (let i = 0; i < xs.length; i++) {
        num += (xs[i] - mx) * (ys[i] - my);
        dx += (xs[i] - mx) ** 2;
        dy += (ys[i] - my) ** 2;
      }
      const c = dx * dy === 0 ? 0 : num / Math.sqrt(dx * dy);
      if (c > bestCorr) {
        bestCorr = c;
        bestLag = lag;
      }
    }
    if (bestLag >= 2 && bestCorr > 0.6) {
      issues.push(issue(
        "lag",
        "warn",
        "Pronóstico atrasado",
        `La correlación máxima es en lag ${bestLag} (r=${bestCorr.toFixed(2)}).`,
        "Revisar el origin del forecast (semana de emisión) y features de calendario.",
      ));
    }

    if (profile.hasTrend) {
      const lastA = mean(a.slice(-8));
      const lastF = mean(f.slice(-8));
      const firstA = mean(a.slice(0, 8));
      const dirA = lastA - firstA;
      const dirF = lastF - mean(f.slice(0, 8));
      if (Math.sign(dirA) !== Math.sign(dirF) && Math.abs(dirA) > stdev(a) * 0.2) {
        issues.push(issue(
          "trend_mismatch",
          "warn",
          "Tendencia en desacuerdo",
          "La demanda real cambia de nivel y el forecast no la sigue.",
          "Usar Holt / damped trend / boosting con tendencia, o un recálculo rolling.",
        ));
      }
    }

    if (profile.seasonalStrength > 0.35 && profile.seasonalPeriod > 1) {
      const fStr = Math.abs(stdev(f) / (mean(f) || 1));
      if (fStr < 0.05) {
        issues.push(issue(
          "season_ignored",
          "warn",
          "Estacionalidad ignorada",
          `Fuerza estacional ${(profile.seasonalStrength * 100).toFixed(0)}% en la demanda y el forecast es plano.`,
          "Holt-Winters, TBATS o dummies estacionales / Fourier en un modelo de ML.",
        ));
      }
    }
  }

  const inverted = s.filter((p) => p.lower !== undefined && p.upper !== undefined && (p.lower as number) > (p.upper as number));
  if (inverted.length) {
    issues.push(issue("pi_inverted", "error", "Intervalo invertido", "El piso es mayor que el techo.", "Intercambiar bounds o regenerar cuantiles.", inverted.map((p) => p.isoDate)));
  }

  if (s.length >= 6) {
    const last = f[f.length - 1];
    const first = Math.abs(f[0]) + 1e-6;
    if (last / first > 20 && last > profile.meanDemand * 8) {
      issues.push(issue("explode", "error", "Tendencia explosiva", "El forecast crece sin cota.", "Amortiguar tendencia (damped Holt) y capar con tope de capacidad/histórico."));
    }
  }

  const unitLike = actuals.length ? a.every((v) => Math.abs(v - Math.round(v)) < 1e-6) : f.every((v) => Math.abs(v - Math.round(v)) < 1e-6);
  const fractional = f.filter((v) => Math.abs(v - Math.round(v)) > 0.05).length;
  if (unitLike && fractional > s.length * 0.5 && profile.meanDemand < 30) {
    issues.push(issue("rounding", "info", "Demanda unitaria con decimales", "El forecast entrega fracciones para un ítem de unidades enteras.", "Redondear (o usar distribución de Poisson/Croston) antes de pasar a abastecimiento."));
  }

  const lead = s.findIndex((p) => p.forecast !== 0);
  if (lead > 3) {
    issues.push(issue("leading_zeros", "info", "Ceros iniciales", `${lead} períodos en cero al inicio.`, "Recortar historia previa al lanzamiento."));
  }

  if (s.length >= 16 && profile.cadence === "week") {
    const half = Math.floor(s.length / 2);
    if (half >= 8) {
      let copy = true;
      for (let i = 0; i < Math.min(half, 12); i++) {
        if (Math.abs(f[i] - f[i + half]) > 1e-6) copy = false;
      }
      if (copy) {
        issues.push(issue("yoy_copy", "warn", "Copia del año anterior", "El forecast replica un bloque previo sin ajuste.", "Ajustar por tendencia, precio y calendario; no copiar 52 semanas crudas."));
      }
    }
  }

  return issues;
}
