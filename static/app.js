const state = { report: null, filter: "todos", query: "", selected: null };

const $ = (id) => document.getElementById(id);

const VERDICT = { mantener: "Mantener", corregir: "Corregir", descartar: "Descartar" };

function pct(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "s/d";
  return `${(value * 100).toLocaleString("es-AR", { maximumFractionDigits: 1 })}%`;
}

function num(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "s/d";
  const abs = Math.abs(value);
  const digits = abs >= 100 ? 1 : abs >= 10 ? 2 : 3;
  return value.toLocaleString("es-AR", { maximumFractionDigits: digits });
}

function formatMetric(metric) {
  if (metric.valor === null || metric.valor === undefined) return "s/d";
  return metric.formato === "pct" ? pct(metric.valor) : num(metric.valor);
}

function metricValue(product, listName, id) {
  const found = (product[listName] || []).find((item) => item.id === id);
  return found ? found.valor : null;
}

async function load(source) {
  $("error").hidden = true;
  try {
    const response = source instanceof FormData
      ? await fetch("/api/auditar", { method: "POST", body: source })
      : await fetch(source);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "No pude auditar el archivo.");
    state.report = body;
    state.selected = body.productos[0] ? body.productos[0].id : null;
    $("loader").hidden = true;
    $("work").hidden = false;
    render();
  } catch (error) {
    $("error").hidden = false;
    $("error").textContent = error.message;
  }
}

function visibleProducts() {
  const query = state.query.trim().toLowerCase();
  return state.report.productos.filter((product) => {
    const filterOk = state.filter === "todos" || product.veredicto === state.filter;
    const text = `${product.producto} ${product.modelo_declarado || ""}`.toLowerCase();
    return filterOk && (!query || text.includes(query));
  });
}

function render() {
  const report = state.report;
  const summary = $("summary");
  summary.replaceChildren();
  const cards = [
    ["Productos", report.resumen.productos],
    ["Corregir", report.resumen.corregir],
    ["Descartar", report.resumen.descartar],
    ["Mantener", report.resumen.mantener],
    ["WMAPE ponderado", pct(report.resumen.wmape_ponderado_antes)],
  ];
  cards.forEach(([label, value]) => {
    const box = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = String(value);
    const span = document.createElement("span");
    span.textContent = label;
    box.append(strong, span);
    summary.append(box);
  });

  const notices = $("notices");
  notices.replaceChildren();
  (report.avisos || []).forEach((text) => {
    const note = document.createElement("div");
    note.className = "notice";
    note.textContent = text;
    notices.append(note);
  });
  $("method").textContent = report.metodologia || "";

  const products = visibleProducts();
  if (products.length && !products.some((product) => product.id === state.selected)) {
    state.selected = products[0].id;
  }
  const list = $("list");
  list.replaceChildren();
  if (!products.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Ningún producto coincide con ese filtro.";
    list.append(empty);
  }
  products.forEach((product) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `item${product.id === state.selected ? " on" : ""}`;
    const top = document.createElement("div");
    top.className = "row";
    const name = document.createElement("strong");
    name.textContent = product.producto;
    const tag = document.createElement("span");
    tag.className = `tag ${product.veredicto}`;
    tag.textContent = VERDICT[product.veredicto];
    top.append(name, tag);
    const meta = document.createElement("small");
    const archivo = metricValue(product, "metricas_historial", "wmape");
    meta.textContent = `${product.modelo_declarado || "Sin modelo"} · puntaje ${product.puntaje} · WMAPE ${pct(product.antes.wmape)}`;
    if (typeof archivo === "number" && Math.abs(archivo - (product.antes.wmape || 0)) > 0.05) {
      meta.textContent += ` · archivo ${pct(archivo)}`;
    }
    button.append(top, meta);
    button.addEventListener("click", () => {
      state.selected = product.id;
      render();
    });
    list.append(button);
  });

  const selected = report.productos.find((product) => product.id === state.selected) || products[0];
  renderDetail(selected);
}

function renderDetail(product) {
  const root = $("detail");
  root.replaceChildren();
  if (!product) return;
  const card = document.createElement("div");
  card.className = "detail-card";

  const tag = document.createElement("span");
  tag.className = `tag ${product.veredicto}`;
  tag.textContent = VERDICT[product.veredicto];
  const title = document.createElement("h2");
  title.textContent = product.producto;
  const sub = document.createElement("p");
  sub.className = "muted";
  const diag = product.diagnostico;
  sub.textContent = [
    product.modelo_declarado ? `Modelo declarado: ${product.modelo_declarado}` : "Sin modelo declarado",
    diag.frecuencia,
    `${diag.inicio || "?"} → ${diag.fin || "?"}`,
    `Demanda ${diag.clase_demanda}`,
    `Confianza ${Math.round(product.confianza * 100)}%`,
  ].join(" · ");

  const kpis = document.createElement("div");
  kpis.className = "kpis";
  [
    ["Puntaje", String(product.puntaje)],
    ["WMAPE validación", pct(product.antes.wmape)],
    ["WMAPE corregido", pct(product.despues.wmape)],
    ["Sesgo", pct(product.antes.bias_pct)],
  ].forEach(([label, value]) => {
    const box = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = value;
    const span = document.createElement("div");
    span.className = "muted";
    span.textContent = label;
    box.append(strong, span);
    kpis.append(box);
  });

  const method = document.createElement("p");
  if (product.veredicto === "descartar") {
    method.textContent = "Este pronóstico se descarta. No lo uses para comprar ni producir.";
  } else if (product.metodo_correccion) {
    method.textContent = `Qué se hace con el número: ${product.metodo_correccion}.`;
  } else {
    method.textContent = "El pronóstico original se deja como está.";
  }

  card.append(tag, title, sub, kpis, method);
  card.append(paragraphList("Por qué", product.motivos));
  card.append(paragraphList("Cómo mejorarlo", product.como_mejorar));

  const canvas = document.createElement("canvas");
  canvas.height = 260;
  const legend = document.createElement("div");
  legend.className = "legend";
  legend.append(legendItem("#1c1915", "Real"), legendItem("#b5523a", "Pronóstico"), legendItem("#1d6b45", "Corregido"));
  card.append(canvas, legend);

  const diagLine = document.createElement("p");
  diagLine.className = "muted";
  diagLine.textContent = [
    `ADI ${fmt(diag.adi)}`,
    `CV² ${fmt(diag.cv2)}`,
    `Estacionalidad ${fmt(diag.estacionalidad)}`,
    diag.hay_tendencia ? "Con tendencia" : "Sin tendencia clara",
    `${diag.fechas_faltantes} fechas faltantes`,
    `${diag.outliers} picos`,
    `${diag.futuros} períodos futuros`,
  ].join(" · ");
  card.append(diagLine);

  card.append(renderMetrics(product));
  card.append(renderModels(product));
  root.append(card);
  requestAnimationFrame(() => draw(canvas, product.serie));
}

function legendItem(color, label) {
  const span = document.createElement("span");
  const swatch = document.createElement("i");
  swatch.className = "swatch";
  swatch.style.background = color;
  span.append(swatch, document.createTextNode(label));
  return span;
}

function paragraphList(title, items) {
  const wrap = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = title;
  wrap.append(heading);
  if (!items || !items.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Sin observaciones extra.";
    wrap.append(empty);
    return wrap;
  }
  const list = document.createElement("ul");
  list.className = "reasons";
  items.forEach((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    list.append(item);
  });
  wrap.append(list);
  return wrap;
}

function renderMetrics(product) {
  const wrap = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = product.validacion ? "Métricas del tramo de validación" : "Métricas del archivo";
  wrap.append(heading);
  const source = product.metricas_validacion.length ? product.metricas_validacion : product.metricas_historial;
  if (!source.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Sin demanda real no hay precisión que medir. Solo se auditó la sanidad del pronóstico.";
    wrap.append(empty);
    return wrap;
  }
  const groups = new Map();
  source.forEach((metric) => {
    if (!groups.has(metric.grupo)) groups.set(metric.grupo, []);
    groups.get(metric.grupo).push(metric);
  });
  const grid = document.createElement("div");
  grid.className = "groups";
  groups.forEach((metrics, name) => {
    const group = document.createElement("section");
    group.className = "group";
    const h = document.createElement("h3");
    h.textContent = name;
    group.append(h);
    metrics.forEach((metric) => {
      const row = document.createElement("div");
      row.className = "metric";
      row.title = metric.ayuda;
      const label = document.createElement("span");
      label.textContent = metric.nombre;
      const value = document.createElement("strong");
      value.textContent = formatMetric(metric);
      const dot = document.createElement("i");
      dot.className = `dot ${metric.estado}`;
      row.append(label, value, dot);
      group.append(row);
    });
    grid.append(group);
  });
  wrap.append(grid);
  if (product.metricas_historial.length && product.validacion) {
    const archivo = metricValue(product, "metricas_historial", "wmape");
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = `WMAPE de todo el archivo, sin recortar el tramo final: ${pct(archivo)}. La validación es la que decide.`;
    wrap.append(note);
  }
  return wrap;
}

function renderModels(product) {
  const wrap = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = "Modelos para el próximo ciclo";
  wrap.append(heading);
  const list = document.createElement("div");
  list.className = "models";
  product.modelos.forEach((model) => {
    const card = document.createElement("div");
    card.className = "model";
    const title = document.createElement("b");
    title.textContent = `${model.prioridad}. ${model.nombre}`;
    const why = document.createElement("p");
    why.textContent = model.por_que;
    const needs = document.createElement("p");
    needs.className = "muted";
    needs.textContent = `Cuándo: ${model.cuando} Necesita: ${model.necesita} Evitar si: ${model.evitar}`;
    card.append(title, why, needs);
    list.append(card);
  });
  wrap.append(list);
  return wrap;
}

function draw(canvas, serie) {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 640;
  const height = 260;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  const values = [];
  serie.forEach((point) => ["real", "pronostico", "corregido"].forEach((key) => {
    if (typeof point[key] === "number") values.push(point[key]);
  }));
  if (!values.length) return;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const pad = 16;
  const x = (index) => pad + (index * (width - pad * 2)) / Math.max(serie.length - 1, 1);
  const y = (value) => height - pad - ((value - min) / (max - min)) * (height - pad * 2);
  [["real", "#1c1915", 2], ["pronostico", "#b5523a", 1.5], ["corregido", "#1d6b45", 1.5]].forEach(([key, color, widthLine]) => {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = widthLine;
    let started = false;
    serie.forEach((point, index) => {
      if (typeof point[key] !== "number") { started = false; return; }
      const px = x(index);
      const py = y(point[key]);
      if (!started) { ctx.moveTo(px, py); started = true; }
      else ctx.lineTo(px, py);
    });
    ctx.stroke();
  });
}

function fmt(value) {
  return typeof value === "number" ? value.toLocaleString("es-AR", { maximumFractionDigits: 2 }) : "s/d";
}

function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.append(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 1000);
}

function toCsv(rows) {
  const headers = ["producto", "modelo_declarado", "fecha", "pronostico_a_usar", "pronostico_original", "real", "veredicto", "metodo", "estado_fecha"];
  const lines = [headers.join(",")];
  rows.forEach((row) => {
    const usable = row.veredicto === "descartar" ? "" : (row.pronostico_corregido ?? "");
    const flat = { ...row, pronostico_a_usar: usable };
    lines.push(headers.map((key) => {
      const value = flat[key] ?? "";
      let text = String(value);
      const numeric = /^-?\d+(\.\d+)?$/.test(text);
      if (!numeric && /^[=+\-@]/.test(text)) text = `'${text}`;
      return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
    }).join(","));
  });
  return lines.join("\n");
}

$("file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("archivo", file);
  load(body);
});

$("sample").addEventListener("click", () => load("/api/ejemplo"));
$("again").addEventListener("click", () => {
  $("work").hidden = true;
  $("loader").hidden = false;
  $("file").value = "";
});
$("search").addEventListener("input", (event) => {
  state.query = event.target.value;
  render();
});
$("filters").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.filter = button.dataset.filter;
  [...$("filters").children].forEach((item) => item.classList.toggle("on", item === button));
  render();
});
$("csv").addEventListener("click", () => {
  const rows = state.report.productos.flatMap((product) => product.exportacion || []);
  download("kalibra-corregido.csv", toCsv(rows), "text/csv");
});
$("json").addEventListener("click", () => {
  const clone = JSON.parse(JSON.stringify(state.report));
  clone.productos.forEach((product) => { delete product.exportacion; delete product.serie; });
  download("kalibra-informe.json", JSON.stringify(clone, null, 2), "application/json");
});

["dragover", "drop"].forEach((name) => {
  $("drop").addEventListener(name, (event) => {
    event.preventDefault();
    if (name === "drop" && event.dataTransfer.files[0]) {
      const body = new FormData();
      body.append("archivo", event.dataTransfer.files[0]);
      load(body);
    }
  });
});

window.addEventListener("resize", () => {
  const canvas = document.querySelector("canvas");
  const product = state.report && state.report.productos.find((item) => item.id === state.selected);
  if (canvas && product) draw(canvas, product.serie);
});
