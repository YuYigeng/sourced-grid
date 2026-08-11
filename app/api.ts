import type { GridDetail, RunSummary, SecretSummary } from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  grids: () => request<GridDetail[]>("/v1/grids"),
  grid: (id: string) => request<GridDetail>(`/v1/grids/${id}`),
  createRadar: () =>
    request<GridDetail>("/v1/templates/github-repository-radar/create-grid", {
      method: "POST",
    }),
  importRows: (gridId: string, values: string[]) =>
    request<GridDetail>(`/v1/grids/${gridId}/import`, {
      method: "POST",
      body: JSON.stringify({ values }),
    }),
  run: (gridId: string, budgetUsd = 2) =>
    request<RunSummary>(`/v1/grids/${gridId}/runs`, {
      method: "POST",
      body: JSON.stringify({ budget_usd: budgetUsd }),
    }),
  runStatus: (runId: string) => request<RunSummary>(`/v1/runs/${runId}`),
  pauseRun: (runId: string) =>
    request<RunSummary>(`/v1/runs/${runId}/pause`, { method: "POST" }),
  resumeRun: (runId: string) =>
    request<RunSummary>(`/v1/runs/${runId}/resume`, { method: "POST" }),
  cancelRun: (runId: string) =>
    request<RunSummary>(`/v1/runs/${runId}/cancel`, { method: "POST" }),
  retryFailed: (runId: string) =>
    request<RunSummary>(`/v1/runs/${runId}/retry-failed`, { method: "POST" }),
  secrets: () => request<SecretSummary[]>("/v1/secrets"),
  saveSecret: (name: string, value: string) =>
    request<SecretSummary>(`/v1/secrets/${name}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  exportUrl: (gridId: string, format: "csv" | "json") =>
    `${API_URL}/v1/grids/${gridId}/export?format=${format}`,
};
