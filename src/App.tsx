import { useMemo, useState } from "react";
import { FORMAT_SPEC, buildSampleCsv } from "./engine/sample";
import {
  exportCleanCsv,
  exportDiscardCsv,
  exportModelsCsv,
  runForecastQa,
} from "./engine/pipeline";
import { formatNum, formatPct, intermittencyLabel, METRIC_HELP } from "./engine/metrics";
import { EVAL_PROTOCOL } from "./engine/models";
import type { PipelineResult, ProductResult, Verdict } from "./engine/types";

function download(name: string, text: string) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function Spark({ product }: { product: ProductResult }) {
  const pts = product.verdict === "discard" ? product.original : product.corrected;
  const ys = pts.map((p) => p.forecast);
  const as = pts.map((p) => p.actual).filter((x): x is number => x !== undefined);
  const all = [...ys, ...as];
  const min = Math.min(...all, 0);
  const max = Math.max(...all, 1);
  const w = 340;
  const h = 72;
  const x = (i: number) => (pts.length <= 1 ? 0 : (i / (pts.length - 1)) * (w - 4) + 2);
  const y = (v: number) => h - 4 - ((v - min) / (max - min || 1)) * (h - 8);
  const line = (vals: (number | undefined)[], use: boolean) => {
    if (!use) return "";
    return vals
      .map((v, i) => (v === undefined ? null : `${i === 0 || vals[i - 1] === undefined ? "M" : "L"}${x(i)},${y(v)}`))
      .filter(Boolean)
      .join(" ");
  };
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Serie forecast vs real">
      <path d={line(pts.map((p) => p.actual), true)} fill="none" stroke="#6b8cce" strokeWidth="1.4" />
      <path d={line(ys, true)} fill="none" stroke="#c4a35a" strokeWidth="1.6" />
    </svg>
  );
}

const VERDICT_LABEL: Record<Verdict, string> = {
  keep: "Conservar",
  correct: "Corregido",
  discard: "Descartar",
};

export function App() {
  const [raw, setRaw] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | Verdict>("all");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [sampleNote, setSampleNote] = useState(false);

  const result: PipelineResult | null = useMemo(() => (raw ? runForecastQa(raw) : null), [raw]);
  const products = result?.products ?? [];
  const shown = products.filter((p) => {
    if (filter !== "all" && p.verdict !== filter) return false;
    const hay = `${p.productId} ${p.productName} ${p.location}`.toLowerCase();
    return hay.includes(q.toLowerCase());
  });
  const selected = products.find((p) => p.key === sel) ?? shown[0] ?? null;

  function onFile(file: File) {
    setSampleNote(false);
    file.text().then((t) => {
      setRaw(t);
      setSel(null);
    });
  }

  function loadSample() {
    setSampleNote(true);
    setRaw(buildSampleCsv());
    setSel(null);
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Forecast QA</h1>
          <p>
            Cargá un CSV de pronóstico. El sistema identifica series malas, las corrige cuando se puede,
            descarta las inoperables, calcula métricas por producto y recomienda modelos.
          </p>
        </div>
        <div className="actions">
          <button className="btn" type="button" onClick={loadSample}>Cargar ejemplo</button>
          {result && (
            <>
              <button className="btn" type="button" onClick={() => download("forecast_corregido.csv", exportCleanCsv(products))}>
                CSV corregido
              </button>
              <button className="btn" type="button" onClick={() => download("forecast_descartes.csv", exportDiscardCsv(products))}>
                CSV descartes
              </button>
              <button className="btn" type="button" onClick={() => download("forecast_modelos.csv", exportModelsCsv(products))}>
                CSV modelos
              </button>
            </>
          )}
        </div>
      </header>
      <div className="layout">
        <aside className="side">
          <label className="drop">
            <strong>Soltá el CSV o elegí archivo</strong>
            sku, fecha, pronostico · ventas opcional
            <input
              type="file"
              accept=".csv,text/csv,text/plain"
              style={{ display: "block", margin: "10px auto 0", maxWidth: "100%" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onFile(f);
              }}
            />
          </label>
          <button className="btn primary" type="button" style={{ width: "100%", marginBottom: 8 }} onClick={loadSample}>
            Cargar ejemplo (12 SKUs)
          </button>
          {sampleNote && <div className="meta">Datos de ejemplo (12 SKUs semanales, 2025). No es tu archivo.</div>}
          {result && (
            <>
              <div className="kpis">
                <div className="kpi"><div className="v">{result.summary.total}</div><div className="l">Productos</div></div>
                <div className="kpi"><div className="v">{formatPct(result.summary.medianWape, 0)}</div><div className="l">WAPE mediano</div></div>
                <div className="kpi keep"><div className="v">{result.summary.keep}</div><div className="l">Conservar</div></div>
                <div className="kpi correct"><div className="v">{result.summary.correct}</div><div className="l">Corregidos</div></div>
                <div className="kpi discard"><div className="v">{result.summary.discard}</div><div className="l">Descartar</div></div>
                <div className="kpi"><div className="v">{result.summary.withActuals}</div><div className="l">Con ventas</div></div>
              </div>
              <div className="meta">
                Delimitador {result.report.delimiter} · {result.report.acceptedRows}/{result.report.rowCount} filas
                {result.report.errors.length > 0 && ` · ${result.report.errors.length} errores de parseo`}
                <br />
                Mapeo: {Object.entries(result.report.mapping).filter(([, r]) => r !== "ignore").map(([h, r]) => `${h}→${r}`).join(", ")}
              </div>
            </>
          )}
          <h3>Formato</h3>
          <pre className="meta" style={{ whiteSpace: "pre-wrap" }}>{FORMAT_SPEC}</pre>
        </aside>
        <section className="main">
          {!result && <div className="empty">Todavía no hay forecast. Cargá un CSV o el ejemplo para auditar producto por producto.</div>}
          {result && (
            <>
              <div className="toolbar">
                <input placeholder="Buscar SKU o nombre" value={q} onChange={(e) => setQ(e.target.value)} />
                <select value={filter} onChange={(e) => setFilter(e.target.value as "all" | Verdict)}>
                  <option value="all">Todos</option>
                  <option value="keep">Conservar</option>
                  <option value="correct">Corregidos</option>
                  <option value="discard">Descartar</option>
                </select>
                <span className="meta">{shown.length} series</span>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Producto</th>
                    <th>Veredicto</th>
                    <th>Calidad</th>
                    <th>Clase</th>
                    <th className="num">WAPE</th>
                    <th className="num">Bias</th>
                    <th className="num">MASE</th>
                    <th>Modelo #1</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((p) => (
                    <tr key={p.key} className={selected?.key === p.key ? "active" : ""} onClick={() => setSel(p.key)}>
                      <td>
                        <div>{p.productName}</div>
                        <div className="meta">{p.productId} · {p.location} · {p.corrected.length} pts</div>
                      </td>
                      <td><span className={`pill ${p.verdict}`}>{VERDICT_LABEL[p.verdict]}</span></td>
                      <td>
                        <div className="num">{p.quality}</div>
                        <div className="bar"><span style={{ width: `${p.quality}%` }} /></div>
                      </td>
                      <td>{intermittencyLabel(p.profile.intermittency)}</td>
                      <td className="num">{formatPct(p.metricsCorrected.wape)}</td>
                      <td className="num">{formatPct(p.metricsCorrected.biasPct)}</td>
                      <td className="num">{formatNum(p.metricsCorrected.mase)}</td>
                      <td>{p.models[0]?.name ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
        <aside className="detail">
          {!selected && <div className="empty">Elegí un producto para ver métricas, correcciones y modelos.</div>}
          {selected && <ProductDetail product={selected} />}
        </aside>
      </div>
    </div>
  );
}

function ProductDetail({ product }: { product: ProductResult }) {
  const m = product.metricsCorrected;
  const metricKeys = [
    "wape", "smape", "mape", "mae", "rmse", "mase", "rmsse", "biasPct", "me", "trackingSignal",
    "hitRate10", "hitRate20", "underForecastRate", "theilU2", "r2", "adi", "cv2",
  ] as const;
  return (
    <div>
      <h2>{product.productName}</h2>
      <div className="meta">
        {product.productId} · {product.location} · {product.profile.cadence} · {product.profile.n} períodos
      </div>
      <p style={{ margin: "8px 0" }}>
        <span className={`pill ${product.verdict}`}>{VERDICT_LABEL[product.verdict]}</span>
        {" "}calidad {product.quality}/100
      </p>
      <Spark product={product} />
      <div className="meta">Dorado: pronóstico · Azul: ventas reales</div>

      {product.verdict === "discard" && (
        <>
          <h3>Por qué se descarta</h3>
          <p style={{ fontSize: 13 }}>{product.discard.reason}</p>
          <p className="meta">{product.discard.keepHint}</p>
        </>
      )}

      <h3>Cómo mejorar</h3>
      <ul className="impr">
        {product.improvements.map((t) => <li key={t}>{t}</li>)}
      </ul>

      {product.corrections.length > 0 && (
        <>
          <h3>Correcciones aplicadas</h3>
          {product.corrections.map((c) => (
            <div className="issue" key={c.code}>
              <div className="t">{c.description}</div>
              <div className="meta">{c.pointsChanged} punto(s)</div>
            </div>
          ))}
        </>
      )}

      <h3>Hallazgos</h3>
      {product.issues.length === 0 && <div className="meta">Sin hallazgos estructurales.</div>}
      {product.issues.map((i) => (
        <div className="issue" key={i.code}>
          <div className="t"><span className={`pill ${i.severity}`}>{i.severity}</span> {i.title}</div>
          <div>{i.detail}</div>
          <div className="meta">{i.howToFix}</div>
        </div>
      ))}

      <h3>Métricas</h3>
      <table>
        <tbody>
          {metricKeys.map((k) => {
            const help = METRIC_HELP[k];
            const raw = m[k];
            const isRate = ["wape", "smape", "mape", "mdape", "biasPct", "hitRate10", "hitRate20", "underForecastRate", "overForecastRate", "rmsePct", "mpe", "piCoverage"].includes(k);
            return (
              <tr key={k}>
                <td title={help ? `${help.formula}. ${help.good}` : k}>{help?.name ?? k}</td>
                <td className="num">{isRate ? formatPct(raw as number | null) : formatNum(raw as number | null)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="meta">ADI {formatNum(m.adi)} · CV² {formatNum(m.cv2)} · clase {intermittencyLabel(m.intermittency)}</div>

      <h3>Modelos recomendados</h3>
      {product.models.map((mod, idx) => (
        <div className="model" key={mod.id}>
          <div><span className="sc">{mod.score}</span> · {idx + 1}. {mod.name}</div>
          <div>{mod.whyThisProduct}</div>
          <div className="meta">{mod.libraries}</div>
          <div className="meta">Hiperparámetros: {mod.hyperparameters}</div>
          <div className="meta">{mod.caveats}</div>
        </div>
      ))}
      <h3>Protocolo de evaluación</h3>
      <div className="meta">
        {EVAL_PROTOCOL.primary}. {EVAL_PROTOCOL.split}. {EVAL_PROTOCOL.folds}. {EVAL_PROTOCOL.secondary}. {EVAL_PROTOCOL.note}
      </div>
    </div>
  );
}
