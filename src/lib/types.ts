export type Decision = 'mantener' | 'corregir' | 'descartar';
export type Confidence = 'alta' | 'media' | 'baja';
export type Pattern = 'suave' | 'errática' | 'intermitente' | 'irregular' | 'insuficiente';
export type Grain = 'diaria' | 'semanal' | 'mensual' | 'trimestral' | 'irregular';

export type CanonicalPoint = {
  date: string;
  forecast: number | null;
  actual: number | null;
  lower: number | null;
  upper: number | null;
};

export type ProductInput = {
  productId: string;
  productName: string;
  category: string;
  points: CanonicalPoint[];
  duplicateDates?: number;
};

export type ColumnKey =
  | 'productId'
  | 'productName'
  | 'category'
  | 'date'
  | 'forecast'
  | 'actual'
  | 'lower'
  | 'upper';

export type ColumnMapping = Partial<Record<ColumnKey, number>>;

export type ParseWarning = { level: 'info' | 'alerta'; message: string };

export type ParseResult = {
  products: ProductInput[];
  mapping: ColumnMapping;
  headers: string[];
  warnings: ParseWarning[];
  droppedRows: number;
  sheetName: string | null;
};

export type MetricTone = 'ok' | 'warn' | 'bad' | 'neutro';

export type MetricView = {
  id: string;
  group: 'precisión' | 'sesgo' | 'valor' | 'estructura' | 'patrón';
  label: string;
  value: string;
  help: string;
  tone: MetricTone;
};

export type Correction = {
  id:
    | 'clip_negativos'
    | 'winsorizar'
    | 'ajuste_sesgo'
    | 'llenar_huecos'
    | 'reemplazo_proyeccion'
    | 'promedio_duplicados';
  detail: string;
};

export type ModelCard = {
  role: 'usar_ahora' | 'siguiente' | 'evitar';
  name: string;
  detail: string;
  wape: number | null;
};

export type SeriesRow = {
  date: string;
  actual: number | null;
  forecast: number | null;
  corrected: number | null;
  origin: 'original' | 'ajustado' | 'reemplazo' | 'vacio';
};

export type ProductReport = {
  productId: string;
  productName: string;
  category: string;
  decision: Decision;
  confidence: Confidence;
  pattern: Pattern;
  grain: Grain;
  season: number;
  reasons: string[];
  improvements: string[];
  corrections: Correction[];
  models: ModelCard[];
  metrics: MetricView[];
  raw: {
    overlap: number;
    periods: number;
    gaps: number;
    duplicates: number;
    negativeShare: number;
    wape: number | null;
    wapeCorrected: number | null;
    biasPct: number | null;
    mase: number | null;
    fvaNaive: number | null;
    correlation: number | null;
    bestBaseline: string | null;
    bestBaselineWape: number | null;
  };
  series: SeriesRow[];
};

export type PortfolioReport = {
  products: ProductReport[];
  totals: {
    products: number;
    mantener: number;
    corregir: number;
    descartar: number;
    wape: number | null;
    wapeCorrected: number | null;
    volume: number;
  };
  processNotes: string[];
  thresholds: string[];
};
