export type CellStatus =
  | "empty"
  | "stale"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled"
  | "not_in_run";

export type ColumnKind = "input" | "github" | "http" | "transform" | "llm";

export type StructuredOutputMode = "json_schema" | "json_object" | "prompt_only";

export interface ColumnDefinition {
  id: string;
  key: string;
  label: string;
  kind: ColumnKind;
  width: number;
  position: number;
  depends_on: string[];
  config: Record<string, unknown>;
  prompt?: string | null;
  output_schema: Record<string, unknown>;
}

export type GridSchemaColumn = Omit<ColumnDefinition, "id" | "position">;

export interface Provenance {
  id: string;
  connector: string;
  source_urls: string[];
  artifact_hash?: string | null;
  input_hash?: string | null;
  model?: string | null;
  prompt?: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  duration_ms: number;
  cache_hit: boolean;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface GridCell {
  id: string;
  column_id: string;
  status: CellStatus;
  value: unknown;
  error?: string | null;
  latest_execution_id?: string | null;
  provenance?: Provenance | null;
}

export interface GridRowData {
  id: string;
  position: number;
  cells: GridCell[];
}

export interface GridDetail {
  id: string;
  name: string;
  description: string;
  schema_version: number;
  canvas_layout: Record<string, { x: number; y: number }>;
  columns: ColumnDefinition[];
  rows: GridRowData[];
}

export interface GridSummary {
  id: string;
  name: string;
  description: string;
  template_slug?: string | null;
  schema_version: number;
  row_count: number;
  column_count: number;
  last_run?: RunSummary | null;
  updated_at: string;
}

export interface RunSummary {
  id: string;
  status: string;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  skipped_tasks: number;
  cancelled_tasks: number;
  spent_usd: number;
  reserved_usd: number;
  budget_usd: number;
  force_refresh: boolean;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface CellExecution {
  id: string;
  cell_id: string;
  run_id?: string | null;
  run_task_id?: string | null;
  status: CellStatus;
  value: unknown;
  error?: { code?: string | null; safe_message?: string | null } | null;
  cache_key?: string | null;
  source_fetched_at?: string | null;
  cache_expires_at?: string | null;
  reused_from_execution_id?: string | null;
  created_at: string;
  completed_at?: string | null;
  provenance?: Provenance | null;
}

export interface RunDetail {
  run: RunSummary;
  executions: CellExecution[];
}

export interface RunEvent {
  run_id?: string;
  task_id?: string;
  execution_id?: string;
  status: string;
  created_at: string;
  [key: string]: unknown;
}

export interface ProviderProfile {
  id: string;
  provider_type: "anthropic" | "openai_compatible";
  display_name: string;
  base_url: string;
  default_model: string;
  structured_output_mode: StructuredOutputMode;
  default_temperature: number;
  credential_mode: "required" | "none";
  trusted: boolean;
  builtin: boolean;
  configured: boolean;
  updated_at: string;
}

export interface BulkImportReport {
  total: number;
  counts: Record<string, number>;
  rows: Array<{ index: number; status: string; error?: string; reason?: string }>;
}

export interface ApiError {
  status: number;
  code: string;
  safe_message: string;
  detail?: unknown;
}

export interface SecretSummary {
  name: string;
  configured: boolean;
  updated_at?: string | null;
}

export interface TemplateSummary {
  slug: string;
  name: string;
  version: string;
}
