import type { FunnelComponentCategory } from "@e1p/shared-types";
import html2canvas from "html2canvas";
import { ArrowLeft, Download, Maximize2, Save, Share2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  type Connection,
  Handle,
  MiniMap,
  type Node,
  type NodeProps,
  Position,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "reactflow";
import "reactflow/dist/style.css";
import { api, apiErrorMessage } from "../../lib/api";

type NodeData = { label: string; description: string; color: string; category: string; key: string };

function FunnelNode({ data, selected }: NodeProps<NodeData>) {
  return (
    <div
      className="rounded-xl bg-white px-3 py-2 shadow-sm"
      style={{
        borderLeft: `5px solid ${data.color}`,
        outline: selected ? `2px solid ${data.color}` : "1px solid #E5E7EB",
        minWidth: 150, maxWidth: 200,
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: data.color }} />
      <p className="text-sm font-semibold text-neutral-800">{data.label}</p>
      <p className="mt-0.5 text-[11px] leading-tight text-neutral-400">{data.description}</p>
      <Handle type="source" position={Position.Bottom} style={{ background: data.color }} />
    </div>
  );
}

const nodeTypes = { funnelNode: FunnelNode };

function Builder() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id || id === "novo";

  const [funnelId, setFunnelId] = useState<string | null>(isNew ? null : id!);
  const [name, setName] = useState("Novo funil");
  const [catalog, setCatalog] = useState<FunnelComponentCategory[]>([]);
  const [openCat, setOpenCat] = useState<string>("gatilhos");
  const [present, setPresent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "ok" | "err" } | null>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const wrapper = useRef<HTMLDivElement>(null);
  const addCount = useRef(0);
  const { screenToFlowPosition } = useReactFlow();

  const notify = useCallback((msg: string, type: "ok" | "err" = "ok") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2600);
  }, []);

  useEffect(() => {
    api.get<FunnelComponentCategory[]>("/funnels/components").then(({ data }) => setCatalog(data));
  }, []);

  useEffect(() => {
    if (!isNew && id) {
      api.get(`/funnels/${id}`).then(({ data }) => {
        setName(data.name);
        setNodes(data.nodes ?? []);
        setEdges(data.edges ?? []);
      });
    }
  }, [isNew, id, setNodes, setEdges]);

  const onConnect = useCallback(
    (c: Connection) => {
      setEdges((eds) => addEdge({ ...c, animated: true }, eds));
      notify("Ponto de conexão estabelecido!");
    },
    [setEdges, notify],
  );

  const makeNode = useCallback(
    (item: { key: string; label: string; description: string }, color: string, category: string,
     position: { x: number; y: number }): Node<NodeData> => ({
      id: crypto.randomUUID(),
      type: "funnelNode",
      position,
      data: { label: item.label, description: item.description, color, category, key: item.key },
    }),
    [],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData("application/e1p-funnel");
      if (!raw) return;
      const item = JSON.parse(raw);
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      setNodes((nds) => nds.concat(makeNode(item, item.color, item.category, position)));
    },
    [screenToFlowPosition, setNodes, makeNode],
  );

  // "Arraste OU clique para adicionar": clique posiciona perto do centro do canvas.
  const addByClick = useCallback(
    (item: { key: string; label: string; description: string }, color: string, category: string) => {
      const rect = wrapper.current?.getBoundingClientRect();
      const off = (addCount.current++ % 6) * 30;
      const center = rect
        ? screenToFlowPosition({ x: rect.left + rect.width / 2 + off, y: rect.top + 140 + off })
        : { x: 120 + off, y: 120 + off };
      setNodes((nds) => nds.concat(makeNode(item, color, category, center)));
    },
    [screenToFlowPosition, setNodes, makeNode],
  );

  function updateSelected(patch: Partial<NodeData>) {
    setNodes((nds) =>
      nds.map((n) => (n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n)),
    );
  }
  function removeNode(nid: string) {
    setNodes((nds) => nds.filter((n) => n.id !== nid));
    setEdges((eds) => eds.filter((e) => e.source !== nid && e.target !== nid));
    setSelectedId(null);
  }

  async function save() {
    setSaving(true);
    try {
      const payload = { name, nodes, edges };
      let res;
      if (funnelId) {
        res = (await api.patch(`/funnels/${funnelId}`, payload)).data;
      } else {
        res = (await api.post("/funnels", payload)).data;
        setFunnelId(res.id);
        window.history.replaceState(null, "", `/funis/${res.id}`);
      }
      notify("Funil salvo");
    } catch (err) {
      notify(apiErrorMessage(err) || "Erro ao salvar o funil", "err");
    } finally {
      setSaving(false);
    }
  }

  async function share() {
    const fid = funnelId ?? (await (async () => { await save(); return funnelId; })());
    const url = `${window.location.origin}/funis/${fid ?? ""}`;
    try {
      await navigator.clipboard.writeText(url);
      notify("Link do funil copiado");
    } catch {
      notify("Não foi possível copiar o link", "err");
    }
  }

  async function downloadPng() {
    const pane = wrapper.current?.querySelector(".react-flow") as HTMLElement | null;
    if (!pane) return;
    const canvas = await html2canvas(pane, { backgroundColor: "#F9FAFB", scale: 2 });
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `${name.replace(/\s+/g, "-").toLowerCase() || "funil"}.png`;
    a.click();
  }

  const selectedNode = nodes.find((n) => n.id === selectedId) as Node<NodeData> | undefined;

  return (
    <div className="flex h-full flex-col">
      {!present && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <button onClick={() => navigate("/funis")} className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-700">
            <ArrowLeft size={16} /> Funis
          </button>
          <input value={name} onChange={(e) => setName(e.target.value)} className="rounded-lg border border-neutral-200 px-3 py-1.5 text-sm font-medium outline-none focus:border-primary-400" />
          <div className="flex items-center gap-2">
            <button onClick={downloadPng} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-200">
              <Download size={14} /> Baixar PNG
            </button>
            <button onClick={share} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-200">
              <Share2 size={14} /> Compartilhar
            </button>
            <button onClick={() => setPresent(true)} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-200">
              <Maximize2 size={14} /> Apresentação
            </button>
            <button onClick={save} disabled={saving} className="flex items-center gap-1.5 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-50">
              <Save size={14} /> {saving ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-1 gap-3 overflow-hidden">
        {/* Paleta de componentes */}
        {!present && (
          <div className="w-60 shrink-0 overflow-auto rounded-2xl bg-white p-2 shadow-sm">
            <p className="px-2 py-1 text-xs font-medium text-neutral-500">Arraste ou clique para adicionar</p>
            {catalog.map((cat) => (
              <div key={cat.category} className="mb-1">
                <button
                  onClick={() => setOpenCat((c) => (c === cat.category ? "" : cat.category))}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-bold uppercase tracking-wide text-neutral-500 hover:bg-neutral-50"
                >
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: cat.color }} />
                  {cat.label}
                  <span className="ml-auto text-neutral-300">{cat.items.length}</span>
                </button>
                {openCat === cat.category && (
                  <div className="space-y-1 py-1">
                    {cat.items.map((it) => (
                      <div
                        key={it.key}
                        draggable
                        onDragStart={(e) =>
                          e.dataTransfer.setData(
                            "application/e1p-funnel",
                            JSON.stringify({ ...it, color: cat.color, category: cat.category }),
                          )
                        }
                        onClick={() => addByClick(it, cat.color, cat.category)}
                        className="cursor-pointer rounded-lg border border-neutral-100 px-2 py-1.5 text-xs hover:border-neutral-300"
                        style={{ borderLeft: `4px solid ${cat.color}` }}
                        title={it.description}
                      >
                        <span className="font-medium text-neutral-700">{it.label}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Canvas */}
        <div ref={wrapper} className="relative flex-1 overflow-hidden rounded-2xl border border-neutral-200 bg-neutral-50">
          {present && (
            <button onClick={() => setPresent(false)} className="absolute right-3 top-3 z-20 rounded-pill bg-white px-3 py-1.5 text-xs font-semibold text-neutral-600 shadow-sm">
              Sair da apresentação
            </button>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_e, n) => setSelectedId(n.id)}
            onPaneClick={() => setSelectedId(null)}
            onDrop={onDrop}
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
            nodeTypes={nodeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={16} color="#E5E7EB" />
            {!present && <Controls />}
            {!present && <MiniMap pannable zoomable nodeColor={(n) => (n.data as NodeData)?.color ?? "#999"} />}
          </ReactFlow>

          {nodes.length === 0 && !present && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-neutral-400">
              Arraste ou clique nos componentes à esquerda para montar o funil.
            </div>
          )}

          {/* Configurações Rápidas do nó selecionado */}
          {!present && selectedNode && (
            <div className="absolute right-3 top-3 z-10 w-64 rounded-2xl bg-white p-4 shadow-card">
              <div className="mb-3 flex items-center gap-2">
                <span className="h-3 w-3 rounded-full" style={{ background: selectedNode.data.color }} />
                <p className="text-sm font-bold text-neutral-800">Configurações Rápidas</p>
              </div>
              <label className="mb-2 block">
                <span className="mb-1 block text-xs font-medium text-neutral-600">Rótulo / Título</span>
                <input value={selectedNode.data.label} onChange={(e) => updateSelected({ label: e.target.value })} className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none focus:border-primary-400" />
              </label>
              <label className="mb-2 block">
                <span className="mb-1 block text-xs font-medium text-neutral-600">Descrição</span>
                <textarea value={selectedNode.data.description} onChange={(e) => updateSelected({ description: e.target.value })} rows={3} className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none focus:border-primary-400" />
              </label>
              <p className="mb-3 text-[11px] text-neutral-400">
                ID e Chave: <span className="font-mono text-neutral-500">{selectedNode.data.key || selectedNode.id.slice(0, 8)}</span>
              </p>
              <button onClick={() => removeNode(selectedNode.id)} className="flex w-full items-center justify-center gap-1.5 rounded-pill bg-red-50 py-2 text-sm font-semibold text-danger hover:bg-red-100">
                <Trash2 size={14} /> Remover Nó
              </button>
            </div>
          )}

          {/* Toast */}
          {toast && (
            <div
              className={`absolute bottom-4 left-1/2 z-30 -translate-x-1/2 rounded-pill px-4 py-2 text-sm font-semibold text-white shadow-lg ${toast.type === "err" ? "bg-danger" : "bg-neutral-800"}`}
            >
              {toast.msg}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function FunnelBuilderPage() {
  return (
    <ReactFlowProvider>
      <Builder />
    </ReactFlowProvider>
  );
}
