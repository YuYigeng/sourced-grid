import type { GridDetail } from "./types";

const columns = [
  ["repo_url", "Repository", "input", 250],
  ["canonical_name", "Canonical name", "transform", 175],
  ["stars", "Stars", "transform", 105],
  ["primary_language", "Language", "transform", 125],
  ["license", "License", "transform", 105],
  ["last_push", "Last push", "transform", 135],
  ["health_score", "Health", "transform", 100],
  ["readme_summary", "Sourced summary", "llm", 290],
] as const;

const data = [
  [
    "https://github.com/openai/openai-python",
    "openai/openai-python",
    "31,842",
    "Python",
    "Apache-2.0",
    "2h ago",
    94,
    "Official Python client with typed request models, streaming helpers, and broad API coverage.",
  ],
  [
    "https://github.com/fastapi/fastapi",
    "fastapi/fastapi",
    "91,124",
    "Python",
    "MIT",
    "5h ago",
    97,
    "High-performance API framework built around Python type hints and automatic OpenAPI documentation.",
  ],
  [
    "https://github.com/OpenHands/OpenHands",
    "OpenHands/OpenHands",
    "74,613",
    "Python",
    "MIT",
    "1h ago",
    89,
    "A software development agent platform with local and cloud runtimes for code-changing tasks.",
  ],
];

export const sampleGrid: GridDetail = {
  id: "sample-grid",
  name: "GitHub Repository Radar",
  description: "Compare repository momentum, maintenance, and product signals.",
  columns: columns.map(([key, label, kind, width], index) => ({
    id: `sample-column-${index}`,
    key,
    label,
    kind,
    width,
    position: index,
  })),
  rows: data.map((row, rowIndex) => ({
    id: `sample-row-${rowIndex}`,
    position: rowIndex,
    cells: row.map((value, cellIndex) => ({
      id: `sample-cell-${rowIndex}-${cellIndex}`,
      column_id: `sample-column-${cellIndex}`,
      status: "succeeded",
      value,
      provenance: {
        id: `sample-provenance-${rowIndex}-${cellIndex}`,
        connector: cellIndex === 7 ? "anthropic" : cellIndex === 0 ? "input" : "github",
        source_urls: [String(row[0])],
        artifact_hash: `sha256:${"a7c3d9e4".repeat(8)}`,
        input_hash: `sha256:${"42f1b8d0".repeat(8)}`,
        model: cellIndex === 7 ? "claude-sonnet" : null,
        prompt: cellIndex === 7 ? "Summarize this repository using only the supplied README and metadata." : null,
        input_tokens: cellIndex === 7 ? 1348 : 0,
        output_tokens: cellIndex === 7 ? 61 : 0,
        cost_usd: cellIndex === 7 ? 0.0062 : 0,
        duration_ms: cellIndex === 7 ? 2183 : 342,
        cache_hit: cellIndex > 0 && cellIndex < 7,
        created_at: new Date().toISOString(),
        metadata: { demo: true },
      },
    })),
  })),
};
