export type Severity = "info" | "warn" | "error" | "fatal";
export type Verdict = "keep" | "correct" | "discard";
export type DemandClass = "smooth" | "intermittent" | "erratic" | "lumpy" | "unknown";

export type ColumnRole =
  | "product"
  | "date"
  | "forecast"
  | "actual"
  | "model"
  | "channel"
  | "warehouse"
  | "lower"
  | "upper"
  | "unit";

export interface ColumnMap {
  product?: string;
  date?: string;
  forecast?: string;
  actual?: string;
  model?: string;
  channel?: string;
  warehouse?: string;
  lower?: string;
  upper?: string;
  unit?: string;
}

export interface ParsedRow {
  product: string;
  date: string;
  period: Date;
  forecast: number | null;
  actual: number | null;
  model: string | null;
  channel: string | null;
  warehouse: string | null;
  lower: number | null;
  upper: number | null;
  unit: string | null;
  sourceLine: number;
}

export interface ParseIssue {
  severity: Severity;
  message: string;
  line?: number;
}

export interface ParseResult {
  format: "long" | "wide";
  delimiter: string;
  decimalComma: boolean;
  map: ColumnMap;
  headers: string[];
  rows: ParsedRow[];
  skipped: number;
  issues: ParseIssue[];
}

export interface Issue {
  id: string;
  severity: Severity;
  message: string;
  autoFixed: boolean;
}

export interface Correction {
  id: string;
  message: string;
  count: number;
}

export interface MetricValue {
  id: string;
  label: string;
  value: number | null;
  unit: "qty" | "pct" | "ratio" | "none";
  better: "low" | "high" | "zero";
  note?: string;
}

export interface ModelRec {
  id: string;
  name: string;
  fit: "alta" | "media" | "baja";
  why: string;
  howToStart: string;
  caution: string;
  libs: string[];
}

export interface Point {
  date: string;
  period: Date;
  forecastRaw: number | null;
  forecast: number | null;
  actual: number | null;
  lower: number | null;
  upper: number | null;
}

export interface ProductReport {
  key: string;
  product: string;
  channel: string | null;
  warehouse: string | null;
  modelHint: string | null;
  n: number;
  nActual: number;
  nForecast: number;
  frequency: "daily" | "weekly" | "monthly" | "quarterly" | "unknown";
  demandClass: DemandClass;
  adi: number | null;
  cv2: number | null;
  seasonalLag: number | null;
  hasTrend: boolean;
  verdict: Verdict;
  score: number;
  issues: Issue[];
  corrections: Correction[];
  metrics: MetricValue[];
  models: ModelRec[];
  improvements: string[];
  series: Point[];
}

export interface PortfolioSummary {
  products: number;
  rows: number;
  keep: number;
  correct: number;
  discard: number;
  wape: number | null;
  bias: number | null;
  mape: number | null;
  mae: number | null;
  skillNaive: number | null;
}

export interface QaReport {
  parse: ParseResult;
  products: ProductReport[];
  portfolio: PortfolioSummary;
  generatedAt: string;
}
