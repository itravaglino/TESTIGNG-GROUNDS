import { useEffect, useMemo, useState } from "react";
import copy from "../copy.json";
import { DEFAULT_GATES, runPipeline } from "../engine/pipeline";
import type { PipelineResult, ProductReport, QualityGates } from "../engine/types";

type Tab = "portfolio" | "product" | "issues" | "format";

function fmt(n: number | null | undefined, digits = 2, suffix = ""): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return `${n.toLocaleString("es-AR", { maximumFractionDigits: digits, minimumFractionDigits: 0 })}${suffix}`;
}

function download(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function Chart({ product }: { product: ProductReport }) {
  const rows = product.rows.filter((r) => Number.isFinite(r.timestamp)).slice(0, 260);
  if (rows.length < 2) return null;
  const w = 900;
  const h = 220;
  const pad = { l: 36, r: 12, t: 16, b: 24 };
  const ys = rows.flatMap((r) => [r.forecast, r.actual ?? r.forecast, r.lower ?? r.forecast, r.upper ?? r.forecast]);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const x = (i: number) => pad.l + (i * (w - pad.l - pad.r)) / (rows.length - 1);
  const y = (v: number) => pad.t + ((max - v) * (h - pad.t - pad.b)) / span;
  const line = (key: "forecast" | "actual") =>
    rows
      .map((r, i) => {
        const v = key === "forecast" ? r.forecast : r.actual;
        if (v === null || !Number.isFinite(v)) return null;
        return `${i === 0 || rows[i - 1][key] === null ? "M" : "L"}${x(i)} ${y(v)}`;
      })
      .filter(Boolean)
      .join(" ");
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Pronóstico versus real">
      <path d={line("forecast")} fill="none" stroke="#a33b22" strokeWidth="2" />
      <path d={line("actual")} fill="none" stroke="#1a1713" strokeWidth="1.6" strokeDasharray="4 3" />
    </svg>
  );
}

const METRIC_CARDS: { key: keyof ProductReport["metrics"]; label: string; suffix?: string }[] = [
  { key: "mae", label: "MAE" },
  { key: "rmse", label: "RMSE" },
  { key: "mape", label: "MAPE", suffix: "%" },
  { key: "smape", label: "sMAPE", suffix: "%" },
  { key: "wape", label: "WAPE", suffix: "%" },
  { key: "mdape", label: "MdAPE", suffix: "%" },
  { key: "me", label: "ME (sesgo)" },
  { key: "biasPct", label: "Sesgo vol.", suffix: "%" },
  { key: "mpe", label: "MPE", suffix: "%" },
  { key: "trackingSignal", label: "Tracking" },
  { key: "mase", label: "MASE" },
  { key: "rmsse", label: "RMSSE" },
  { key: "r2", label: "R²" },
  { key: "corr", label: "Correlación" },
  { key: "theilU", label: "Theil U" },
  { key: "hitRate", label: "Hit rate" },
  { key: "coverage", label: "Cobertura", suffix: "%" },
  { key: "pinball50", label: "Pinball 50" },
  { key: "maxAbsError", label: "Max |e|" },
  { key: "p90AbsError", label: "P90 |e|" },
];

export function App() {
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("portfolio");
  const [selected, setSelected] = useState<string | null>(null);
  const [hot, setHot] = useState(false);
  const [gates, setGates] = useState<QualityGates>(DEFAULT_GATES);
  const [source, setSource] = useState<string | null>(null);

  const product = useMemo(
    () => result?.products.find((p) => p.productId === selected) ?? result?.products[0] ?? null,
    [result, selected],
  );

  function evaluate(text: string) {
    try {
      const next = runPipeline(text, gates);
      setResult(next);
      setError(null);
      setSelected(next.products[0]?.productId ?? null);
      setTab("portfolio");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo leer el archivo");
    }
  }

  async function loadSample() {
    const res = await fetch("/sample-forecast.csv");
    const text = await res.text();
    setSource("muestra");
    evaluate(text);
  }

  useEffect(() => {
    void loadSample();
    // Carga inicial de la muestra para que el producto se pueda usar al abrir.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "");
      setSource(file.name);
      evaluate(text);
    };
    reader.readAsText(file);
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <h1>{copy.product}</h1>
          <p>
            Identifica, corrige y descarta pronósticos malos, producto por producto, con el
            catálogo completo de métricas y una recomendación de modelo.
          </p>
        </div>
        <div className="actions">
          <button type="button" className="ghost" onClick={loadSample}>
            Cargar muestra
          </button>
          <label>
            <input
              type="file"
              accept=".csv,text/csv,text/plain"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onFile(file);
              }}
            />
            <button type="button" onClick={(e) => (e.currentTarget.previousElementSibling as HTMLInputElement).click()}>
              Subir CSV
            </button>
          </label>
          <button
            type="button"
            className="ghost"
            disabled={!result}
            onClick={() => result && download("forecast-limpio.csv", result.cleanedCsv)}
          >
            Bajar limpio
          </button>
          <button
            type="button"
            className="ghost"
            disabled={!result}
            onClick={() => result && download("forecast-descartado.csv", result.discardedCsv)}
          >
            Bajar descartes
          </button>
        </div>
      </header>

      <div
        className={`drop ${hot ? "hot" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setHot(true);
        }}
        onDragLeave={() => setHot(false)}
        onDrop={(e) => {
          e.preventDefault();
          setHot(false);
          const file = e.dataTransfer.files[0];
          if (file) onFile(file);
        }}
      >
        Arrastre un CSV con producto, fecha y forecast. También se aceptan real, modelo, ubicación,
        canal, horizonte e intervalos. Separador coma, punto y coma o tab. {source ? `Fuente: ${source}.` : ""}
      </div>
      {error ? <p className="err">{error}</p> : null}

      {result ? (
        <>
          <section className="kpis">
            <div className="kpi">
              <span>Productos</span>
              <strong>{result.summary.products}</strong>
            </div>
            <div className="kpi">
              <span>Score medio</span>
              <strong>{fmt(result.summary.meanQualityScore, 0)}</strong>
            </div>
            <div className="kpi">
              <span>WAPE ponderado</span>
              <strong>{fmt(result.summary.weightedWape, 1, "%")}</strong>
            </div>
            <div className="kpi">
              <span>OK / corregir</span>
              <strong>
                {result.summary.productsOk}/{result.summary.productsFix}
              </strong>
            </div>
            <div className="kpi">
              <span>Revisar / descartar</span>
              <strong>
                {result.summary.productsReview}/{result.summary.productsDiscard}
              </strong>
            </div>
            <div className="kpi">
              <span>Filas corr. / desc.</span>
              <strong>
                {result.summary.correctedRows}/{result.summary.discardedRows}
              </strong>
            </div>
          </section>

          <nav className="tabs">
            {(
              [
                ["portfolio", "Portafolio"],
                ["product", "Producto"],
                ["issues", "Incidencias"],
                ["format", "Formato y umbrales"],
              ] as const
            ).map(([id, label]) => (
              <button key={id} type="button" className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </nav>

          {tab === "portfolio" || tab === "product" ? (
            <div className="layout">
              <aside className="plist">
                {result.products.map((p) => (
                  <button
                    key={p.productId}
                    type="button"
                    className={`pitem ${product?.productId === p.productId ? "on" : ""}`}
                    onClick={() => {
                      setSelected(p.productId);
                      setTab("product");
                    }}
                  >
                    <span>
                      {p.productName}
                      <small>
                        {p.productId} · {p.profile.demandClass} · {p.profile.frequency}
                      </small>
                    </span>
                    <span className={`badge ${p.verdict}`}>{p.verdict}</span>
                  </button>
                ))}
              </aside>
              {product ? (
                <main className="detail">
                  <h2>{product.productName}</h2>
                  <p className="lede">
                    Score {product.qualityScore} · {product.verdictReason} Clase {product.profile.demandClass},
                    tendencia {product.profile.trend}, {product.profile.n} periodos
                    {product.profile.modelsUsed.length ? `, modelo declarado: ${product.profile.modelsUsed.join(", ")}` : ""}.
                  </p>
                  <Chart product={product} />
                  <p className="legend">
                    <span>
                      <i className="fc" /> Pronóstico
                    </span>
                    <span>
                      <i className="ac" /> Real
                    </span>
                  </p>
                  <div className="metrics">
                    {METRIC_CARDS.map((m) => (
                      <div className="metric" key={m.key}>
                        <span>{m.label}</span>
                        <b>{fmt(product.metrics[m.key] as number | null, 2, m.suffix ?? "")}</b>
                      </div>
                    ))}
                  </div>
                  <div className="split">
                    <section>
                      <h3>Qué está mal y cómo corregirlo</h3>
                      {product.issues.length === 0 ? (
                        <p>Sin incidencias de calidad.</p>
                      ) : (
                        <table>
                          <thead>
                            <tr>
                              <th>Sev.</th>
                              <th>Hallazgo</th>
                              <th>Qué hacer</th>
                            </tr>
                          </thead>
                          <tbody>
                            {product.issues.slice(0, 12).map((issue, i) => (
                              <tr key={`${issue.code}-${i}`}>
                                <td className={`sev-${issue.severity}`}>{issue.severity}</td>
                                <td>{issue.message}</td>
                                <td>{issue.howToFix}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                      <h3>Mejoras</h3>
                      {product.improvements.map((a) => (
                        <article className="model" key={a.title}>
                          <header>
                            <strong>{a.title}</strong>
                            <span className="badge">{a.priority}</span>
                          </header>
                          <p>{a.detail}</p>
                          <p className="lede">{a.expectedGain}</p>
                        </article>
                      ))}
                    </section>
                    <section>
                      <h3>Modelos que puede usar</h3>
                      {product.suggestions.map((s) => (
                        <article className="model" key={s.id}>
                          <header>
                            <strong>{s.name}</strong>
                            <span className="score">{s.score}</span>
                          </header>
                          <p>{s.why}</p>
                          <p>{s.whenToUse}</p>
                          <p className="lede">{s.caveats}</p>
                          <p className="libs">{s.libraries.join(" · ")}</p>
                        </article>
                      ))}
                    </section>
                  </div>
                </main>
              ) : null}
            </div>
          ) : null}

          {tab === "issues" ? (
            <main className="page">
              <h2>Incidencias del portafolio</h2>
              <table>
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th>Sev.</th>
                    <th>Código</th>
                    <th>Mensaje</th>
                    <th>Corrección</th>
                  </tr>
                </thead>
                <tbody>
                  {result.issues.map((issue, i) => (
                    <tr key={`${issue.productId}-${issue.code}-${i}`}>
                      <td>{issue.productId}</td>
                      <td className={`sev-${issue.severity}`}>{issue.severity}</td>
                      <td>{issue.code}</td>
                      <td>{issue.message}</td>
                      <td>{issue.howToFix}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </main>
          ) : null}

          {tab === "format" ? (
            <main className="page">
              <h2>Formato aceptado</h2>
              <p>
                Columnas mínimas: <b>producto</b> (o sku), <b>fecha</b>, <b>forecast</b> (o pronóstico /
                predicción / yhat). Opcionales: nombre, real, modelo, ubicacion, canal, horizonte, lower,
                upper. Fechas ISO, DD/MM/AAAA o serial Excel. Números 1234.56 o 1.234,56.
              </p>
              <pre className="spec">{`producto;nombre;fecha;forecast;real;modelo;ubicacion;canal;horizonte;lower;upper
SKU-1001;Café de Altura 340g;2025-01-06;214.67;207.59;prophet;CDMX;autoservicio;4;180.32;249.01`}</pre>
              <h3>Umbrales</h3>
              <p>Al cambiarlos, vuelva a cargar el archivo o la muestra para recalcular.</p>
              <div className="gates">
                {(
                  [
                    ["mapeWarn", "MAPE alerta"],
                    ["mapeFail", "MAPE falla"],
                    ["wapeWarn", "WAPE alerta"],
                    ["wapeFail", "WAPE falla"],
                    ["trackingSignalFail", "Tracking"],
                    ["minPoints", "Mín. puntos"],
                    ["spikeZ", "Z de picos"],
                    ["coverageMin", "Cobertura mín."],
                    ["scaleShiftRatio", "Ratio de escala"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <input
                      type="number"
                      value={gates[key]}
                      onChange={(e) => setGates({ ...gates, [key]: Number(e.target.value) })}
                    />
                  </label>
                ))}
              </div>
              <h3>Glosario</h3>
              <table>
                <thead>
                  <tr>
                    <th>Métrica</th>
                    <th>Qué mide</th>
                  </tr>
                </thead>
                <tbody>
                  {copy.glossary.metrics.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <b>{m.abbr}</b> {m.name}
                      </td>
                      <td>{m.definition}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </main>
          ) : null}
        </>
      ) : (
        <main className="page">
          <h2>Cómo usarlo</h2>
          <p>
            Suba su forecast o abra la muestra de 8 SKU con defectos plantados (escala ×1000,
            negativos, huecos, constante, explosión, duplicados, intermitencia). El motor —armado
            entre ocho instancias de Grok— parsea, puntúa, corrige, descarta y recomienda modelo.
          </p>
        </main>
      )}
    </div>
  );
}
