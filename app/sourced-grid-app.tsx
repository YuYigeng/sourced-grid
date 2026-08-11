"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { DataGrid, type Column, type RenderCellProps } from "react-data-grid";
import {
  Activity,
  ArrowDownToLine,
  BookOpen,
  Check,
  ChevronDown,
  CircleDollarSign,
  CircleHelp,
  Database,
  FileJson,
  FileSpreadsheet,
  Github,
  KeyRound,
  Link2,
  LoaderCircle,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Table2,
  Upload,
  X,
  Zap,
} from "lucide-react";
import "react-data-grid/lib/styles.css";
import { api } from "./api";
import { sampleGrid } from "./sample-data";
import type {
  ColumnDefinition,
  GridCell,
  GridDetail,
  Provenance,
  RunSummary,
  SecretSummary,
} from "./types";

type DisplayRow = Record<string, unknown> & {
  _rowId: string;
  _cells: Record<string, GridCell>;
};

function formatValue(value: unknown, key: string) {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "stars" && typeof value === "number") return value.toLocaleString();
  if (key === "health_score") return `${value}/100`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function cellClass(cell?: GridCell) {
  if (!cell) return "cell-empty";
  return `cell-${cell.status}`;
}

function StatusDot({ status }: { status?: string }) {
  if (status === "running" || status === "queued") {
    return <LoaderCircle className="status-spinner" aria-label={status} />;
  }
  if (status === "failed") return <span className="status-dot status-dot-failed" />;
  if (status === "succeeded") return <span className="status-dot status-dot-ready" />;
  return <span className="status-dot" />;
}

function GridValue({ cell, columnKey }: { cell?: GridCell; columnKey: string }) {
  const value = cell?.value;
  if (cell?.status === "running" || cell?.status === "queued") {
    return (
      <span className="cell-pending">
        <LoaderCircle className="status-spinner" /> Researching…
      </span>
    );
  }
  if (cell?.status === "failed") return <span className="cell-error">Needs attention</span>;
  if (columnKey === "repo_url" && value) {
    return (
      <span className="repo-cell">
        <Github size={15} />
        <span>{String(value).replace("https://github.com/", "")}</span>
      </span>
    );
  }
  if (columnKey === "stars") {
    return <span className="numeric-cell">★ {formatValue(value, columnKey)}</span>;
  }
  if (columnKey === "health_score" && value !== null && value !== undefined) {
    const score = Number(value);
    return (
      <span className={`score-pill ${score >= 90 ? "score-high" : "score-medium"}`}>
        {score}
      </span>
    );
  }
  if (columnKey === "license" && value) return <span className="code-pill">{String(value)}</span>;
  return <span>{formatValue(value, columnKey)}</span>;
}

export function SourcedGridApp() {
  const [grid, setGrid] = useState<GridDetail>(sampleGrid);
  const [selectedCell, setSelectedCell] = useState<GridCell | null>(
    sampleGrid.rows[0].cells[7],
  );
  const [selectedColumn, setSelectedColumn] = useState<ColumnDefinition | null>(
    sampleGrid.columns[7],
  );
  const [backendOnline, setBackendOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [secrets, setSecrets] = useState<SecretSummary[]>([]);
  const [githubToken, setGithubToken] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const loadGrid = useCallback(async () => {
    try {
      await api.health();
      setBackendOnline(true);
      const grids = await api.grids();
      const active = grids[0] ?? (await api.createRadar());
      setGrid(await api.grid(active.id));
      setSecrets(await api.secrets());
    } catch {
      setBackendOnline(false);
      setGrid(sampleGrid);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadGrid(), 0);
    return () => window.clearTimeout(timer);
  }, [loadGrid]);

  useEffect(() => {
    if (!run || !["queued", "running", "paused"].includes(run.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.runStatus(run.id);
        setRun(next);
        if (["completed", "completed_with_errors", "failed", "cancelled"].includes(next.status)) {
          setGrid(await api.grid(grid.id));
        }
      } catch {
        window.clearInterval(timer);
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [grid.id, run]);

  const displayRows = useMemo<DisplayRow[]>(
    () =>
      grid.rows.map((row) => {
        const cells = Object.fromEntries(
          row.cells.map((cell) => {
            const column = grid.columns.find((item) => item.id === cell.column_id);
            return [column?.key ?? cell.column_id, cell];
          }),
        );
        const values = Object.fromEntries(
          Object.entries(cells).map(([key, cell]) => [key, cell.value]),
        );
        return { _rowId: row.id, _cells: cells, ...values };
      }),
    [grid],
  );

  const columns = useMemo<Column<DisplayRow>[]>(
    () => [
      {
        key: "_index",
        name: "",
        width: 46,
        minWidth: 46,
        resizable: false,
        frozen: true,
        renderCell: ({ rowIdx }) => <span className="row-index">{rowIdx + 1}</span>,
      },
      ...grid.columns.map((column) => ({
        key: column.key,
        name: column.label,
        width: column.width || 160,
        minWidth: 90,
        resizable: true,
        renderHeaderCell: () => (
          <span className="column-heading">
            <span className={`kind-icon kind-${column.kind}`}>
              {column.kind === "llm" ? <Sparkles size={12} /> : column.kind === "github" ? <Github size={12} /> : <Database size={12} />}
            </span>
            {column.label}
            <ChevronDown size={13} />
          </span>
        ),
        cellClass: (row: DisplayRow) => cellClass(row._cells[column.key]),
        renderCell: ({ row }: RenderCellProps<DisplayRow>) => (
          <GridValue cell={row._cells[column.key]} columnKey={column.key} />
        ),
      })),
      {
        key: "_add",
        name: "",
        width: 48,
        minWidth: 48,
        renderHeaderCell: () => <Plus size={15} aria-label="Add column" />,
        renderCell: () => null,
      },
    ],
    [grid.columns],
  );

  async function startRun() {
    if (!backendOnline) {
      setNotice("Start the API and worker to run live research. The current grid is an interactive demo.");
      return;
    }
    try {
      const next = await api.run(grid.id, 2);
      setRun(next);
      setNotice("Research run started. Every completed cell will keep its source receipt.");
      setGrid(await api.grid(grid.id));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not start the run.");
    }
  }

  async function submitImport() {
    const values = importText
      .split(/[\n,]/)
      .map((value) => value.trim())
      .filter(Boolean);
    if (!values.length) return;
    if (!backendOnline) {
      setNotice("Live importing becomes available when the local API is running.");
      setImportOpen(false);
      return;
    }
    setGrid(await api.importRows(grid.id, values));
    setImportText("");
    setImportOpen(false);
  }

  async function saveSecrets() {
    if (!backendOnline) {
      setNotice("Start the local API before saving encrypted credentials.");
      return;
    }
    if (githubToken) await api.saveSecret("github_token", githubToken);
    if (providerKey) await api.saveSecret("anthropic_api_key", providerKey);
    setSecrets(await api.secrets());
    setGithubToken("");
    setProviderKey("");
    setSettingsOpen(false);
    setNotice("Credentials encrypted locally. Plaintext values are never returned by the API.");
  }

  function selectCell(row: DisplayRow, columnKey: string) {
    const column = grid.columns.find((item) => item.key === columnKey);
    const cell = row._cells[columnKey];
    if (!column || !cell) return;
    setSelectedColumn(column);
    setSelectedCell(cell);
  }

  const progress = run?.total_tasks
    ? Math.round(((run.completed_tasks + run.failed_tasks) / run.total_tasks) * 100)
    : 100;
  const isRunning = run && ["queued", "running"].includes(run.status);

  return (
    <main className="app-shell" data-ready={!loading}>
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <strong>SourcedGrid</strong>
            <span>Research with receipts</span>
          </div>
        </div>
        <div className="topbar-search">
          <Search size={15} />
          <input aria-label="Search grids" placeholder="Search grids, rows, sources…" />
          <kbd>⌘ K</kbd>
        </div>
        <div className="topbar-actions">
          <span className={`connection-pill ${backendOnline ? "online" : "demo"}`}>
            <StatusDot status={backendOnline ? "succeeded" : "empty"} />
            {backendOnline ? "Local engine" : "Demo data"}
          </span>
          <button className="icon-button" aria-label="Help"><CircleHelp size={17} /></button>
          <button className="avatar" aria-label="Local workspace">SG</button>
        </div>
      </header>

      <div className="workspace-shell">
        <aside className="sidebar">
          <button className="new-grid-button" disabled={loading} onClick={() => setImportOpen(true)}>
            <Plus size={16} /> New research grid
          </button>
          <nav aria-label="Workspace navigation">
            <p className="nav-label">Workspace</p>
            <button className="nav-item active"><Table2 size={16} /> Research grids <span>1</span></button>
            <button className="nav-item"><Activity size={16} /> Runs <span>{run ? 1 : 0}</span></button>
            <button className="nav-item"><ShieldCheck size={16} /> Sources</button>
            <p className="nav-label second">Templates</p>
            <button className="nav-item template-active"><Github size={16} /> Repository Radar</button>
            <button className="nav-item"><BookOpen size={16} /> Research library</button>
          </nav>
          <div className="sidebar-bottom">
            <div className="usage-card">
              <div><CircleDollarSign size={15} /><span>Run budget</span></div>
              <strong>${run?.spent_usd.toFixed(3) ?? "0.000"} <span>/ ${run?.budget_usd.toFixed(2) ?? "2.00"}</span></strong>
              <div className="usage-track"><span style={{ width: `${Math.min(100, ((run?.spent_usd ?? 0) / (run?.budget_usd || 2)) * 100)}%` }} /></div>
            </div>
            <button className="nav-item" disabled={loading} onClick={() => setSettingsOpen(true)}><Settings size={16} /> Settings</button>
          </div>
        </aside>

        <section className="main-workspace">
          <div className="grid-header">
            <div>
              <div className="breadcrumb"><span>Research grids</span><span>/</span><span>GitHub Repository Radar</span></div>
              <div className="title-line">
                <h1>{grid.name}</h1>
                <span className="template-badge"><Zap size={12} /> Template</span>
                <button className="icon-button"><MoreHorizontal size={17} /></button>
              </div>
              <p>{grid.description}</p>
            </div>
            <div className="header-actions">
              <div className="export-menu">
                <button className="secondary-button"><ArrowDownToLine size={15} /> Export <ChevronDown size={13} /></button>
                <div className="export-options">
                  <a href={backendOnline ? api.exportUrl(grid.id, "csv") : "#"}><FileSpreadsheet size={14} /> CSV values</a>
                  <a href={backendOnline ? api.exportUrl(grid.id, "json") : "#"}><FileJson size={14} /> JSON + receipts</a>
                </div>
              </div>
              <button className="secondary-button" disabled={loading} onClick={() => setImportOpen(true)}><Upload size={15} /> Import</button>
              {isRunning ? (
                <button className="run-button" onClick={async () => setRun(await api.pauseRun(run.id))}><Pause size={15} /> Pause</button>
              ) : run?.status === "paused" ? (
                <button className="run-button" onClick={async () => setRun(await api.resumeRun(run.id))}><Play size={15} /> Resume</button>
              ) : (
                <button className="run-button" onClick={startRun}><Sparkles size={15} /> Run research</button>
              )}
            </div>
          </div>

          <div className="view-toolbar">
            <div className="view-tabs">
              <button className="active"><Table2 size={14} /> Grid</button>
              <button><Activity size={14} /> Run log</button>
            </div>
            <div className="toolbar-right">
              {run && (
                <div className="run-progress">
                  <span className="progress-track"><span style={{ width: `${progress}%` }} /></span>
                  <span>{progress}% · {run.completed_tasks} done</span>
                  {isRunning && <button onClick={async () => setRun(await api.cancelRun(run.id))} aria-label="Cancel run"><Square size={12} /></button>}
                  {run.failed_tasks > 0 && <button onClick={async () => setRun(await api.retryFailed(run.id))}><RefreshCw size={12} /> Retry {run.failed_tasks}</button>}
                </div>
              )}
              <button><Link2 size={14} /> Share template</button>
            </div>
          </div>

          <div className="grid-and-inspector">
            <div className="data-grid-wrap">
              {loading ? (
                <div className="loading-state"><LoaderCircle className="status-spinner" /> Loading research grid…</div>
              ) : (
                <DataGrid
                  className="rdg-light sourced-data-grid"
                  columns={columns}
                  rows={displayRows}
                  rowHeight={52}
                  headerRowHeight={42}
                  onCellClick={({ row, column }) => selectCell(row, column.key)}
                  rowKeyGetter={(row) => row._rowId}
                />
              )}
              <button className="add-row" disabled={loading} onClick={() => setImportOpen(true)}><Plus size={14} /> Add repositories</button>
              <div className="grid-footer">
                <span>{grid.rows.length} repositories · {grid.columns.length} fields</span>
                <span><ShieldCheck size={13} /> Every generated value keeps a receipt</span>
              </div>
            </div>

            <aside className={`inspector ${selectedCell ? "open" : ""}`} aria-label="Cell evidence">
              <div className="inspector-header">
                <div>
                  <span className="eyebrow">Cell evidence</span>
                  <h2>{selectedColumn?.label ?? "Select a cell"}</h2>
                </div>
                <button className="icon-button" onClick={() => setSelectedCell(null)} aria-label="Close evidence"><X size={17} /></button>
              </div>
              {selectedCell ? (
                <EvidencePanel cell={selectedCell} column={selectedColumn} />
              ) : (
                <div className="empty-inspector"><ShieldCheck size={24} /><p>Select a generated cell to inspect its sources, cost, and execution receipt.</p></div>
              )}
            </aside>
          </div>
        </section>
      </div>

      {notice && <div className="toast"><Check size={15} /><span>{notice}</span><button onClick={() => setNotice(null)}><X size={14} /></button></div>}

      {importOpen && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="import-title">
            <div className="modal-icon"><Github size={21} /></div>
            <h2 id="import-title">Add repositories</h2>
            <p>Paste one GitHub URL or <code>owner/repo</code> per line. CSV columns are also accepted.</p>
            <textarea value={importText} onChange={(event) => setImportText(event.target.value)} placeholder={"https://github.com/openai/openai-python\nfastapi/fastapi\nOpenHands/OpenHands"} />
            <div className="modal-actions"><button className="secondary-button" onClick={() => setImportOpen(false)}>Cancel</button><button className="run-button" onClick={submitImport}><Upload size={15} /> Import repositories</button></div>
          </section>
        </div>
      )}

      {settingsOpen && (
        <div className="modal-backdrop">
          <section className="modal settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
            <div className="modal-icon"><KeyRound size={21} /></div>
            <h2 id="settings-title">Local credentials</h2>
            <p>Keys are encrypted by the local engine. Existing plaintext values are never returned.</p>
            <label>GitHub token <span>{secrets.find((item) => item.name === "github_token")?.configured ? "Configured" : "Optional"}</span><input type="password" value={githubToken} onChange={(event) => setGithubToken(event.target.value)} placeholder="github_pat_••••••••" /></label>
            <label>Anthropic API key <span>{secrets.find((item) => item.name === "anthropic_api_key")?.configured ? "Configured" : "Optional"}</span><input type="password" value={providerKey} onChange={(event) => setProviderKey(event.target.value)} placeholder="sk-ant-••••••••" /></label>
            <div className="modal-actions"><button className="secondary-button" onClick={() => setSettingsOpen(false)}>Cancel</button><button className="run-button" onClick={saveSecrets}><ShieldCheck size={15} /> Encrypt & save</button></div>
          </section>
        </div>
      )}
    </main>
  );
}

function EvidencePanel({ cell, column }: { cell: GridCell; column: ColumnDefinition | null }) {
  const receipt: Provenance | null | undefined = cell.provenance;
  return (
    <div className="evidence-content">
      <div className="result-card">
        <span className="eyebrow">Resolved value</span>
        <p>{formatValue(cell.value, column?.key ?? "")}</p>
      </div>
      <div className="verified-line"><ShieldCheck size={16} /><div><strong>Source-backed</strong><span>{receipt?.cache_hit ? "Verified from cached source" : "Verified from live source"}</span></div></div>
      <section className="evidence-section">
        <h3>Sources <span>{receipt?.source_urls.length ?? 0}</span></h3>
        {(receipt?.source_urls ?? []).map((url) => (
          <a key={url} className="source-link" href={url} target="_blank" rel="noreferrer">
            <Github size={16} /><span><strong>{url.replace("https://github.com/", "")}</strong><small>{url}</small></span><Link2 size={14} />
          </a>
        ))}
      </section>
      <section className="evidence-section">
        <h3>Execution receipt</h3>
        <dl className="receipt-grid">
          <div><dt>Connector</dt><dd>{receipt?.connector ?? column?.kind ?? "input"}</dd></div>
          <div><dt>Duration</dt><dd>{receipt ? `${receipt.duration_ms.toLocaleString()} ms` : "—"}</dd></div>
          <div><dt>Model</dt><dd>{receipt?.model ?? "Deterministic"}</dd></div>
          <div><dt>Cost</dt><dd>${receipt?.cost_usd.toFixed(4) ?? "0.0000"}</dd></div>
          <div><dt>Input tokens</dt><dd>{receipt?.input_tokens.toLocaleString() ?? "0"}</dd></div>
          <div><dt>Output tokens</dt><dd>{receipt?.output_tokens.toLocaleString() ?? "0"}</dd></div>
        </dl>
      </section>
      {receipt?.prompt && <section className="evidence-section"><h3>Prompt</h3><pre className="prompt-box">{receipt.prompt}</pre></section>}
      {receipt?.artifact_hash && <section className="evidence-section"><h3>Artifact integrity</h3><div className="hash-box"><Database size={14} /><code>{receipt.artifact_hash}</code></div></section>}
    </div>
  );
}
