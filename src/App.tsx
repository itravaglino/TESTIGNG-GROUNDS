import { useEffect, useMemo, useState } from "react";
import type { ProductReport, QaReport } from "./engine/types";
import { exportCleaned, exportDiscarded, exportRecommendations, runQa } from "./engine/pipeline";
import { sampleForecastCsv } from "./engine/sample";
import { classLabel, downloadText, fmtNum, fmtPct, freqLabel, verdictLabel } from "./engine/format";

function Spark({ p }: { p: ProductReport }) {
  const w = 640;
  const h = 180;
  const pad = 16;
  const series = p.series;
  if (series.length === 0) return null;
  const ys = series.flatMap((s) => [s.forecast, s.actual, s.forecastRaw]).filter((x): x is number => x !== null);
  const min = Math.min(0, ...ys);
  const max = Math.max(1, ...ys);
  const x = (i: number) => pad + (i * (w - pad * 2)) / Math.max(1, series.length - 1);
  const y = (v: number) => h - pad - ((v - min) / (max - min || 1)) * (h - pad * 2);
  const path = (field: "forecast" | "actual") => {
    const pts: string[] = [];
    series.forEach((s, i) => {
      const v = s[field];
      if (v === null) return;
      pts.push(`${pts.length ? "L" : "M"}${x(i)},${y(v)}`);
    });
    return pts.join(" ");
  };
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Serie pronóstico vs real">
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#e4ddd3" />
      <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="#e4ddd3" />
      <path d={path("actual")} fill="none" stroke="#1c1916" strokeWidth="1.6" />
      <path d={path("forecast")} fill="none" stroke="#9a3412" strokeWidth="1.8" />
      <text x={pad + 4} y={14} fontSize="11" fill="#6b645c">
        negro = real · terracota = pronóstico corregido
      </text>
    </svg>
  );
}

export function App() {
  const [report, setReport] = useState<QaReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "keep" | "correct" | "discard">("all");
  const [sel, setSel] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("demo") === "1") analyze(sampleForecastCsv());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- demo bootstrap once
  }, []);

  function analyze(text: string) {
    setBusy(true);
    setError(null);
    try {
      const qa = runQa(text);
      if (qa.products.length === 0) {
        setError(qa.parse.issues.map((i) => i.message).join(" ") || "No pude leer el archivo.");
        setReport(null);
        return;
      }
      setReport(qa);
      setSel(qa.products[0]?.key ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al analizar");
      setReport(null);
    } finally {
      setBusy(false);
    }
  }

  function onFile(file: File) {
    file.text().then(analyze).catch(() => setError("No pude leer el archivo."));
  }

  const visible = useMemo(() => {
    if (!report) return [];
    return report.products.filter((p) => {
      if (filter !== "all" && p.verdict !== filter) return false;
      if (q && !p.product.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
  }, [report, q, filter]);

  const selected = report?.products.find((p) => p.key === sel) ?? visible[0] ?? null;

  return (
    <div className="app">
      <header className="top">
        <div>
          <p className="eyebrow">Demand planning · auditoría</p>
          <h1>Forecast QA</h1>
          <p className="lede">
            Subí un CSV de pronóstico. El sistema identifica series malas, corrige lo recuperable,
            descarta lo inutilizable y recomienda modelos producto a producto.
          </p>
        </div>
        <div className="actions">
          <button className="btn ghost" type="button" onClick={() => analyze(sampleForecastCsv())}>
            Cargar muestra
          </button>
          {report && (
            <>
              <button className="btn ghost" type="button" onClick={() => downloadText("forecast_corregido.csv", exportCleaned(report))}>
                Exportar corregido
              </button>
              <button className="btn ghost" type="button" onClick={() => downloadText("forecast_descartes.csv", exportDiscarded(report))}>
                Exportar descartes
              </button>
              <button className="btn" type="button" onClick={() => downloadText("forecast_recomendaciones.csv", exportRecommendations(report))}>
                Exportar recomendaciones
              </button>
            </>
          )}
        </div>
      </header>

      <label className="drop">
        <input
          type="file"
          accept=".csv,text/csv,text/plain"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
        />
        <strong>{busy ? "Analizando…" : "Soltá un CSV o hacé clic para elegir archivo"}</strong>
        <p>También se acepta pegar formato ancho (fechas en columnas) y CSV con ; y decimal coma.</p>
      </label>

      <p className="format">
        Formato largo esperado: <code>producto,fecha,pronostico,real,modelo,canal</code>.
        Columnas en español o inglés. <code>real</code> es opcional pero habilita todas las métricas de error.
        Fechas ISO o dd/mm/aaaa. Máximo 80.000 filas.
      </p>

      {error && <p className="parse-issues">{error}</p>}

      {report && (
        <>
          {report.parse.issues.filter((i) => i.severity !== "info").length > 0 && (
            <p className="parse-issues">
              {report.parse.issues
                .filter((i) => i.severity !== "info")
                .slice(0, 6)
                .map((i) => i.message)
                .join(" · ")}
            </p>
          )}
          <section className="kpis">
            <div className="kpi">
              <span>Productos</span>
              <b>{fmtNum(report.portfolio.products, "0")}</b>
            </div>
            <div className="kpi">
              <span>Conservar</span>
              <b>{fmtNum(report.portfolio.keep, "0")}</b>
            </div>
            <div className="kpi">
              <span>Corregir</span>
              <b>{fmtNum(report.portfolio.correct, "0")}</b>
            </div>
            <div className="kpi">
              <span>Descartar</span>
              <b>{fmtNum(report.portfolio.discard, "0")}</b>
            </div>
            <div className="kpi">
              <span>WAPE portafolio</span>
              <b>{fmtPct(report.portfolio.wape)}</b>
            </div>
            <div className="kpi">
              <span>Sesgo medio</span>
              <b>{fmtNum(report.portfolio.bias)}</b>
            </div>
          </section>

          <div className="toolbar">
            <input placeholder="Filtrar producto" value={q} onChange={(e) => setQ(e.target.value)} />
            <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>
              <option value="all">Todos</option>
              <option value="keep">Conservar</option>
              <option value="correct">Corregir</option>
              <option value="discard">Descartar</option>
            </select>
          </div>

          <div className="layout">
            <div>
              <table>
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th>Veredicto</th>
                    <th>Score</th>
                    <th>Clase</th>
                    <th>WAPE</th>
                    <th>Modelo</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((p) => {
                    const wape = p.metrics.find((m) => m.id === "wape")?.value ?? null;
                    return (
                      <tr
                        key={p.key}
                        className={`click ${selected?.key === p.key ? "sel" : ""}`}
                        onClick={() => setSel(p.key)}
                      >
                        <td>
                          {p.product}
                          {p.channel ? <div style={{ color: "#6b645c", fontSize: 11 }}>{p.channel}</div> : null}
                        </td>
                        <td>
                          <span className={`tag ${p.verdict}`}>{verdictLabel(p.verdict)}</span>
                        </td>
                        <td>{p.score}</td>
                        <td>{classLabel(p.demandClass)}</td>
                        <td>{fmtPct(wape)}</td>
                        <td>{p.models[0]?.name ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {selected && (
              <aside className="panel">
                <h2>{selected.product}</h2>
                <p className="meta">
                  {verdictLabel(selected.verdict)} · score {selected.score} · {classLabel(selected.demandClass)} ·
                  frecuencia {freqLabel(selected.frequency)} · {selected.n} períodos
                  {selected.adi !== null ? ` · ADI ${fmtNum(selected.adi, "3")}` : ""}
                  {selected.cv2 !== null ? ` · CV² ${fmtNum(selected.cv2, "3")}` : ""}
                  {selected.hasTrend ? " · tendencia" : ""}
                  {selected.seasonalLag ? ` · estacionalidad ${selected.seasonalLag}` : ""}
                </p>
                <Spark p={selected} />

                <h3>Métricas</h3>
                <div className="metrics">
                  {selected.metrics
                    .filter((m) => m.value !== null)
                    .map((m) => (
                      <div key={m.id}>
                        <span title={m.note}>{m.label}</span>
                        <b>{m.unit === "pct" ? fmtPct(m.value) : fmtNum(m.value, m.id === "n_eval" ? "0" : "2")}</b>
                      </div>
                    ))}
                </div>

                <h3>Hallazgos</h3>
                <ul className="issues">
                  {selected.issues.length === 0 && <li>Sin problemas de calidad graves.</li>}
                  {selected.issues.map((i) => (
                    <li key={i.id} className={i.severity}>
                      {i.message}
                      {i.autoFixed ? " (corregido)" : ""}
                    </li>
                  ))}
                </ul>

                {selected.corrections.length > 0 && (
                  <>
                    <h3>Correcciones aplicadas</h3>
                    <ul>
                      {selected.corrections.map((c) => (
                        <li key={c.id}>
                          {c.message} ({c.count})
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                <h3>Modelos sugeridos</h3>
                {selected.models.map((m) => (
                  <div key={m.id} style={{ marginBottom: 10 }}>
                    <strong>
                      {m.name} · afinidad {m.fit}
                    </strong>
                    <p style={{ margin: "4px 0", fontSize: 14 }}>{m.why}</p>
                    <p style={{ margin: "4px 0", fontSize: 13, color: "#6b645c" }}>{m.howToStart}</p>
                    <p style={{ margin: "4px 0", fontSize: 13, color: "#9a3412" }}>{m.caution}</p>
                    <p style={{ margin: 0, fontSize: 12, color: "#6b645c" }}>{m.libs.join(" · ")}</p>
                  </div>
                ))}

                <h3>Cómo mejorar</h3>
                <ul>
                  {selected.improvements.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              </aside>
            )}
          </div>
        </>
      )}
    </div>
  );
}
