export type PeriodType = "day" | "week" | "month" | "quarter" | "year" | "unknown";
export type Verdict = "keep" | "review" | "discard";
export type Severity = "info" | "warn" | "error" | "discard";
export type DemandClass = "smooth" | "erratic" | "intermittent" | "lumpy" | "unknown";

export interface ForecastRow {
  productId: string;
  productName: string | null;
  date: string;
  periodType: PeriodType;
  forecast: number | null;
  actual: number | null;
  model: string;
  lo: number | null;
  hi: number | null;
  attributes: Record<string, string | number | null>;
  sourceRow: number;
}

export interface Diagnostic {
  code: string;
  severity: Severity;
  message: string;
  row?: number;
  column?: string;
}

export interface ParseResult {
  rows: ForecastRow[];
  diagnostics: Diagnostic[];
  delimiter: string;
  orientation: "long" | "wide";
  columnsUsed: string[];
  ignoredColumns: string[];
}

export interface Flag {
  id: string;
  severity: Severity;
  message: string;
}

export interface Mutation {
  code: string;
  message: string;
  affectedDates: string[];
}

export interface Pair {
  date: string;
  actual: number;
  forecast: number;
  lo: number | null;
  hi: number | null;
}

export interface MetricValue {
  id: string;
  name: string;
  value: number | null;
  unit: "units" | "percent" | "ratio" | "count";
  lowerIsBetter: boolean | null;
  defined: boolean;
  note?: string;
}

export interface ModelRec {
  id: string;
  name: string;
  reason: string;
  fallback?: string;
  ensemble: boolean;
}

export interface Tip {
  id: string;
  title: string;
  body: string;
}

export interface ProductReport {
  productId: string;
  productName: string | null;
  model: string;
  attributes: Record<string, string | number | null>;
  points: ForecastRow[];
  correctedForecast: Record<string, number | null>;
  pairs: Pair[];
  flags: Flag[];
  mutations: Mutation[];
  metrics: MetricValue[];
  features: SeriesFeatures;
  verdict: Verdict;
  health: number;
  volume: number;
  recommended: ModelRec;
  challengers: ModelRec[];
  tips: Tip[];
  winnerAmongUploaded?: boolean;
}

export interface SeriesFeatures {
  n: number;
  nPos: number;
  nPairs: number;
  mean: number | null;
  cv: number | null;
  adi: number | null;
  cv2: number | null;
  zerosShare: number | null;
  demandClass: DemandClass;
  trend: boolean;
  seasonal: boolean;
  senSlope: number | null;
  acfSeason: number | null;
  lastShock: boolean;
}

export interface PortfolioReport {
  products: ProductReport[];
  diagnostics: Diagnostic[];
  parse: ParseResult;
  health: number;
  discardedShare: number;
  reviewShare: number;
  wape: number | null;
  bias: number | null;
  cancellationGap: number | null;
  scoredVolume: number;
  unscoredVolumeShare: number;
  periodType: PeriodType;
  productCount: number;
  periodCount: number;
  rowCount: number;
}

export const EPS = 1e-9;
export const ATOL = 1e-6;
export const RTOL = 1e-6;

export function near(a: number, b: number): boolean {
  return Math.abs(a - b) <= ATOL + RTOL * Math.abs(b);
}

export function isFiniteNumber(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x);
}
