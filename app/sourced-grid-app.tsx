"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { parse } from "csv-parse/browser/esm/sync";
import { DataGrid, type Column, type RenderCellProps } from "react-data-grid";
import {
  Activity,
  ArrowDownToLine,
  BookOpen,
  Check,
  ChevronDown,
  CircleDollarSign,
  Database,
  Copy,
  FileJson,
  FileSpreadsheet,
  Github,
  KeyRound,
  Link2,
  LoaderCircle,
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
  Trash2,
  Upload,
  X,
  Zap,
} from "lucide-react";
import "react-data-grid/lib/styles.css";
import { api } from "./api";
import { sampleGrid } from "./sample-data";
import { SchemaEditor } from "./schema-editor";
import type {
  CellExecution,
  ColumnDefinition,
  GridCell,
  GridDetail,
  GridSummary,
  Provenance,
  ProviderProfile,
  RunSummary,
  SecretSummary,
  TemplateSummary,
} from "./types";

type DisplayRow = Record<string, unknown> & {
  _rowId: string;
  _cells: Record<string, GridCell>;
};

function formatValue(value: unknown, key: string) {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "stars" && typeof value === "number") return value.toLocaleString();
  if (key === "health_score" && typeof value === "object" && value) {
    return `${String((value as { score?: unknown }).score ?? "—")}/100`;
  }
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
    const score = Number(typeof value === "object" && value ? (value as { score?: unknown }).score : value);
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
  const [selectedRowId, setSelectedRowId] = useState(sampleGrid.rows[0].id);
  const [backendOnline, setBackendOnline] = useState(false);
  const [gridSummaries, setGridSummaries] = useState<GridSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [view, setView] = useState<"grid" | "runs">("grid");
  const [importOpen, setImportOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [schemaOpen, setSchemaOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importPreview, setImportPreview] = useState<Record<string, unknown>[]>([]);
  const [duplicateStrategy, setDuplicateStrategy] = useState<"skip" | "replace" | "allow">("skip");
  const [secrets, setSecrets] = useState<SecretSummary[]>([]);
  const [providers, setProviders] = useState<ProviderProfile[]>([]);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [githubToken, setGithubToken] = useState("");
  const [providerKey, setProviderKey] = useState("");
  const [customProvider, setCustomProvider] = useState({ id: "", display_name: "", base_url: "", default_model: "", credential_mode: "required" as "required" | "none", credential: "" });
  const [cellHistory, setCellHistory] = useState<CellExecution[]>([]);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const loadGrid = useCallback(async () => {
    try {
      await api.health();
      setBackendOnline(true);
      const grids = await api.grids();
      const active = grids[0] ?? (await api.createRadar());
      setGrid(await api.grid(active.id));
      setGridSummaries(await api.grids());
      setSecrets(await api.secrets());
      setProviders(await api.providers());
      setTemplates(await api.templates());
      setRuns(await api.runs(active.id));
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
    if (!run || !["queued", "running", "paused", "cancelling"].includes(run.status)) return;
    const events = new EventSource(api.runEventsUrl(run.id));
    const refresh = async () => {
      try {
        const next = await api.runStatus(run.id);
        setRun(next);
        setGrid(await api.grid(grid.id));
        setRuns(await api.runs(grid.id));
        if (["completed", "completed_with_errors", "failed", "cancelled"].includes(next.status)) events.close();
      } catch {
        events.close();
      }
    };
    events.addEventListener("task", () => void refresh());
    events.addEventListener("run", () => void refresh());
    events.addEventListener("rate_limit", () => void refresh());
    events.onerror = () => {
      // Native EventSource reconnects and sends Last-Event-ID automatically.
    };
    return () => events.close();
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
      }).filter((row) => !searchQuery || JSON.stringify(row).toLowerCase().includes(searchQuery.toLowerCase())),
    [grid, searchQuery],
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
          </span>
        ),
        cellClass: (row: DisplayRow) => cellClass(row._cells[column.key]),
        renderCell: ({ row }: RenderCellProps<DisplayRow>) => (
          <GridValue cell={row._cells[column.key]} columnKey={column.key} />
        ),
      })),
    ],
    [grid.columns],
  );

  async function startRun() {
    if (!backendOnline) {
      setNotice("Start the API and worker to run live research. The current grid is an interactive demo.");
      return;
    }
    try {
      const next = await api.run(grid.id, 2, forceRefresh);
      setRun(next);
      setNotice("Research run started. Every completed cell will keep its source receipt.");
      setGrid(await api.grid(grid.id));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not start the run.");
    }
  }

  async function submitImport() {
    if (importPreview.length) {
      if (!backendOnline) return;
      const input = grid.columns.find((column) => column.kind === "input");
      if (!input) return;
      const firstHeader = Object.keys(importPreview[0] ?? {})[0];
      const mapped = importPreview.map((row) => ({ [input.key]: row[input.key] ?? row[firstHeader] }));
      const report = await api.importMappedRows(grid.id, mapped, duplicateStrategy);
      setNotice(`Import complete: ${report.counts.imported ?? 0} imported, ${report.counts.skipped ?? 0} skipped, ${report.counts.error ?? 0} errors.`);
      setGrid(await api.grid(grid.id));
      setImportPreview([]);
      setImportOpen(false);
      return;
    }
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

  async function createCustomProvider() {
    if (!customProvider.id || !customProvider.base_url || !customProvider.default_model) return;
    const profile = await api.createProvider({
      id: customProvider.id,
      display_name: customProvider.display_name || customProvider.id,
      base_url: customProvider.base_url,
      default_model: customProvider.default_model,
      credential_mode: customProvider.credential_mode,
      trusted: true,
    });
    if (profile.credential_mode === "required" && customProvider.credential) {
      await api.saveProviderCredential(profile.id, customProvider.credential);
    }
    setProviders(await api.providers());
    setCustomProvider({ id: "", display_name: "", base_url: "", default_model: "", credential_mode: "required", credential: "" });
    setNotice("Provider profile trusted locally. Templates can reference it but cannot alter its endpoint.");
  }

  async function selectGrid(id: string) {
    const next = await api.grid(id);
    setGrid(next);
    const history = await api.runs(id);
    setRuns(history);
    setRun(history.find((item) => ["queued", "running", "paused", "cancelling"].includes(item.status)) ?? history[0] ?? null);
    setSelectedCell(null);
  }

  async function chooseTemplate(slug: string) {
    const next = await api.createFromTemplate(slug);
    setGrid(next);
    setGridSummaries(await api.grids());
    setRuns([]);
    setRun(null);
    setTemplateOpen(false);
  }

  async function loadHistory(cell: GridCell) {
    if (!backendOnline) return;
    setCellHistory(await api.cellHistory(cell.id));
  }

  function parseCsvFile(file: File | undefined) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const rows = parse(String(reader.result ?? ""), { columns: true, skip_empty_lines: true, relax_column_count: true }) as Record<string, unknown>[];
        setImportPreview(rows.slice(0, 1000));
        setNotice(`Parsed ${Math.min(rows.length, 1000)} CSV rows. Confirm mapping in the import dialog.`);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "CSV parsing failed");
      }
    };
    reader.readAsText(file);
  }

  function selectCell(row: DisplayRow, columnKey: string) {
    const column = grid.columns.find((item) => item.key === columnKey);
    const cell = row._cells[columnKey];
    if (!column || !cell) return;
    setSelectedColumn(column);
    setSelectedCell(cell);
    setSelectedRowId(row._rowId);
    void loadHistory(cell);
  }

  async function editSelectedInput(value: string) {
    if (!selectedCell || !selectedColumn || !selectedRowId) return;
    await api.patchInputCell(grid.id, selectedRowId, selectedColumn.id, value);
    setGrid(await api.grid(grid.id));
    setNotice("Input saved. Downstream cells are now stale until the next run.");
  }

  async function deleteSelectedRow() {
    if (!selectedRowId || !window.confirm("Delete this row? Existing run snapshots remain exportable.")) return;
    await api.deleteRow(grid.id, selectedRowId);
    setGrid(await api.grid(grid.id));
    setSelectedCell(null);
  }

  async function cloneSelectedRow() {
    if (!selectedRowId) return;
    setGrid(await api.cloneRow(grid.id, selectedRowId));
    setNotice("Row duplicated. Generated cells start empty and keep independent history.");
  }

  const progress = run?.total_tasks
    ? Math.round(((run.completed_tasks + run.failed_tasks + run.skipped_tasks + run.cancelled_tasks) / run.total_tasks) * 100)
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
          <input aria-label="Search rows" placeholder="Search rows and values…" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} />
          <kbd>⌘ K</kbd>
        </div>
        <div className="topbar-actions">
          <span className={`connection-pill ${backendOnline ? "online" : "demo"}`}>
            <StatusDot status={backendOnline ? "succeeded" : "empty"} />
            {backendOnline ? "Local engine" : "Demo data"}
          </span>
          <span className="avatar" aria-label="Local workspace">SG</span>
        </div>
      </header>

      <div className="workspace-shell">
        <aside className="sidebar">
          <button className="new-grid-button" disabled={loading || !backendOnline} onClick={() => setTemplateOpen(true)}>
            <Plus size={16} /> New research grid
          </button>
          <nav aria-label="Workspace navigation">
            <p className="nav-label">Workspace</p>
            <button className={`nav-item ${view === "grid" ? "active" : ""}`} onClick={() => setView("grid")}><Table2 size={16} /> Research grids <span>{gridSummaries.length || 1}</span></button>
            <button className={`nav-item ${view === "runs" ? "active" : ""}`} onClick={() => setView("runs")}><Activity size={16} /> Runs <span>{runs.length}</span></button>
            <p className="nav-label second">Templates</p>
            {templates.map((template) => <button key={template.slug} className="nav-item template-active" onClick={() => void chooseTemplate(template.slug)}>{template.slug.includes("github") ? <Github size={16} /> : <BookOpen size={16} />}{template.name}</button>)}
            <p className="nav-label second">Grids</p>
            {gridSummaries.map((item) => <button key={item.id} className={`nav-item ${item.id === grid.id ? "active" : ""}`} onClick={() => void selectGrid(item.id)}><Table2 size={16} /> {item.name}<span>{item.row_count}</span></button>)}
          </nav>
          <div className="sidebar-bottom">
            <div className="usage-card">
              <div><CircleDollarSign size={15} /><span>Run budget</span></div>
              <strong>${run?.spent_usd.toFixed(3) ?? "0.000"} <span>+ ${run?.reserved_usd.toFixed(3) ?? "0.000"} reserved / ${run?.budget_usd.toFixed(2) ?? "2.00"}</span></strong>
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
              <button className="secondary-button" disabled={loading || !backendOnline} onClick={() => setSchemaOpen(true)}><Link2 size={15} /> Edit DAG</button>
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
              <button className={view === "grid" ? "active" : ""} onClick={() => setView("grid")}><Table2 size={14} /> Grid</button>
              <button className={view === "runs" ? "active" : ""} onClick={() => setView("runs")}><Activity size={14} /> Run log</button>
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
              <label className="force-refresh"><input type="checkbox" checked={forceRefresh} onChange={(event) => setForceRefresh(event.target.checked)} /> Force refresh</label>
            </div>
          </div>

          {view === "grid" ? <div className="grid-and-inspector">
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
                <EvidencePanel key={selectedCell.id} cell={selectedCell} column={selectedColumn} history={cellHistory} runId={run?.id} onEditInput={editSelectedInput} onDeleteRow={deleteSelectedRow} onCloneRow={cloneSelectedRow} />
              ) : (
                <div className="empty-inspector"><ShieldCheck size={24} /><p>Select a generated cell to inspect its sources, cost, and execution receipt.</p></div>
              )}
            </aside>
          </div> : <RunLog runs={runs} gridId={grid.id} onSelect={setRun} />}
        </section>
      </div>

      {notice && <div className="toast"><Check size={15} /><span>{notice}</span><button onClick={() => setNotice(null)}><X size={14} /></button></div>}

      {importOpen && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="import-title">
            <div className="modal-icon"><Github size={21} /></div>
            <h2 id="import-title">Add repositories</h2>
            <p>Paste one value per line, or choose a real CSV file. CSV uses the matching input header or maps its first column.</p>
            <input className="file-input" type="file" accept=".csv,text/csv" onChange={(event) => parseCsvFile(event.target.files?.[0])} />
            {importPreview.length ? <div className="import-preview"><strong>CSV preview · {importPreview.length} rows</strong><pre>{JSON.stringify(importPreview.slice(0, 4), null, 2)}</pre><label>Duplicates<select value={duplicateStrategy} onChange={(event) => setDuplicateStrategy(event.target.value as typeof duplicateStrategy)}><option value="skip">Skip existing</option><option value="replace">Replace existing</option><option value="allow">Allow duplicates</option></select></label></div> : <textarea value={importText} onChange={(event) => setImportText(event.target.value)} placeholder={"https://github.com/openai/openai-python\nfastapi/fastapi\nOpenHands/OpenHands"} />}
            <div className="modal-actions"><button className="secondary-button" onClick={() => { setImportOpen(false); setImportPreview([]); }}>Cancel</button><button className="run-button" onClick={submitImport}><Upload size={15} /> Import rows</button></div>
          </section>
        </div>
      )}

      {templateOpen && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-label="Choose a research template">
            <div className="modal-icon"><Plus size={21} /></div>
            <h2>Create research grid</h2>
            <p>Start from a versioned template. Provider endpoints remain controlled by your local settings.</p>
            <div className="template-list">{templates.map((template) => <button key={template.slug} onClick={() => void chooseTemplate(template.slug)}><strong>{template.name}</strong><span>{template.slug} · v{template.version}</span></button>)}</div>
            <div className="modal-actions"><button className="secondary-button" onClick={() => setTemplateOpen(false)}>Cancel</button></div>
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
            <div className="provider-list"><strong>Trusted provider profiles</strong>{providers.map((provider) => <div key={provider.id}><span>{provider.display_name}<small>{provider.base_url}</small></span><i>{provider.configured || provider.credential_mode === "none" ? "Ready" : "Needs key"}</i></div>)}</div>
            <details className="provider-create"><summary>Add custom OpenAI-compatible provider</summary>
              <label>ID<input value={customProvider.id} onChange={(event) => setCustomProvider((value) => ({ ...value, id: event.target.value }))} placeholder="my-provider" /></label>
              <label>Display name<input value={customProvider.display_name} onChange={(event) => setCustomProvider((value) => ({ ...value, display_name: event.target.value }))} /></label>
              <label>Base URL<input value={customProvider.base_url} onChange={(event) => setCustomProvider((value) => ({ ...value, base_url: event.target.value }))} placeholder="https://api.example.com/v1" /></label>
              <label>Default model<input value={customProvider.default_model} onChange={(event) => setCustomProvider((value) => ({ ...value, default_model: event.target.value }))} /></label>
              <label>Credential mode<select value={customProvider.credential_mode} onChange={(event) => setCustomProvider((value) => ({ ...value, credential_mode: event.target.value as "required" | "none" }))}><option value="required">API key (HTTPS public only)</option><option value="none">No credential (local endpoint allowed)</option></select></label>
              {customProvider.credential_mode === "required" && <label>API key<input type="password" value={customProvider.credential} onChange={(event) => setCustomProvider((value) => ({ ...value, credential: event.target.value }))} /></label>}
              <button className="secondary-button" onClick={() => void createCustomProvider()}>Confirm trust & add</button>
            </details>
            <div className="modal-actions"><button className="secondary-button" onClick={() => setSettingsOpen(false)}>Cancel</button><button className="run-button" onClick={saveSecrets}><ShieldCheck size={15} /> Encrypt & save</button></div>
          </section>
        </div>
      )}
      {schemaOpen && <SchemaEditor grid={grid} onClose={() => setSchemaOpen(false)} onSaved={(saved) => { setGrid(saved); setSchemaOpen(false); setNotice("Schema saved atomically."); }} />}
    </main>
  );
}

function EvidencePanel({ cell, column, history, runId, onEditInput, onDeleteRow, onCloneRow }: { cell: GridCell; column: ColumnDefinition | null; history: CellExecution[]; runId?: string; onEditInput: (value: string) => Promise<void>; onDeleteRow: () => Promise<void>; onCloneRow: () => Promise<void> }) {
  const receipt: Provenance | null | undefined = cell.provenance;
  const [draft, setDraft] = useState(String(cell.value ?? ""));
  return (
    <div className="evidence-content">
      <div className="result-card">
        <span className="eyebrow">Resolved value</span>
        <p>{formatValue(cell.value, column?.key ?? "")}</p>
      </div>
      {column?.kind === "input" && <div className="input-cell-editor"><label>Edit input<input value={draft} onChange={(event) => setDraft(event.target.value)} /></label><button className="run-button" onClick={() => void onEditInput(draft)}>Save input</button></div>}
      <div className="row-actions"><button onClick={() => void onCloneRow()}><Copy size={13} /> Duplicate row</button><button onClick={() => void onDeleteRow()}><Trash2 size={13} /> Delete row</button></div>
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
      {receipt?.artifact_hash && <section className="evidence-section"><h3>Artifact integrity</h3><a className="hash-box" href={api.artifactUrl(receipt.artifact_hash)}><Database size={14} /><code>{receipt.artifact_hash}</code></a></section>}
      <section className="evidence-section"><h3>Execution history <span>{history.length}</span></h3><div className="execution-history">{history.map((execution) => <div key={execution.id} className={execution.run_id === runId ? "current" : ""}><StatusDot status={execution.status} /><span><strong>{execution.status}</strong><small>{new Date(execution.created_at).toLocaleString()} · {execution.id.slice(0, 8)}</small></span>{execution.provenance?.cache_hit && <i>cache</i>}</div>)}</div></section>
    </div>
  );
}

function RunLog({ runs, gridId, onSelect }: { runs: RunSummary[]; gridId: string; onSelect: (run: RunSummary) => void }) {
  return <section className="run-log"><header><div><span>Immutable run snapshots</span><h2>Run history</h2></div><p>Every run links to its own executions, receipts, cost estimate, and scoped export.</p></header>{runs.length ? <div className="run-list">{runs.map((item) => <article key={item.id}><button className="run-summary-button" onClick={() => onSelect(item)}><StatusDot status={item.status === "completed" ? "succeeded" : item.status} /><span><strong>{item.status.replaceAll("_", " ")}</strong><small>{new Date(item.created_at).toLocaleString()} · {item.id}</small></span></button><dl><div><dt>Done</dt><dd>{item.completed_tasks}/{item.total_tasks}</dd></div><div><dt>Failed</dt><dd>{item.failed_tasks + item.skipped_tasks}</dd></div><div><dt>Estimated cost</dt><dd>${item.spent_usd.toFixed(4)}</dd></div></dl><div className="run-exports"><a href={api.exportUrl(gridId, "csv", item.id)}>CSV</a><a href={api.exportUrl(gridId, "json", item.id)}>JSON + receipts</a></div></article>)}</div> : <div className="empty-run-log"><Activity size={25} /><p>No runs yet. Start research from the grid view.</p></div>}</section>;
}
