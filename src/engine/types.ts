export type Cadence = "day" | "week" | "month" | "quarter" | "irregular";

export type IntermittencyClass = "smooth" | "erratic" | "intermittent" | "lumpy";

export type Severity = "info" | "warn" | "error" | "fatal";

export type Verdict = "keep" | "correct" | "discard";

export type ColumnRole =
  | "product_id"
  | "product_name"
  | "date"
  | "forecast"
  | "actual"
  | "location"
  | "model"
  | "price"
  | "lower"
  | "upper"
  | "ignore";

export interface ForecastPoint {
  date: Date;
  isoDate: string;
  forecast: number;
  actual?: number;
  lower?: number;
  upper?: number;
  price?: number;
  model?: string;
  raw: Record<string, string>;
}

export interface ForecastRow {
  productId: string;
  productName: string;
  location: string;
  point: ForecastPoint;
}

export interface ParseError {
  row: number;
  message: string;
}

export interface FormatReport {
  delimiter: string;
  headers: string[];
  mapping: Record<string, ColumnRole>;
  unmappedHeaders: string[];
  rowCount: number;
  acceptedRows: number;
  errors: ParseError[];
  hasActuals: boolean;
}

export interface ParseResult {
  rows: ForecastRow[];
  report: FormatReport;
}

export interface Issue {
  code: string;
  severity: Severity;
  title: string;
  detail: string;
  howToFix: string;
  affectedDates?: string[];
}

export interface Correction {
  code: string;
  description: string;
  pointsChanged: number;
}

export interface SeriesProfile {
  n: number;
  cadence: Cadence;
  stepDays: number;
  seasonalPeriod: number;
  hasTrend: boolean;
  trendSlope: number;
  seasonalStrength: number;
  intermittency: IntermittencyClass;
  adi: number;
  cv2: number;
  meanDemand: number;
  cv: number;
  isNewProduct: boolean;
  promotionsLikely: boolean;
}

export interface Metrics {
  n: number;
  nWithActual: number;
  meanForecast: number;
  meanActual: number | null;
  mae: number | null;
  mse: number | null;
  rmse: number | null;
  mape: number | null;
  smape: number | null;
  wape: number | null;
  mdape: number | null;
  mase: number | null;
  rmsse: number | null;
  me: number | null;
  mpe: number | null;
  biasPct: number | null;
  trackingSignal: number | null;
  theilU1: number | null;
  theilU2: number | null;
  r2: number | null;
  rmsePct: number | null;
  hitRate10: number | null;
  hitRate20: number | null;
  underForecastRate: number | null;
  overForecastRate: number | null;
  piCoverage: number | null;
  pinaw: number | null;
  zeroForecastRate: number;
  demandCv: number | null;
  adi: number;
  cv2: number;
  intermittency: IntermittencyClass;
}

export interface ModelRec {
  id: string;
  name: string;
  score: number;
  whenToUse: string;
  whyThisProduct: string;
  libraries: string;
  hyperparameters: string;
  dataNeeds: string;
  caveats: string;
}

export interface DiscardDecision {
  discard: boolean;
  reason: string;
  keepHint: string;
}

export interface ProductResult {
  key: string;
  productId: string;
  productName: string;
  location: string;
  verdict: Verdict;
  quality: number;
  profile: SeriesProfile;
  original: ForecastPoint[];
  corrected: ForecastPoint[];
  issues: Issue[];
  corrections: Correction[];
  metricsOriginal: Metrics;
  metricsCorrected: Metrics;
  discard: DiscardDecision;
  models: ModelRec[];
  improvements: string[];
}

export interface PipelineResult {
  report: FormatReport;
  products: ProductResult[];
  summary: {
    total: number;
    keep: number;
    correct: number;
    discard: number;
    medianWape: number | null;
    withActuals: number;
  };
}
