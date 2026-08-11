export type CellStatus =
  | "empty"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

export type ColumnKind = "input" | "github" | "http" | "transform" | "llm";

export interface ColumnDefinition {
  id: string;
  key: string;
  label: string;
  kind: ColumnKind;
  width: number;
  position: number;
}

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
  columns: ColumnDefinition[];
  rows: GridRowData[];
}

export interface RunSummary {
  id: string;
  status: string;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  spent_usd: number;
  budget_usd: number;
}

export interface SecretSummary {
  name: string;
  configured: boolean;
  updated_at?: string | null;
}
