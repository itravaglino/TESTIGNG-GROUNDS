import { useEffect, useMemo, useState } from 'react';
import { analyzePortfolio } from '../lib/analyze';
import { auditCsv, correctedCsv } from '../lib/export';
import { parseCsv, parseXlsx } from '../lib/parse';
import { sampleProducts, templateCsv } from '../lib/sample';
import type { Decision, ParseResult, PortfolioReport, ProductReport } from '../lib/types';

type Filter = 'todos' | Decision;

const DECISION_LABEL: Record<Decision, string> = {
  mantener: 'Mantener',
  corregir: 'Corregir',
  descartar: 'Descartar',
};

export function App() {
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [report, setReport] = useState<PortfolioReport | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('todos');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [fileName, setFileName] = useState('');

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('ejemplo') === '1') loadSample();
  }, []);

  const selected = report?.products.find((product) => product.productId === selectedId) ?? null;
  const visible = useMemo(() => {
    if (!report) return [];
    const needle = query.trim().toLowerCase();
    return report.products.filter((product) => {
      const matchesFilter = filter === 'todos' || product.decision === filter;
      const matchesQuery =
        !needle ||
        product.productName.toLowerCase().includes(needle) ||
        product.productId.toLowerCase().includes(needle) ||
        product.category.toLowerCase().includes(needle);
      return matchesFilter && matchesQuery;
    });
  }, [report, filter, query]);

  async function onFile(file: File) {
    setError('');
    try {
      const lower = file.name.toLowerCase();
      const result = lower.endsWith('.csv') || lower.endsWith('.txt')
        ? parseCsv(await file.text())
        : await parseXlsx(await file.arrayBuffer());
      if (!result.products.length) {
        setError(result.warnings[0]?.message ?? 'No pude leer productos de ese archivo.');
        return;
      }
      publish(result, file.name);
    } catch {
      setError('Ese archivo no se pudo leer. Usá CSV o Excel con encabezados.');
    }
  }

  function publish(result: ParseResult, name: string) {
    const next = analyzePortfolio(result.products);
    setParseResult(result);
    setReport(next);
    setFileName(name);
    setSelectedId(next.products[0]?.productId ?? null);
    setFilter('todos');
    setQuery('');
  }

  function loadSample() {
    const products = sampleProducts();
    publish(
      {
        products,
        mapping: {},
        headers: ['producto', 'nombre', 'categoria', 'fecha', 'pronostico', 'real'],
        warnings: [{ level: 'info', message: 'Estás viendo 8 productos de ejemplo, uno por tipo de problema.' }],
        droppedRows: 0,
        sheetName: null,
      },
      'ejemplo-lupa.csv',
    );
  }

  return (
    <div className="page">
      <header className="top">
        <div>
          <p className="eyebrow">Laboratorio de pronósticos</p>
          <h1>Lupa</h1>
        </div>
        <p className="lede">
          Subí un forecast por producto y período. Lupa mide el error, separa lo que se puede usar, corrige lo que tiene arreglo y deja en blanco lo que no debería publicarse.
        </p>
      </header>

      <Upload onFile={onFile} onSample={loadSample} fileName={fileName} />
      {error ? <p className="banner bad">{error}</p> : null}
      {parseResult && report ? <Warnings result={parseResult} /> : null}

      {!report ? <FormatGuide /> : null}
      {report ? (
        <>
          <Summary report={report} />
          <section className="panel">
            <div className="toolbar">
              <div className="filters" role="tablist" aria-label="Filtrar por decisión">
                <FilterButton current={filter} id="todos" count={report.totals.products} onClick={setFilter} label="Todos" />
                <FilterButton current={filter} id="descartar" count={report.totals.descartar} onClick={setFilter} label="Descartar" />
                <FilterButton current={filter} id="corregir" count={report.totals.corregir} onClick={setFilter} label="Corregir" />
                <FilterButton current={filter} id="mantener" count={report.totals.mantener} onClick={setFilter} label="Mantener" />
              </div>
              <label className="search">
                Buscar
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Producto, código o categoría" />
              </label>
              <div className="exports">
                <button type="button" onClick={() => download('lupa-auditoria.csv', auditCsv(report))}>Auditoría</button>
                <button type="button" onClick={() => download('lupa-corregido.csv', correctedCsv(report))}>Forecast corregido</button>
              </div>
            </div>
            <div className="split">
              <ProductTable products={visible} selectedId={selectedId} onSelect={setSelectedId} />
              {selected ? <ProductDetail product={selected} /> : <p className="empty">Ningún producto coincide con ese filtro.</p>}
            </div>
          </section>
          <ProcessNotes notes={report.processNotes} thresholds={report.thresholds} />
        </>
      ) : null}
    </div>
  );
}

function Upload({ onFile, onSample, fileName }: { onFile: (file: File) => void; onSample: () => void; fileName: string }) {
  return (
    <section
      className="drop"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const file = event.dataTransfer.files?.[0];
        if (file) onFile(file);
      }}
    >
      <div>
        <h2>{fileName || 'Arrastrá un CSV o Excel'}</h2>
        <p>El cálculo queda en el navegador. Columnas mínimas: producto, fecha y pronóstico. Si agregás la venta real, también mide precisión.</p>
      </div>
      <div className="actions">
        <label className="primary">
          Elegir archivo
          <input
            type="file"
            accept=".csv,.txt,.xlsx,.xls"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) onFile(file);
            }}
          />
        </label>
        <button type="button" onClick={onSample}>Cargar ejemplo</button>
        <button type="button" onClick={() => download('plantilla-lupa.csv', `\uFEFF${templateCsv()}`)}>Descargar plantilla</button>
      </div>
    </section>
  );
}

function Warnings({ result }: { result: ParseResult }) {
  if (!result.warnings.length && !result.droppedRows) return null;
  return (
    <ul className="warnings">
      {result.warnings.map((warning) => (
        <li key={warning.message} className={warning.level}>{warning.message}</li>
      ))}
      {result.droppedRows ? <li className="alerta">Se omitieron {result.droppedRows} filas sin producto, fecha o números.</li> : null}
    </ul>
  );
}

function FormatGuide() {
  return (
    <section className="guide">
      <h2>Formato que entiende</h2>
      <p>Una fila por producto y período. Acepta coma, punto y coma o tab, y encabezados en español o inglés.</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>producto</th>
              <th>nombre</th>
              <th>categoria</th>
              <th>fecha</th>
              <th>pronostico</th>
              <th>real</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>SKU-001</td>
              <td>Yerba 1kg</td>
              <td>Almacén</td>
              <td>2025-01-01</td>
              <td>120</td>
              <td>100</td>
            </tr>
            <tr>
              <td>SKU-001</td>
              <td>Yerba 1kg</td>
              <td>Almacén</td>
              <td>2025-02-01</td>
              <td>110</td>
              <td>108</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="fine">También reconoce sku, código, material, semana, demanda, venta, piso y techo. Fechas como 2025-01-01, 01/02/2025 o 2025-03.</p>
    </section>
  );
}

function Summary({ report }: { report: PortfolioReport }) {
  return (
    <section className="kpis" aria-label="Resumen del portafolio">
      <Kpi label="Productos" value={String(report.totals.products)} />
      <Kpi label="Descartar" value={String(report.totals.descartar)} tone="bad" />
      <Kpi label="Corregir" value={String(report.totals.corregir)} tone="warn" />
      <Kpi label="Mantener" value={String(report.totals.mantener)} tone="ok" />
      <Kpi label="WAPE original" value={percent(report.totals.wape)} />
      <Kpi label="WAPE publicado" value={percent(report.totals.wapeCorrected)} />
      <p className="fine span">El WAPE publicado es el del archivo corregido, ponderado por venta. Los productos descartados quedan afuera porque no llevan número.</p>
    </section>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <article className={tone ? `kpi ${tone}` : 'kpi'}>
      <p>{label}</p>
      <strong>{value}</strong>
    </article>
  );
}

function FilterButton({
  current,
  id,
  count,
  label,
  onClick,
}: {
  current: Filter;
  id: Filter;
  count: number;
  label: string;
  onClick: (id: Filter) => void;
}) {
  return (
    <button type="button" role="tab" aria-selected={current === id} className={current === id ? 'on' : ''} onClick={() => onClick(id)}>
      {label}
      <span>{count}</span>
    </button>
  );
}

function ProductTable({
  products,
  selectedId,
  onSelect,
}: {
  products: ProductReport[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (!products.length) return <p className="empty">Nada para mostrar con ese filtro.</p>;
  return (
    <div className="table-wrap products">
      <table>
        <thead>
          <tr>
            <th>Producto</th>
            <th>Decisión</th>
            <th>Patrón</th>
            <th>WAPE</th>
            <th>Corregido</th>
            <th>Sesgo</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <tr key={product.productId} className={product.productId === selectedId ? 'selected' : ''} onClick={() => onSelect(product.productId)}>
              <td>
                <button type="button" className="rowhit" onClick={() => onSelect(product.productId)}>
                  <strong>{product.productName}</strong>
                  <small>{product.productId} · {product.category}</small>
                </button>
              </td>
              <td><span className={`pill ${product.decision}`}>{DECISION_LABEL[product.decision]}</span></td>
              <td>{product.pattern}</td>
              <td>{percent(product.raw.wape)}</td>
              <td>{percent(product.raw.wapeCorrected)}</td>
              <td>{percent(product.raw.biasPct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProductDetail({ product }: { product: ProductReport }) {
  const groups = ['precisión', 'sesgo', 'valor', 'estructura', 'patrón'] as const;
  return (
    <article className="detail" aria-live="polite">
      <header>
        <div>
          <p className="eyebrow">{product.category} · {product.grain} · confianza {product.confidence}</p>
          <h2>{product.productName}</h2>
          <p className="code">{product.productId}</p>
        </div>
        <span className={`pill ${product.decision}`}>{DECISION_LABEL[product.decision]}</span>
      </header>
      <Chart product={product} />
      <div className="cols">
        <section>
          <h3>Por qué</h3>
          <ul>{product.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </section>
        <section>
          <h3>Cómo mejorarlo</h3>
          <ul>{product.improvements.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      </div>
      {product.corrections.length ? (
        <section>
          <h3>Qué se tocó</h3>
          <ul>{product.corrections.map((item) => <li key={item.id}>{item.detail}</li>)}</ul>
        </section>
      ) : null}
      <section>
        <h3>Modelos</h3>
        <div className="models">
          {product.models.map((model) => (
            <article key={`${model.role}-${model.name}`}>
              <p className="eyebrow">{model.role === 'usar_ahora' ? 'Usar ahora' : model.role === 'siguiente' ? 'Siguiente paso' : 'Evitar'}</p>
              <h4>{model.name}</h4>
              <p>{model.detail}</p>
              {model.wape != null ? <p className="fine">WAPE de un paso {percent(model.wape)}</p> : null}
            </article>
          ))}
        </div>
      </section>
      {groups.map((group) => (
        <section key={group}>
          <h3>{group}</h3>
          <div className="metrics">
            {product.metrics.filter((metric) => metric.group === group).map((metric) => (
              <article key={metric.id} className={metric.tone}>
                <p>{metric.label}</p>
                <strong>{metric.value}</strong>
                <span>{metric.help}</span>
              </article>
            ))}
          </div>
        </section>
      ))}
    </article>
  );
}

function Chart({ product }: { product: ProductReport }) {
  const width = 640;
  const height = 200;
  const pad = 22;
  const rows = product.series;
  const values = rows.flatMap((row) => [row.actual, row.forecast, row.corrected].filter((value): value is number => value != null && Number.isFinite(value)));
  if (values.length < 2 || rows.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (index: number) => pad + (index * (width - pad * 2)) / (rows.length - 1);
  const y = (value: number) => height - pad - ((value - min) / span) * (height - pad * 2);
  const path = (key: 'actual' | 'forecast' | 'corrected') =>
    rows
      .map((row, index) => {
        const value = row[key];
        if (value == null || !Number.isFinite(value)) return null;
        return `${index === 0 || rows[index - 1][key] == null ? 'M' : 'L'} ${x(index).toFixed(1)} ${y(value).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(' ');
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Serie de ${product.productName}`}>
        <path d={path('actual')} className="actual" />
        <path d={path('forecast')} className="forecast" />
        <path d={path('corrected')} className="corrected" />
        <text x={pad} y={14} className="axis">{max.toLocaleString('es-AR', { maximumFractionDigits: 0 })}</text>
        <text x={pad} y={height - 6} className="axis">{min.toLocaleString('es-AR', { maximumFractionDigits: 0 })}</text>
      </svg>
      <figcaption>
        <span><i className="swatch actual" /> Venta real</span>
        <span><i className="swatch forecast" /> Pronóstico original</span>
        <span><i className="swatch corrected" /> Número publicado</span>
        <span>{rows[0].date} a {rows[rows.length - 1].date}</span>
      </figcaption>
    </figure>
  );
}

function ProcessNotes({ notes, thresholds }: { notes: string[]; thresholds: string[] }) {
  return (
    <section className="notes">
      <div>
        <h2>Cómo usar el resultado</h2>
        <ul>{notes.map((note) => <li key={note}>{note}</li>)}</ul>
      </div>
      <div>
        <h2>Reglas de corte</h2>
        <ul>{thresholds.map((note) => <li key={note}>{note}</li>)}</ul>
      </div>
    </section>
  );
}

function percent(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('es-AR', { style: 'percent', maximumFractionDigits: 1 }).format(value);
}

function download(filename: string, contents: string) {
  const blob = new Blob([contents], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
