"use client";

import { useCallback, useMemo, useState } from "react";
import dagre from "@dagrejs/dagre";
import {
  addEdge,
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Copy, LayoutDashboard, Plus, Redo2, Save, Trash2, Undo2, X } from "lucide-react";
import "@xyflow/react/dist/style.css";
import { api } from "./api";
import type { ColumnKind, GridDetail, GridSchemaColumn, ProviderProfile } from "./types";

type ColumnNodeData = GridSchemaColumn & { label: string };
type ColumnNode = Node<ColumnNodeData, "column">;
type Snapshot = { nodes: ColumnNode[]; edges: Edge[] };

const kinds: ColumnKind[] = ["input", "github", "http", "transform", "llm"];

function ColumnNodeView({ data, selected }: NodeProps<ColumnNode>) {
  return (
    <div className={`dag-node dag-${data.kind} ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <span>{data.kind}</span>
      <strong>{data.label}</strong>
      <small>{data.key}</small>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { column: ColumnNodeView };

function toGraph(grid: GridDetail): Snapshot {
  const nodes: ColumnNode[] = grid.columns.map((column, index) => ({
    id: column.key,
    type: "column",
    position: grid.canvas_layout[column.key] ?? { x: 80 + index * 210, y: 100 + (index % 3) * 125 },
    data: {
      key: column.key,
      label: column.label,
      kind: column.kind,
      width: column.width,
      depends_on: column.depends_on,
      config: column.config,
      prompt: column.prompt,
      output_schema: column.output_schema,
    },
  }));
  const edges = grid.columns.flatMap((column) =>
    column.depends_on.map((dependency) => ({
      id: `${dependency}->${column.key}`,
      source: dependency,
      target: column.key,
    })),
  );
  return { nodes, edges };
}

function createsCycle(edges: Edge[], connection: Pick<Connection, "source" | "target">) {
  if (!connection.source || !connection.target || connection.source === connection.target) return true;
  const adjacency = new Map<string, string[]>();
  for (const edge of [...edges, { source: connection.source, target: connection.target } as Edge]) {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
  }
  const stack = [connection.target];
  const seen = new Set<string>();
  while (stack.length) {
    const current = stack.pop()!;
    if (current === connection.source) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(adjacency.get(current) ?? []));
  }
  return false;
}

function layoutGraph(nodes: ColumnNode[], edges: Edge[]) {
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "LR", nodesep: 55, ranksep: 90 });
  nodes.forEach((node) => graph.setNode(node.id, { width: 180, height: 82 }));
  edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
  dagre.layout(graph);
  return nodes.map((node) => {
    const point = graph.node(node.id);
    return { ...node, position: { x: point.x - 90, y: point.y - 41 } };
  });
}

export function SchemaEditor({ grid, providers, onClose, onSaved }: { grid: GridDetail; providers: ProviderProfile[]; onClose: () => void; onSaved: (grid: GridDetail) => void }) {
  const initial = useMemo(() => toGraph(grid), [grid]);
  const [nodes, setNodes, onNodesChange] = useNodesState<ColumnNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const [selectedId, setSelectedId] = useState(initial.nodes[0]?.id ?? "");
  const [past, setPast] = useState<Snapshot[]>([]);
  const [future, setFuture] = useState<Snapshot[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [baseline, setBaseline] = useState(() => JSON.stringify(initial));

  const selected = nodes.find((node) => node.id === selectedId);
  const selectedProvider = providers.find(
    (provider) => provider.id === String(selected?.data.config.provider_ref ?? ""),
  );
  const dirty = JSON.stringify({ nodes, edges }) !== baseline;

  const checkpoint = useCallback(() => {
    setPast((items) => [...items.slice(-49), { nodes, edges }]);
    setFuture([]);
  }, [edges, nodes]);

  const onConnect = useCallback((connection: Connection) => {
    if (createsCycle(edges, connection)) {
      setError("That connection would create a dependency cycle.");
      return;
    }
    checkpoint();
    setEdges((current) => addEdge({ ...connection, id: `${connection.source}->${connection.target}` }, current));
  }, [checkpoint, edges, setEdges]);

  function updateSelected(patch: Partial<ColumnNodeData>) {
    checkpoint();
    setNodes((items) => items.map((node) => node.id === selectedId ? { ...node, data: { ...node.data, ...patch } } : node));
  }

  function addNode(kind: ColumnKind) {
    checkpoint();
    const suffix = nodes.filter((node) => node.data.kind === kind).length + 1;
    let key = `${kind}_${suffix}`;
    while (nodes.some((node) => node.id === key)) key += "_new";
    const node: ColumnNode = {
      id: key,
      type: "column",
      position: { x: 80 + nodes.length * 35, y: 80 + nodes.length * 35 },
      data: { key, label: `${kind[0].toUpperCase()}${kind.slice(1)} ${suffix}`, kind, width: 180, depends_on: [], config: kind === "llm" ? { provider_ref: providers.find((provider) => provider.configured || provider.credential_mode === "none")?.id ?? providers[0]?.id ?? "anthropic" } : {}, prompt: kind === "llm" ? "" : null, output_schema: {} },
    };
    setNodes((items) => [...items, node]);
    setSelectedId(key);
  }

  function removeSelected() {
    if (!selected) return;
    checkpoint();
    setNodes((items) => items.filter((node) => node.id !== selected.id));
    setEdges((items) => items.filter((edge) => edge.source !== selected.id && edge.target !== selected.id));
    setSelectedId("");
  }

  function duplicateSelected() {
    if (!selected) return;
    checkpoint();
    let key = `${selected.data.key}_copy`;
    while (nodes.some((node) => node.id === key)) key += "_copy";
    setNodes((items) => [...items, { ...selected, id: key, selected: false, position: { x: selected.position.x + 40, y: selected.position.y + 100 }, data: { ...selected.data, key, label: `${selected.data.label} copy` } }]);
    setSelectedId(key);
  }

  function updateLlmModel(model: string) {
    if (!selected) return;
    const config = { ...selected.data.config };
    if (model.trim()) config.model = model;
    else delete config.model;
    updateSelected({ config });
  }

  function undo() {
    const previous = past.at(-1);
    if (!previous) return;
    setFuture((items) => [{ nodes, edges }, ...items]);
    setPast((items) => items.slice(0, -1));
    setNodes(previous.nodes);
    setEdges(previous.edges);
  }

  function redo() {
    const next = future[0];
    if (!next) return;
    setPast((items) => [...items, { nodes, edges }]);
    setFuture((items) => items.slice(1));
    setNodes(next.nodes);
    setEdges(next.edges);
  }

  async function save() {
    setSaving(true);
    setError(null);
    const columns: GridSchemaColumn[] = nodes.map((node) => ({
      ...node.data,
      key: node.id,
      depends_on: edges.filter((edge) => edge.target === node.id).map((edge) => edge.source),
    }));
    const layout = Object.fromEntries(nodes.map((node) => [node.id, node.position]));
    try {
      await api.validateSchema(grid.id, grid.schema_version, columns, layout);
      const saved = await api.saveSchema(grid.id, grid.schema_version, columns, layout);
      setBaseline(JSON.stringify({ nodes, edges }));
      onSaved(saved);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Schema save failed");
    } finally {
      setSaving(false);
    }
  }

  function close() {
    if (!dirty || window.confirm("Discard unsaved schema changes?")) onClose();
  }

  return (
    <div className="schema-editor-backdrop">
      <section className="schema-editor" role="dialog" aria-modal="true" aria-label="Grid schema editor">
        <header className="schema-editor-header">
          <div><strong>Column DAG</strong><span>Schema v{grid.schema_version} · {dirty ? "Unsaved changes" : "Saved"}</span></div>
          <div className="dag-actions">
            <button disabled={!past.length} onClick={undo}><Undo2 size={14} /> Undo</button>
            <button disabled={!future.length} onClick={redo}><Redo2 size={14} /> Redo</button>
            <button onClick={() => { checkpoint(); setNodes(layoutGraph(nodes, edges)); }}><LayoutDashboard size={14} /> Auto layout</button>
            <button className="run-button" disabled={saving || !dirty} onClick={save}><Save size={14} /> Save atomically</button>
            <button className="icon-button" onClick={close}><X size={17} /></button>
          </div>
        </header>
        <div className="schema-editor-body">
          <aside className="node-palette">
            <span>ADD COLUMN</span>
            {kinds.map((kind) => <button key={kind} onClick={() => addNode(kind)}><Plus size={13} /><i className={`palette-kind kind-${kind}`} />{kind}</button>)}
          </aside>
          <div className="flow-canvas">
            <ReactFlowProvider>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                isValidConnection={(connection) => !createsCycle(edges, connection)}
                onNodeClick={(_, node) => setSelectedId(node.id)}
                onNodeDragStart={checkpoint}
                fitView
                deleteKeyCode={null}
              >
                <Background />
                <MiniMap zoomable pannable />
                <Controls />
              </ReactFlow>
            </ReactFlowProvider>
          </div>
          <aside className="node-config">
            {selected ? <>
              <div className="config-heading"><div><span>{selected.data.kind}</span><strong>{selected.data.label}</strong></div><div><button onClick={duplicateSelected}><Copy size={14} /></button><button onClick={removeSelected}><Trash2 size={14} /></button></div></div>
              <label>Column key<input disabled value={selected.id} /></label>
              <label>Label<input value={selected.data.label} onChange={(event) => updateSelected({ label: event.target.value })} /></label>
              <label>Width<input type="number" min={80} max={800} value={selected.data.width} onChange={(event) => updateSelected({ width: Number(event.target.value) })} /></label>
              {selected.data.kind === "llm" && <>
                <label>Provider<select value={String(selected.data.config.provider_ref ?? providers[0]?.id ?? "anthropic")} onChange={(event) => updateSelected({ config: { ...selected.data.config, provider_ref: event.target.value } })}>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.display_name} · {provider.configured || provider.credential_mode === "none" ? "ready" : "needs key"}</option>)}</select></label>
                <label>Model override<input value={String(selected.data.config.model ?? "")} onChange={(event) => updateLlmModel(event.target.value)} placeholder={selectedProvider ? `Inherited: ${selectedProvider.default_model}` : "Use provider default"} /></label>
                {selectedProvider && <p className="provider-capability">{selectedProvider.structured_output_mode.replaceAll("_", " ")} · temperature {selectedProvider.default_temperature}</p>}
                <label>Prompt<textarea value={selected.data.prompt ?? ""} onChange={(event) => updateSelected({ prompt: event.target.value })} /></label>
              </>}
              {selected.data.kind !== "input" && <label>Connector config (JSON)<textarea value={JSON.stringify(selected.data.config, null, 2)} onChange={(event) => { try { updateSelected({ config: JSON.parse(event.target.value) }); setError(null); } catch { setError("Connector config must be valid JSON."); } }} /></label>}
              <label>Value JSON Schema<textarea value={JSON.stringify(selected.data.output_schema, null, 2)} onChange={(event) => { try { updateSelected({ output_schema: JSON.parse(event.target.value) }); setError(null); } catch { setError("Output schema must be valid JSON."); } }} /></label>
            </> : <p>Select a node to edit its configuration.</p>}
            {error && <div className="dag-error">{error}</div>}
          </aside>
        </div>
      </section>
    </div>
  );
}
