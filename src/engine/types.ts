export type ForecastFrequency = "daily" | "weekly" | "monthly" | "quarterly" | "unknown";

export type IssueSeverity = "info" | "warn" | "error" | "critical";

export type IssueCode =
  | "MISSING_REQUIRED"
  | "UNPARSEABLE_DATE"
  | "UNPARSEABLE_NUMBER"
  | "DUPLICATE_KEY"
  | "NEGATIVE_FORECAST"
  | "NEGATIVE_ACTUAL"
  | "NAN_VALUE"
  | "INFINITE_VALUE"
  | "GAP_IN_SERIES"
  | "CONSTANT_FORECAST"
  | "ALL_ZERO"
  | "SPIKE"
  | "SCALE_SHIFT"
  | "BIAS_SYSTEMATIC"
  | "HIGH_MAPE"
  | "HIGH_WAPE"
  | "HIGH_RMSE"
  | "TRACKING_SIGNAL"
  | "INTERVAL_VIOLATION"
  | "INTERVAL_TOO_NARROW"
  | "INTERVAL_TOO_WIDE"
  | "TOO_SHORT"
  | "INTERMITTENT_MISMATCH"
  | "TREND_EXPLOSION"
  | "SEASONALITY_IGNORED"
  | "HORIZON_INCONSISTENT"
  | "FORECAST_BELOW_FLOOR"
  | "FORECAST_ABOVE_CEILING"
  | "ZERO_ACTUAL_DIVISION"
  | "STALE_PATTERN"
  | "CROSSOVER_NEGATIVE"
  | "LOW_COVERAGE"
  | "OVERFIT_FLAT"
  | "DEMAND_CV_HIGH";

export interface RawRow {
  line: number;
  values: Record<string, string>;
}

export interface CanonicalRow {
  line: number;
  productId: string;
  productName: string;
  date: string;
  timestamp: number;
  forecast: number;
  actual: number | null;
  model: string | null;
  location: string | null;
  channel: string | null;
  horizon: number | null;
  lower: number | null;
  upper: number | null;
  extra: Record<string, string>;
}

export interface ColumnMapping {
  productId: string;
  productName: string | null;
  date: string;
  forecast: string;
  actual: string | null;
  model: string | null;
  location: string | null;
  channel: string | null;
  horizon: string | null;
  lower: string | null;
  upper: string | null;
}

export interface ForecastIssue {
  code: IssueCode;
  severity: IssueSeverity;
  productId: string;
  date: string | null;
  line: number | null;
  message: string;
  howToFix: string;
  metric?: string;
  value?: number | null;
  threshold?: number | null;
}

export interface PointMetrics {
  error: number | null;
  absError: number | null;
  pctError: number | null;
  ape: number | null;
  squaredError: number | null;
  insideInterval: boolean | null;
  intervalWidth: number | null;
}

export interface AccuracyMetrics {
  n: number;
  nWithActual: number;
  me: number | null;
  mae: number | null;
  mse: number | null;
  rmse: number | null;
  mape: number | null;
  smape: number | null;
  wape: number | null;
  mdape: number | null;
  mpe: number | null;
  biasPct: number | null;
  trackingSignal: number | null;
  mase: number | null;
  rmsse: number | null;
  r2: number | null;
  corr: number | null;
  theilU: number | null;
  hitRate: number | null;
  overforecastRate: number | null;
  underforecastRate: number | null;
  coverage: number | null;
  meanIntervalWidth: number | null;
  pinball50: number | null;
  maxAbsError: number | null;
  p90AbsError: number | null;
}

export interface SeriesProfile {
  productId: string;
  productName: string;
  n: number;
  nWithActual: number;
  frequency: ForecastFrequency;
  start: string | null;
  end: string | null;
  meanForecast: number;
  meanActual: number | null;
  stdForecast: number;
  stdActual: number | null;
  cvForecast: number | null;
  cvActual: number | null;
  zeroForecastShare: number;
  zeroActualShare: number | null;
  intermittence: number | null;
  adi: number | null;
  cv2: number | null;
  demandClass: "smooth" | "erratic" | "intermittent" | "lumpy" | "unknown";
  trend: "down" | "flat" | "up" | "explosive" | "unknown";
  seasonalStrength: number | null;
  seasonLength: number | null;
  modelsUsed: string[];
  locations: string[];
  channels: string[];
}

export interface ModelSuggestion {
  id: string;
  name: string;
  score: number;
  why: string;
  libraries: string[];
  whenToUse: string;
  caveats: string;
}

export interface ImprovementAction {
  priority: "alta" | "media" | "baja";
  title: string;
  detail: string;
  expectedGain: string;
}

export type RowDisposition = "keep" | "corrected" | "discarded";

export interface ProcessedRow extends CanonicalRow {
  disposition: RowDisposition;
  originalForecast: number;
  correction: string | null;
  discardReason: string | null;
  point: PointMetrics;
}

export interface ProductReport {
  productId: string;
  productName: string;
  profile: SeriesProfile;
  metrics: AccuracyMetrics;
  issues: ForecastIssue[];
  rows: ProcessedRow[];
  discarded: ProcessedRow[];
  suggestions: ModelSuggestion[];
  improvements: ImprovementAction[];
  verdict: "ok" | "corregir" | "descartar" | "revisar";
  verdictReason: string;
  qualityScore: number;
}

export interface PortfolioSummary {
  products: number;
  rows: number;
  discardedRows: number;
  correctedRows: number;
  productsOk: number;
  productsFix: number;
  productsDiscard: number;
  productsReview: number;
  weightedWape: number | null;
  weightedMape: number | null;
  weightedRmse: number | null;
  meanQualityScore: number;
}

export interface ParseDiagnostic {
  mapping: ColumnMapping;
  delimiter: string;
  header: string[];
  skippedEmpty: number;
  warnings: string[];
}

export interface PipelineResult {
  parse: ParseDiagnostic;
  products: ProductReport[];
  summary: PortfolioSummary;
  issues: ForecastIssue[];
  cleanedCsv: string;
  discardedCsv: string;
  generatedAt: string;
}

export interface QualityGates {
  mapeWarn: number;
  mapeFail: number;
  wapeWarn: number;
  wapeFail: number;
  trackingSignalFail: number;
  minPoints: number;
  spikeZ: number;
  coverageMin: number;
  scaleShiftRatio: number;
}
