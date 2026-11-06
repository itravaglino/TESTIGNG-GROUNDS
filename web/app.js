const estadoVacio = document.querySelector("#vacio");
const trabajo = document.querySelector("#trabajo");
const cuerpoTabla = document.querySelector("#cuerpo-tabla");
const ficha = document.querySelector("#ficha");
let resultado = null;
let filtro = "TODOS";
let consulta = "";
let orden = null;
let elegido = null;

const AYUDA_SBC = "Clasifica la demanda según qué tan seguida y qué tan variable es.";

function fmt(valor, digitos = 3) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  if (typeof valor !== "number") return String(valor);
  return valor.toLocaleString("es-AR", { maximumFractionDigits: digitos });
}

function pct(valor) {
  if (valor === null || valor === undefined) return "—";
  return (valor * 100).toLocaleString("es-AR", { maximumFractionDigits: 1 }) + "%";
}

async function cargarEjemplo() {
  const respuesta = await fetch("/api/ejemplo");
  if (!respuesta.ok) return mostrarError(await respuesta.json());
  pintar(await respuesta.json(), "ejemplo incluido");
}

async function subir(archivo) {
  const datos = new FormData();
  datos.append("archivo", archivo);
  const respuesta = await fetch("/api/auditar", { method: "POST", body: datos });
  const cuerpo = await respuesta.json();
  if (!respuesta.ok) return mostrarError(cuerpo);
  pintar(cuerpo, archivo.name);
}

function mostrarError(cuerpo) {
  const texto = cuerpo.error || "No se pudo leer el archivo.";
  const lectura = document.querySelector("#lectura");
  estadoVacio.hidden = false;
  trabajo.hidden = true;
  alert(texto);
}

function pintar(data, nombre) {
  resultado = data;
  elegido = data.productos[0]?.producto || null;
  orden = null;
  estadoVacio.hidden = true;
  trabajo.hidden = false;
  document.querySelector("#archivo-activo").textContent = nombre;
  document.querySelector("#btn-dictamen").disabled = false;
  document.querySelector("#btn-corregido").disabled = false;
  const lectura = data.lectura;
  const avisos = (lectura.avisos || []).map((a) => `<span class="aviso">${a}</span>`).join("");
  document.querySelector("#lectura").innerHTML = `
    <span>${lectura.filas} filas</span>
    <span>${lectura.productos} productos</span>
    <span>${lectura.fecha_min} → ${lectura.fecha_max}</span>
    <span>${Object.entries(lectura.columnas).map(([k, v]) => `${k} → ${v}`).join(" · ") || "columnas mapeadas"}</span>
    ${avisos}`;
  const p = data.portafolio;
  document.querySelector("#conteos").innerHTML = ["MANTENER", "CORREGIR", "DESCARTAR"].map((estado) => {
    const n = p[estado.toLowerCase()];
    return `<div class="tarjeta ${estado}"><button type="button" data-filtro="${estado}"><strong>${n}</strong><span>${estado}</span></button></div>`;
  }).join("");
  document.querySelector("#globales").innerHTML = `
    <div class="tarjeta"><strong>${pct(p.wape)}</strong><span>WAPE del archivo</span><span class="ayuda">Error absoluto pesado por el volumen, con los descartados adentro. Más bajo, mejor.</span></div>
    <div class="tarjeta"><strong>${pct(p.wape_usable)}</strong><span>WAPE usable</span><span class="ayuda">Mismos productos que se mantienen, más los corregidos. Los descartados no entran.</span></div>
    <div class="tarjeta"><strong>${pct(p.sesgo)}</strong><span>Sesgo global</span><span class="ayuda">Positivo: el forecast se pasa. Negativo: se queda corto.</span></div>
    <div class="tarjeta"><strong>${pct(p.fva_vs_naive)}</strong><span>FVA vs naive</span><span class="ayuda">Positivo: el forecast le gana a repetir la demanda reciente.</span></div>`;
  document.querySelector("#filtros").innerHTML = ["TODOS", "MANTENER", "CORREGIR", "DESCARTAR"]
    .map((estado) => `<button type="button" data-filtro="${estado}" class="${filtro === estado ? "activo" : ""}">${estado === "TODOS" ? "Todos" : estado}</button>`)
    .join("");
  renderTabla();
  renderFicha();
}

function productosVisibles() {
  let filas = resultado.productos.slice();
  if (filtro !== "TODOS") filas = filas.filter((p) => p.estado === filtro);
  if (consulta) filas = filas.filter((p) => p.producto.toLowerCase().includes(consulta));
  if (orden) {
    const { col, dir } = orden;
    filas.sort((a, b) => {
      const va = a[col] ?? "";
      const vb = b[col] ?? "";
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }
  return filas;
}

function renderTabla() {
  const filas = productosVisibles();
  cuerpoTabla.innerHTML = filas.map((p) => `
    <tr data-prod="${p.producto}" class="${p.producto === elegido ? "elegida" : ""}" tabindex="0">
      <td>${p.producto}</td>
      <td title="${AYUDA_SBC}">${p.clase_sbc || "—"}</td>
      <td><span class="estado ${p.estado}">${p.estado}</span></td>
      <td>${p.modelo_recomendado}</td>
      <td>${p.modelo_respaldo}</td>
      <td class="num">${pct(p.wape)}</td>
      <td class="num">${fmt(p.mase)}</td>
      <td class="num">${pct(p.sesgo)}</td>
      <td>${p.problema_principal}</td>
      <td>${p.accion}</td>
    </tr>`).join("");
  document.querySelector("#buscar").setAttribute("aria-description", `${filas.length} productos`);
}

function chart(serie) {
  const nums = serie.flatMap((p) => [p.actual, p.forecast, p.forecast_corregido, p.baseline]).filter((v) => typeof v === "number");
  if (!nums.length) return "";
  const ordenados = nums.slice().sort((a, b) => a - b);
  const mediana = ordenados[Math.floor(ordenados.length / 2)] || 1;
  const paraEscala = nums.filter((v) => Math.abs(v) <= Math.abs(mediana) * 8);
  const base = paraEscala.length >= 2 ? paraEscala : nums;
  const min = Math.min(...base);
  const max = Math.max(...base);
  const span = max - min || 1;
  const w = 520;
  const h = 140;
  const x = (i) => (serie.length === 1 ? w / 2 : (i / (serie.length - 1)) * (w - 16) + 8);
  const y = (v) => h - 12 - ((v - min) / span) * (h - 24);
  const linea = (clave, color) => {
    const puntos = serie.map((p, i) => (typeof p[clave] === "number" ? `${x(i)},${y(p[clave])}` : null)).filter(Boolean);
    return puntos.length ? `<polyline fill="none" stroke="${color}" stroke-width="2" points="${puntos.join(" ")}" />` : "";
  };
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Serie del producto">
    ${linea("actual", "#1c1915")}
    ${linea("forecast", "#8d2433")}
    ${linea("forecast_corregido", "#8a5a12")}
    ${linea("baseline", "#0f6a45")}
  </svg>
  <p class="ayuda">Negro: venta. Rojo: forecast original. Ámbar: corregido. Verde: baseline del modelo recomendado.</p>`;
}

function renderFicha() {
  const p = resultado.productos.find((item) => item.producto === elegido) || resultado.productos[0];
  if (!p) {
    ficha.innerHTML = "<p>Sin productos.</p>";
    return;
  }
  elegido = p.producto;
  const grupos = {};
  for (const met of p.catalogo || []) {
    if (met.valor === null || met.valor === undefined) continue;
    grupos[met.grupo] = grupos[met.grupo] || [];
    const valor = ["wape", "smape", "mape", "pbias", "mpe", "me", "fva_rel", "hit_10", "hit_20", "mda", "bias_ratio", "mean_ratio", "cv_ratio", "pearson", "r2", "picp"].includes(met.id) && Math.abs(met.valor) <= 5
      ? (["mae", "rmse", "mse", "medae", "me"].includes(met.id) ? fmt(met.valor) : pct(met.valor))
      : fmt(met.valor);
    grupos[met.grupo].push(`<div class="metrica" title="${met.ayuda}"><span>${met.id}</span><b>${valor}</b><span class="ayuda">${met.ayuda}</span></div>`);
  }
  const bloques = Object.entries(grupos).map(([nombre, items]) => `<div class="grupo"><h3>${nombre}</h3><div class="metricas">${items.join("")}</div></div>`).join("");
  const hallazgos = (p.hallazgos || []).map((h) => `<p><span class="severidad ${h.severidad}">${h.severidad}</span> ${h.mensaje}</p>`).join("");
  const no = (p.modelos_que_no || []).map((m) => `<p class="no">${m}</p>`).join("");
  const leyendaCorr = p.estado === "DESCARTAR"
    ? "Sin número usable. El dictamen es DESCARTAR."
    : p.estado === "MANTENER"
      ? "Se conserva el forecast original."
      : "El número de plan es el forecast corregido.";
  ficha.innerHTML = `
    <p class="estado ${p.estado}">${p.estado}</p>
    <h2>${p.producto}</h2>
    <p>${p.clase_sbc || "sin clase"} · ${p.categoria || "sin categoría"} · origen ${p.modelo_origen || "sin modelo"}</p>
    <p><strong>${p.modelo_recomendado}</strong> · respaldo ${p.modelo_respaldo}</p>
    <p>${p.por_que_modelo}</p>
    ${chart(p.serie)}
    <div class="grupo"><h3>Serie</h3><p class="ayuda">${leyendaCorr}</p>
      <table class="serie"><thead><tr><th>Fecha</th><th>Actual</th><th>Forecast original</th><th>Forecast corregido</th><th>Baseline</th></tr></thead>
      <tbody>${p.serie.map((s) => `<tr><td>${s.fecha}</td><td class="num">${fmt(s.actual, 2)}</td><td class="num">${fmt(s.forecast, 2)}</td><td class="num">${fmt(s.forecast_corregido, 2)}</td><td class="num">${fmt(s.baseline, 2)}</td></tr>`).join("")}</tbody></table>
    </div>
    ${bloques || "<p>Sin métricas de error: no hay venta real.</p>"}
    <div class="grupo"><h3>Hallazgos</h3>${hallazgos}</div>
    <div class="grupo"><h3>Cómo mejorarlo</h3><p>${p.como_mejorarlo}</p></div>
    <div class="grupo"><h3>Modelos que sí encajan</h3><p>${p.modelo_recomendado}. ${p.por_que_modelo}</p><p>Respaldo: ${p.modelo_respaldo}.</p></div>
    <div class="grupo"><h3>Modelos que no usar</h3>${no}</div>
    <div class="grupo"><h3>Próximos periodos sugeridos</h3>
      <p class="ayuda">${(p.sugerido_futuro || []).map((s) => `${s.fecha}: ${fmt(s.valor, 2)}`).join(" · ") || "Sin proyección."}</p>
    </div>`;
}

function csv(filas) {
  const cols = Object.keys(filas[0]);
  const linea = (fila) => cols.map((c) => {
    const valor = fila[c] === null || fila[c] === undefined ? "" : String(fila[c]);
    return `"${valor.replaceAll('"', '""')}"`;
  }).join(";");
  return "\ufeff" + [cols.join(";"), ...filas.map(linea)].join("\n");
}

function descargar(nombre, contenido) {
  const blob = new Blob([contenido], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  a.click();
  URL.revokeObjectURL(url);
}

document.querySelector("#btn-ejemplo").addEventListener("click", cargarEjemplo);
function abrirPrecarga() {
  if (!window.__PRELOAD) return;
  pintar(window.__PRELOAD, "ejemplo incluido");
  const hash = location.hash.replace("#", "");
  if (hash) {
    elegido = decodeURIComponent(hash);
    renderTabla();
    renderFicha();
  }
}
abrirPrecarga();
if (!window.__PRELOAD && new URLSearchParams(location.search).has("ejemplo")) cargarEjemplo();
document.querySelector("#archivo").addEventListener("change", (evento) => {
  if (evento.target.files[0]) subir(evento.target.files[0]);
});
const drop = document.querySelector("#drop");
drop.addEventListener("dragover", (evento) => { evento.preventDefault(); drop.classList.add("sobre"); });
drop.addEventListener("dragleave", () => drop.classList.remove("sobre"));
drop.addEventListener("drop", (evento) => {
  evento.preventDefault();
  drop.classList.remove("sobre");
  if (evento.dataTransfer.files[0]) subir(evento.dataTransfer.files[0]);
});
document.body.addEventListener("click", (evento) => {
  const filtroBtn = evento.target.closest("[data-filtro]");
  if (filtroBtn && resultado) {
    filtro = filtroBtn.dataset.filtro;
    document.querySelectorAll("#filtros button").forEach((b) => b.classList.toggle("activo", b.dataset.filtro === filtro));
    renderTabla();
  }
  const fila = evento.target.closest("tbody tr");
  if (fila) {
    elegido = fila.dataset.prod;
    renderTabla();
    renderFicha();
  }
});
document.querySelector("#buscar").addEventListener("input", (evento) => {
  consulta = evento.target.value.trim().toLowerCase();
  renderTabla();
});
document.querySelector("#btn-orden").addEventListener("click", () => { orden = null; renderTabla(); });
document.querySelectorAll("#tabla th").forEach((th) => {
  th.addEventListener("click", () => {
    if (!th.dataset.col) return;
    const dir = orden && orden.col === th.dataset.col ? -orden.dir : 1;
    orden = { col: th.dataset.col, dir };
    renderTabla();
  });
});
document.querySelector("#btn-dictamen").addEventListener("click", () => {
  const filas = resultado.productos.map((p) => ({
    producto: p.producto,
    clase_sbc: p.clase_sbc,
    dictamen: p.estado,
    modelo_recomendado: p.modelo_recomendado,
    modelo_respaldo: p.modelo_respaldo,
    wape: p.wape ?? "",
    mase: p.mase ?? "",
    sesgo: p.sesgo ?? "",
    problema_principal: p.problema_principal,
    accion: p.accion,
    como_mejorarlo: p.como_mejorarlo,
  }));
  descargar("dictamen.csv", csv(filas));
});
document.querySelector("#btn-corregido").addEventListener("click", () => {
  const filas = [];
  for (const p of resultado.productos) {
    for (const s of p.serie) {
      filas.push({
        producto: p.producto,
        fecha: s.fecha,
        forecast: s.forecast ?? "",
        forecast_corregido: p.estado === "CORREGIR" && s.forecast_corregido !== null ? s.forecast_corregido : "",
        dictamen: p.estado,
      });
    }
  }
  descargar("forecast_corregido.csv", csv(filas));
});
