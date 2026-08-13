import type {
  ApiError,
  BulkImportReport,
  CellExecution,
  GridDetail,
  GridSchemaColumn,
  GridSummary,
  ProviderProfile,
  RunDetail,
  RunSummary,
  SecretSummary,
  StructuredOutputMode,
  TemplateSummary,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export class SourcedGridApiError extends Error {
  readonly error: ApiError;

  constructor(error: ApiError) {
    super(error.safe_message);
    this.name = "SourcedGridApiError";
    this.error = error;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    const body = typeof detail === "object" && detail ? detail as Record<string, unknown> : {};
    const nested = typeof body.detail === "object" && body.detail ? body.detail as Record<string, unknown> : {};
    throw new SourcedGridApiError({
      status: response.status,
      code: String(nested.code ?? body.code ?? `http_${response.status}`),
      safe_message: String(nested.safe_message ?? body.safe_message ?? body.detail ?? `Request failed: ${response.status}`),
      detail,
    });
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  grids: () => request<GridSummary[]>("/v1/grids"),
  grid: (id: string) => request<GridDetail>(`/v1/grids/${id}`),
  patchGrid: (id: string, patch: { name?: string; description?: string }) =>
    request<GridDetail>(`/v1/grids/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteGrid: (id: string) => request<void>(`/v1/grids/${id}`, { method: "DELETE" }),
  templates: () => request<TemplateSummary[]>("/v1/templates"),
  createFromTemplate: (slug: string) =>
    request<GridDetail>(`/v1/templates/${slug}/create-grid`, { method: "POST" }),
  createRadar: () =>
    request<GridDetail>("/v1/templates/github-repository-radar/create-grid", { method: "POST" }),
  importRows: (gridId: string, values: string[]) =>
    request<GridDetail>(`/v1/grids/${gridId}/import`, {
      method: "POST",
      body: JSON.stringify({ values }),
    }),
  importMappedRows: (
    gridId: string,
    rows: Record<string, unknown>[],
    duplicateStrategy: "skip" | "replace" | "allow" = "skip",
  ) => request<BulkImportReport>(`/v1/grids/${gridId}/rows:import`, {
    method: "POST",
    body: JSON.stringify({ rows, duplicate_strategy: duplicateStrategy }),
  }),
  patchInputCell: (gridId: string, rowId: string, columnId: string, value: string) =>
    request(`/v1/grids/${gridId}/rows/${rowId}/cells/${columnId}`, {
      method: "PATCH",
      body: JSON.stringify({ value }),
    }),
  deleteRow: (gridId: string, rowId: string) =>
    request<void>(`/v1/grids/${gridId}/rows/${rowId}`, { method: "DELETE" }),
  cloneRow: (gridId: string, rowId: string) =>
    request<GridDetail>(`/v1/grids/${gridId}/rows/${rowId}/clone`, { method: "POST" }),
  cloneColumn: (gridId: string, columnId: string) =>
    request<GridDetail>(`/v1/grids/${gridId}/columns/${columnId}/clone`, { method: "POST" }),
  validateSchema: (gridId: string, schemaVersion: number, columns: GridSchemaColumn[], canvasLayout: Record<string, { x: number; y: number }>) =>
    request<{ valid: boolean }>(`/v1/grids/${gridId}/schema/validate`, {
      method: "POST",
      body: JSON.stringify({ schema_version: schemaVersion, columns, canvas_layout: canvasLayout }),
    }),
  saveSchema: (gridId: string, schemaVersion: number, columns: GridSchemaColumn[], canvasLayout: Record<string, { x: number; y: number }>) =>
    request<GridDetail>(`/v1/grids/${gridId}/schema`, {
      method: "PUT",
      body: JSON.stringify({ schema_version: schemaVersion, columns, canvas_layout: canvasLayout }),
    }),
  run: (gridId: string, budgetUsd = 2, forceRefresh = false) =>
    request<RunSummary>(`/v1/grids/${gridId}/runs`, {
      method: "POST",
      body: JSON.stringify({ budget_usd: budgetUsd, force_refresh: forceRefresh }),
    }),
  runs: (gridId: string) => request<RunSummary[]>(`/v1/grids/${gridId}/runs`),
  runStatus: (runId: string) => request<RunSummary>(`/v1/runs/${runId}`),
  runResults: (runId: string) => request<RunDetail>(`/v1/runs/${runId}/results`),
  runEventsUrl: (runId: string) => `${API_URL}/v1/runs/${runId}/events`,
  pauseRun: (runId: string) => request<RunSummary>(`/v1/runs/${runId}/pause`, { method: "POST" }),
  resumeRun: (runId: string) => request<RunSummary>(`/v1/runs/${runId}/resume`, { method: "POST" }),
  cancelRun: (runId: string) => request<RunSummary>(`/v1/runs/${runId}/cancel`, { method: "POST" }),
  retryFailed: (runId: string) => request<RunSummary>(`/v1/runs/${runId}/retry-failed`, { method: "POST" }),
  cellHistory: (cellId: string) => request<CellExecution[]>(`/v1/cells/${cellId}/history`),
  secrets: () => request<SecretSummary[]>("/v1/secrets"),
  saveSecret: (name: string, value: string) => request<SecretSummary>(`/v1/secrets/${name}`, {
    method: "PUT",
    body: JSON.stringify({ value }),
  }),
  providers: () => request<ProviderProfile[]>("/v1/providers"),
  createProvider: (profile: { id: string; display_name: string; base_url: string; default_model: string; structured_output_mode: StructuredOutputMode; default_temperature: number; credential_mode: "required" | "none"; trusted: true }) =>
    request<ProviderProfile>("/v1/providers", { method: "POST", body: JSON.stringify(profile) }),
  patchProvider: (providerId: string, patch: { display_name?: string; base_url?: string; default_model?: string; structured_output_mode?: StructuredOutputMode; default_temperature?: number; credential_mode?: "required" | "none" }) =>
    request<ProviderProfile>(`/v1/providers/${providerId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteProvider: (providerId: string) =>
    request<void>(`/v1/providers/${providerId}`, { method: "DELETE" }),
  saveProviderCredential: (providerId: string, value: string) =>
    request<{ id: string; configured: boolean }>(`/v1/providers/${providerId}/credential`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  exportUrl: (gridId: string, format: "csv" | "json", runId?: string) =>
    `${API_URL}/v1/grids/${gridId}/export?format=${format}${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`,
  artifactUrl: (artifactHash: string) => `${API_URL}/v1/artifacts/${artifactHash}`,
};
