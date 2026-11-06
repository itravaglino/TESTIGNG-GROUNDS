import { useMemo, useState } from "react";
import { analyzeCsv, exportCsv, metricMap } from "../engine/analyze";
import type { PortfolioReport, ProductReport, Verdict } from "../engine/types";
import { DEMO_CSV } from "./demo";

type SortKey = "productId" | "verdict" | "wape" | "bias" | "volume" | "model" | "health";

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toLocaleString("es-AR", { maximumFractionDigits: digits, minimumFractionDigits: digits })} %`;
}
function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("es-AR", { maximumFractionDigits: digits });
}
function toneHealth(v: number): "good" | "warn" | "bad" {
  if (v >= 80) return "good";
  if (v >= 60) return "warn";
  return "bad";
}
function toneShare(v: number, good: number, warn: number): "good" | "warn" | "bad" {
  const p = v * 100;
  if (p < good) return "good";
  if (p <= warn) return "warn";
  return "bad";
}
function toneWape(v: number | null): "good" | "warn" | "bad" {
  if (v == null) return "warn";
  if (v <= 15) return "good";
  if (v <= 30) return "warn";
  return "bad";
}
function toneBias(v: number | null): "good" | "warn" | "bad" {
  if (v == null) return "warn";
  const a = Math.abs(v);
  if (a <= 5) return "good";
  if (a <= 15) return "warn";
  return "bad";
}

const VERDICT_LABEL: Record<Verdict, string> = {
  keep: "Mantener",
  review: "Revisar",
  discard: "Descartar",
};

export function App() {
  const [paste, setPaste] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<PortfolioReport | null>(null);
  const [filter, setFilter] = useState<"all" | Verdict>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "volume", dir: -1 });
  const [selected, setSelected] = useState<string | null>(null);

  function run(text: string, name: string) {
    try {
      const next = analyzeCsv(text);
      if (!next.products.length) {
        setError(next.diagnostics[0]?.message ?? "El archivo no contiene filas de datos.");
        setReport(null);
        return;
      }
      setError(null);
      setReport(next);
      setFileName(name);
      setSelected(next.products[0] ? `${next.products[0].productId}||${next.products[0].model}` : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo leer el archivo.");
      setReport(null);
    }
  }

  function onFile(file: File) {
    file.text().then((t) => run(t, file.name));
  }

  const rows = useMemo(() => {
    if (!report) return [];
    let list = report.products;
    if (filter !== "all") list = list.filter((p) => p.verdict === filter);
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (p) =>
          p.productId.toLowerCase().includes(q) ||
          (p.productName ?? "").toLowerCase().includes(q) ||
          p.model.toLowerCase().includes(q),
      );
    }
    const sorted = [...list].sort((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * sort.dir;
      return ((av as number) - (bv as number)) * sort.dir;
    });
    return sorted;
  }, [report, filter, query, sort]);

  const selectedProduct = report?.products.find((p) => `${p.productId}||${p.model}` === selected) ?? null;

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>Revisión de pronósticos</h1>
          <p className="sub">Calidad del portafolio de demanda, producto por producto</p>
        </div>
        <div className="actions">
          <button disabled={!report} onClick={() => download("veredictos.json", JSON.stringify(serialize(report!), null, 2))}>
            Exportar JSON
          </button>
          <button disabled={!report} onClick={() => download("veredictos.csv", exportCsv(report!))}>
            Exportar CSV
          </button>
        </div>
      </header>

      <section>
        <h2>Datos de entrada</h2>
        <div className="drop"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f) onFile(f);
          }}
        >
          <p>Arrastre un CSV aquí o seleccione un archivo. UTF-8. Separador coma, punto y coma o tabulador.</p>
          <div className="row">
            <label className="linkish">
              Seleccionar archivo
              <input type="file" accept=".csv,text/csv,text/plain" hidden onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onFile(f);
              }} />
            </label>
            <button type="button" className="primary" onClick={() => run(DEMO_CSV, "portafolio-demo.csv")}>
              Cargar portafolio de ejemplo
            </button>
            <button
              type="button"
              onClick={() => {
                fetch("/samples/planilla_mann_muestra.csv")
                  .then((res) => {
                    if (!res.ok) throw new Error("No está la muestra de la planilla estándar.");
                    return res.text();
                  })
                  .then((text) => run(text, "planilla_mann_muestra.csv"))
                  .catch((e: unknown) => setError(e instanceof Error ? e.message : "No se pudo cargar la muestra."));
              }}
            >
              Cargar muestra de la planilla estándar
            </button>
            <a href="/samples/plantilla-minima.csv" download>Descargar plantilla mínima</a>
            <a href="/samples/forecast_largo_ar.csv" download>Descargar plantilla Argentina (;)</a>
          </div>
          <textarea
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            placeholder="Pegue filas con encabezado. Separador coma o tabulador."
          />
          <div className="row">
            <button type="button" onClick={() => paste.trim() && run(paste, "pegado.csv")}>Usar estos datos</button>
            <button type="button" onClick={() => setPaste("")}>Limpiar</button>
          </div>
          <p className="hint">
            Columnas reconocidas: sku/código, producto, fecha/periodo, pronóstico/forecast, real/actual/ventas, modelo, lo/hi o p10/p90.
            También acepta formato ancho (meses en columnas) y decimales con coma.
          </p>
          {fileName && report && (
            <p className="note">
              {fileName} · {report.productCount} productos · {report.periodCount} periodos · {report.rowCount} filas
            </p>
          )}
          {error && <p className="err">{error}</p>}
        </div>
      </section>

      {!report && (
        <section>
          <h2>Aún no hay pronósticos para revisar</h2>
          <p className="empty">
            Cargue un CSV o use el portafolio de ejemplo para calcular la salud, los veredictos, las métricas y los modelos recomendados.
          </p>
        </section>
      )}

      {report && (
        <>
          <section>
            <h2>Salud del portafolio</h2>
            <div className="kpis">
              <Kpi
                label="Salud del portafolio"
                value={String(report.health)}
                tone={toneHealth(report.health)}
                read={report.health >= 80 ? "Listo para operar" : report.health >= 60 ? "Revise el portafolio antes de publicar" : "No publique este portafolio tal cual"}
              />
              <Kpi
                label="Descartados"
                value={fmtPct(report.discardedShare * 100, 0)}
                tone={toneShare(report.discardedShare, 10, 25)}
                read="Productos cuyo pronóstico no debe usarse tal cual."
              />
              <Kpi
                label="A revisar"
                value={fmtPct(report.reviewShare * 100, 0)}
                tone={toneShare(report.reviewShare, 20, 40)}
                read="Productos que necesitan criterio humano antes de publicarse."
              />
              <Kpi
                label="WAPE ponderado"
                value={fmtPct(report.wape)}
                tone={toneWape(report.wape)}
                read="Suma del error absoluto dividida por la suma del real."
              />
              <Kpi
                label="Sesgo"
                value={fmtPct(report.bias)}
                tone={toneBias(report.bias)}
                read={
                  report.bias == null
                    ? "Sin reales comparables."
                    : Math.abs(report.bias) <= 5
                      ? "Sesgo bajo"
                      : report.bias > 0
                        ? "Sobrepronóstico"
                        : "Subpronóstico"
                }
              />
            </div>
            {report.cancellationGap != null && (
              <p className="note">
                Brecha de cancelación (WAPE SKU vs serie agregada): {fmtPct(report.cancellationGap)}.
                Un valor alto significa que los errores se compensan en el total y no en la reposición por SKU.
              </p>
            )}
          </section>

          <div className="layout">
            <section>
              <h2>Productos</h2>
              <p className="hint">Mantener: operable. Revisar: hace falta criterio humano. Descartar: no usar tal cual.</p>
              <div className="toolbar filters">
                {(["all", "keep", "review", "discard"] as const).map((k) => (
                  <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>
                    {k === "all" ? "Todos" : VERDICT_LABEL[k]}
                  </button>
                ))}
                <input
                  type="search"
                  placeholder="Buscar por SKU o producto"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <span className="note">{rows.length} productos</span>
              </div>
              {rows.length === 0 ? (
                <p className="empty">Ningún producto coincide con este filtro.</p>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <Th k="productId" sort={sort} setSort={setSort}>SKU</Th>
                        <th>Producto</th>
                        <Th k="verdict" sort={sort} setSort={setSort}>Veredicto</Th>
                        <Th k="health" sort={sort} setSort={setSort}>Salud</Th>
                        <Th k="wape" sort={sort} setSort={setSort}>WAPE</Th>
                        <Th k="bias" sort={sort} setSort={setSort}>Sesgo</Th>
                        <Th k="volume" sort={sort} setSort={setSort}>Volumen</Th>
                        <Th k="model" sort={sort} setSort={setSort}>Modelo recomendado</Th>
                        <th>Señales</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((p) => {
                        const id = `${p.productId}||${p.model}`;
                        const m = metricMap(p.metrics);
                        return (
                          <tr key={id} className={selected === id ? "selected" : ""} onClick={() => setSelected(id)}>
                            <td>
                              {p.productId}
                              {p.model !== "default" && <div className="note">{p.model}</div>}
                            </td>
                            <td>{p.productName ?? "—"}</td>
                            <td><span className={`badge ${p.verdict}`}>{VERDICT_LABEL[p.verdict]}</span></td>
                            <td className={`tone-${toneHealth(p.health)}`}>{p.health}</td>
                            <td className={`tone-${toneWape(m.wape)}`}>{fmtPct(m.wape)}</td>
                            <td className={`tone-${toneBias(m.pbias)}`}>{fmtPct(m.pbias)}</td>
                            <td>{fmtNum(p.volume, 0)}</td>
                            <td>{p.recommended.name}</td>
                            <td>{p.flags.length}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
            <Detail product={selectedProduct} />
          </div>
        </>
      )}
    </div>
  );
}

function Th({ k, sort, setSort, children }: { k: SortKey; sort: { key: SortKey; dir: 1 | -1 }; setSort: (s: { key: SortKey; dir: 1 | -1 }) => void; children: string }) {
  return (
    <th onClick={() => setSort({ key: k, dir: sort.key === k ? (sort.dir === 1 ? -1 : 1) : -1 })}>
      {children}
      {sort.key === k ? (sort.dir === -1 ? " ↓" : " ↑") : ""}
    </th>
  );
}

function sortValue(p: ProductReport, key: SortKey): number | string {
  const m = metricMap(p.metrics);
  switch (key) {
    case "productId": return p.productId;
    case "verdict": return p.verdict;
    case "wape": return m.wape ?? 1e9;
    case "bias": return Math.abs(m.pbias ?? 0);
    case "volume": return p.volume;
    case "model": return p.recommended.name;
    case "health": return p.health;
  }
}

function Kpi({ label, value, tone, read }: { label: string; value: string; tone: "good" | "warn" | "bad"; read: string }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className={`value tone-${tone}`}>{value}</div>
      <div className="read">{read}</div>
    </div>
  );
}

function Detail({ product }: { product: ProductReport | null }) {
  if (!product) {
    return (
      <section className="detail">
        <h2>Detalle del producto</h2>
        <p className="empty">Seleccione un producto para ver la serie, las señales y la recomendación.</p>
      </section>
    );
  }
  const m = metricMap(product.metrics);
  const show = product.metrics.filter((x) => ["wape", "pbias", "mae", "rmse", "mape", "smape", "mase", "rmsse", "theil_u2", "r2", "corr", "tracking_signal", "pct_overforecast", "fill_rate"].includes(x.id));
  return (
    <section className="detail">
      <h2>Detalle del producto</h2>
      <h3>{product.productId} {product.productName ? `· ${product.productName}` : ""}</h3>
      <p>
        <span className={`badge ${product.verdict}`}>{VERDICT_LABEL[product.verdict]}</span>
        {" "}Modelo cargado: {product.model} · Clase: {clase(product.features.demandClass)} · ADI {fmtNum(product.features.adi, 2)} · CV² {fmtNum(product.features.cv2, 2)}
      </p>
      <h3>Serie</h3>
      <SeriesChart product={product} />
      <div className="legend">
        <span>Real — trazo lleno</span>
        <span>Pronóstico — trazo gris</span>
        <span>Corregido — discontinuo</span>
      </div>
      <h3>Métricas</h3>
      <div className="metrics-grid">
        {show.map((x) => (
          <div className="metric" key={x.id}>
            <span>{x.name}</span>
            <b>{x.unit === "percent" ? fmtPct(x.value) : fmtNum(x.value, 2)}</b>
          </div>
        ))}
      </div>
      <p className="note">WAPE {fmtPct(m.wape)} · Sesgo {fmtPct(m.pbias)} · Volumen {fmtNum(product.volume, 0)}</p>
      <h3>Señales</h3>
      <ul className="plain">
        {product.flags.map((f) => (
          <li key={f.id}><strong>{f.id}.</strong> {f.message}</li>
        ))}
      </ul>
      {product.mutations.length > 0 && (
        <>
          <h3>Correcciones aplicadas</h3>
          <ul className="plain">
            {product.mutations.map((mu, i) => (
              <li key={i}>{mu.message}</li>
            ))}
          </ul>
        </>
      )}
      <h3>Cómo mejorar</h3>
      <ul className="plain">
        {product.tips.map((t) => (
          <li key={t.id}><strong>{t.title}.</strong> {t.body}</li>
        ))}
      </ul>
      <h3>Modelo recomendado</h3>
      <p><strong>{product.recommended.name}</strong> — {product.recommended.reason}</p>
      {product.challengers.length > 0 && (
        <ul className="plain">
          {product.challengers.map((c) => (
            <li key={c.id}><strong>{c.name}.</strong> {c.reason}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function clase(c: ProductReport["features"]["demandClass"]): string {
  return { smooth: "suave", erratic: "errática", intermittent: "intermitente", lumpy: "irregular", unknown: "sin clasificar" }[c];
}

function SeriesChart({ product }: { product: ProductReport }) {
  const pts = product.points;
  if (pts.length < 2) return <p className="note">Historia demasiado corta para graficar.</p>;
  const ys: number[] = [];
  for (const p of pts) {
    if (p.actual != null) ys.push(p.actual);
    if (p.forecast != null) ys.push(p.forecast);
    const c = product.correctedForecast[p.date];
    if (c != null) ys.push(c);
  }
  const min = Math.min(0, ...ys);
  const max = Math.max(...ys, 1);
  const w = 640;
  const h = 220;
  const pad = 28;
  const x = (i: number) => pad + (i * (w - pad * 2)) / (pts.length - 1);
  const y = (v: number) => h - pad - ((v - min) / (max - min || 1)) * (h - pad * 2);
  const line = (pick: (p: (typeof pts)[0], i: number) => number | null) => {
    const d: string[] = [];
    pts.forEach((p, i) => {
      const v = pick(p, i);
      if (v == null) return;
      d.push(`${d.length ? "L" : "M"}${x(i)},${y(v)}`);
    });
    return d.join(" ");
  };
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Serie real versus pronóstico">
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#d9d6d1" />
      <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="#d9d6d1" />
      <text x={pad} y={14} fontSize="11" fill="#5c5c5c">Unidades</text>
      <text x={w / 2} y={h - 6} fontSize="11" fill="#5c5c5c" textAnchor="middle">Periodo</text>
      <path d={line((p) => p.actual)} fill="none" stroke="#1c1c1c" strokeWidth="2" />
      <path d={line((p) => p.forecast)} fill="none" stroke="#5c5c5c" strokeWidth="1.5" />
      <path d={line((p) => product.correctedForecast[p.date] ?? null)} fill="none" stroke="#1c1c1c" strokeWidth="1.5" strokeDasharray="4 3" />
    </svg>
  );
}

function serialize(report: PortfolioReport) {
  return {
    health: report.health,
    discardedShare: report.discardedShare,
    reviewShare: report.reviewShare,
    wape: report.wape,
    bias: report.bias,
    products: report.products.map((p) => ({
      sku: p.productId,
      producto: p.productName,
      modelo: p.model,
      veredicto: p.verdict,
      salud: p.health,
      metricas: Object.fromEntries(p.metrics.map((m) => [m.id, m.value])),
      modelo_recomendado: p.recommended,
      senales: p.flags,
      consejos: p.tips,
    })),
  };
}

function download(name: string, body: string) {
  const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
