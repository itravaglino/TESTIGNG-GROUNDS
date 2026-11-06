const nf = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 });
const nf0 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 0 });
const nf3 = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 3 });

export function fmtNum(v: number | null | undefined, digits: "0" | "2" | "3" = "2"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (digits === "0") return nf0.format(v);
  if (digits === "3") return nf3.format(v);
  return nf.format(v);
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${nf.format(v)}%`;
}

export function verdictLabel(v: "keep" | "correct" | "discard"): string {
  if (v === "keep") return "Conservar";
  if (v === "correct") return "Corregir";
  return "Descartar";
}

export function classLabel(v: string): string {
  switch (v) {
    case "smooth":
      return "Suave";
    case "intermittent":
      return "Intermitente";
    case "erratic":
      return "Errática";
    case "lumpy":
      return "Grumosa";
    default:
      return "Sin clasificar";
  }
}

export function freqLabel(v: string): string {
  switch (v) {
    case "daily":
      return "diaria";
    case "weekly":
      return "semanal";
    case "monthly":
      return "mensual";
    case "quarterly":
      return "trimestral";
    default:
      return "desconocida";
  }
}

export function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
