import type { FunnelComponentCategory } from "@e1p/shared-types";
import html2canvas from "html2canvas";
import {
  ArrowLeft, Download, GitBranch, type LucideIcon, Maximize2, MessageCircle, MousePointerClick,
  Save, Share2, Sparkles, Trash2, TrendingUp, Zap,
} from "lucide-react";
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

type NodeConfig = { subject?: string; body?: string; model?: string };
type NodeData = {
  label: string; description: string; color: string; category: string; key: string;
  shape?: "page" | "node";
  config?: NodeConfig;
};

const CAT_ICON: Record<string, LucideIcon> = {
  gatilhos: Zap, logica: GitBranch, acoes: MousePointerClick,
  comunicacao: MessageCircle, trafego: TrendingUp,
};
const PAGE_MODELS = ["Vendas", "Captura", "Obrigado", "Checkout", "Download", "Webinar", "Conteúdo"];

// Tipo de conteúdo editável conforme o componente.
const EMAIL_KEYS = new Set(["email-base", "enviar-email", "sequencia-email"]);
const MSG_KEYS = new Set(["whatsapp", "sequencia-whatsapp", "dm-instagram", "manychat", "telegram"]);
const SMS_KEYS = new Set(["sms"]);
function contentKind(key: string): "email" | "whatsapp" | "sms" | "generic" {
  if (EMAIL_KEYS.has(key)) return "email";
  if (MSG_KEYS.has(key)) return "whatsapp";
  if (SMS_KEYS.has(key)) return "sms";
  return "generic";
}
const KIND_VERB: Record<string, string> = {
  email: "Criar e-mail", whatsapp: "Escrever mensagem", sms: "Escrever SMS",
  generic: "Configurar conteúdo",
};

/** Mockup de página que muda conforme o "Modelo de página" escolhido. */
function PageMockup({ model, color }: { model?: string; color: string }) {
  const cta = (text: string) => (
    <div className="mt-1 h-5 w-full rounded-md text-center text-[9px] font-bold leading-5 text-white" style={{ background: color }}>
      {text}
    </div>
  );
  const line = (w: string, light = false) => (
    <div className={`h-2 rounded ${light ? "bg-neutral-100" : "bg-neutral-200"}`} style={{ width: w }} />
  );
  switch (model) {
    case "Captura":
      return (<>{line("60%")}<div className="h-4 rounded border border-neutral-200" /><div className="h-4 rounded border border-neutral-200" />{cta("QUERO!")}</>);
    case "Obrigado":
      return (
        <div className="flex flex-col items-center gap-1.5 py-1">
          <div className="flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold text-white" style={{ background: color }}>✓</div>
          {line("70%")}{line("45%", true)}
        </div>
      );
    case "Checkout":
      return (
        <>
          <div className="flex justify-between gap-2">{line("50%")}{line("18%")}</div>
          <div className="flex justify-between gap-2">{line("40%", true)}{line("18%", true)}</div>
          {cta("PAGAR")}
        </>
      );
    case "Download":
      return (<><div className="mx-auto h-8 w-10 rounded" style={{ background: `${color}33` }} /><div className="mx-auto h-2 w-2/3 rounded bg-neutral-100" />{cta("BAIXAR")}</>);
    case "Webinar":
      return (
        <>
          <div className="flex h-9 items-center justify-center rounded bg-neutral-800 text-[11px] text-white">▶</div>
          {line("70%", true)}
          {cta("ASSISTIR")}
        </>
      );
    case "Vendas":
      return (<><div className="h-6 rounded" style={{ background: `${color}33` }} />{line("75%")}{line("100%", true)}{cta("COMPRAR")}</>);
    default: // Conteúdo
      return (<>{line("75%")}{line("100%", true)}{line("85%", true)}<div className="mt-1 h-5 w-2/3 rounded-md" style={{ background: color }} /></>);
  }
}

function FunnelNode({ data, selected }: NodeProps<NodeData>) {
  const configured = !!(data.config?.body || data.config?.model);
  const handleStyle = { background: "#fff", border: `2px solid ${data.color}`, width: 10, height: 10 };

  // PÁGINA → card quadrado com mockup colorido.
  if (data.shape === "page") {
    return (
      <div
        className="relative w-[156px] rounded-2xl bg-white shadow-md"
        style={{ outline: selected ? `3px solid ${data.color}` : "1px solid #E5E7EB" }}
      >
        <Handle type="target" position={Position.Top} style={handleStyle} />
        <div className="flex items-center gap-1 rounded-t-2xl px-2.5 py-1.5" style={{ background: data.color }}>
          <span className="h-2 w-2 rounded-full bg-white/70" />
          <span className="h-2 w-2 rounded-full bg-white/50" />
          <span className="h-2 w-2 rounded-full bg-white/40" />
          <span className="ml-1 truncate text-[10px] font-bold uppercase tracking-wide text-white">
            {data.config?.model || "Página"}
          </span>
        </div>
        <div className="space-y-1.5 p-3">
          <PageMockup model={data.config?.model} color={data.color} />
        </div>
        <p className="truncate border-t border-neutral-100 px-3 py-1.5 text-xs font-semibold text-neutral-800">
          {data.label}
        </p>
        {configured && <span className="absolute right-2 top-2 h-2.5 w-2.5 rounded-full bg-accent-500 ring-2 ring-white" />}
        <Handle type="source" position={Position.Bottom} style={handleStyle} />
      </div>
    );
  }

  // AÇÃO/LÓGICA/COMUNICAÇÃO/TRÁFEGO → círculo colorido com ícone + rótulo abaixo.
  const Icon = CAT_ICON[data.category] ?? Zap;
  return (
    <div
      className="relative flex h-16 w-16 items-center justify-center rounded-full text-white shadow-md"
      style={{ background: data.color, outline: selected ? `3px solid ${data.color}66` : "none" }}
    >
      <Handle type="target" position={Position.Top} style={handleStyle} />
      <Icon size={24} />
      {configured && <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full bg-accent-500 ring-2 ring-white" />}
      <span className="pointer-events-none absolute left-1/2 top-[112%] w-28 -translate-x-1/2 text-center text-[11px] font-semibold leading-tight text-neutral-700">
        {data.label}
      </span>
      <Handle type="source" position={Position.Bottom} style={handleStyle} />
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
  const [editing, setEditing] = useState<string | null>(null);
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
    (item: { key: string; label: string; description: string; shape?: "page" | "node" },
     color: string, category: string,
     position: { x: number; y: number }): Node<NodeData> => ({
      id: crypto.randomUUID(),
      type: "funnelNode",
      position,
      data: {
        label: item.label, description: item.description, color, category, key: item.key,
        shape: item.shape ?? "node",
      },
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
              <button
                onClick={() => setEditing(selectedNode.id)}
                className="mb-2 flex w-full items-center justify-center gap-1.5 rounded-pill bg-primary-500 py-2 text-sm font-semibold text-white hover:bg-primary-600"
              >
                <Sparkles size={14} />{" "}
                {selectedNode.data.shape === "page"
                  ? "Editar página"
                  : KIND_VERB[contentKind(selectedNode.data.key)]}
                {selectedNode.data.config?.body || selectedNode.data.config?.model ? " ✓" : ""}
              </button>
              <p className="mb-3 text-[11px] text-neutral-400">
                ID e Chave: <span className="font-mono text-neutral-500">{selectedNode.data.key || selectedNode.id.slice(0, 8)}</span>
              </p>
              <button onClick={() => removeNode(selectedNode.id)} className="flex w-full items-center justify-center gap-1.5 rounded-pill bg-red-50 py-2 text-sm font-semibold text-danger hover:bg-red-100">
                <Trash2 size={14} /> Remover Nó
              </button>
            </div>
          )}

          {/* Editor de conteúdo do nó (e-mail / mensagem / genérico) */}
          {editing && (() => {
            const node = nodes.find((n) => n.id === editing) as Node<NodeData> | undefined;
            if (!node) return null;
            return (
              <NodeContentEditor
                node={node}
                onClose={() => setEditing(null)}
                onSave={(config) => {
                  setNodes((nds) =>
                    nds.map((n) => (n.id === editing ? { ...n, data: { ...n.data, config } } : n)),
                  );
                  setEditing(null);
                  notify("Conteúdo salvo no nó");
                }}
              />
            );
          })()}

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

function NodeContentEditor({
  node,
  onClose,
  onSave,
}: {
  node: Node<NodeData>;
  onClose: () => void;
  onSave: (config: NodeConfig) => void;
}) {
  const isPage = node.data.shape === "page";
  const kind = contentKind(node.data.key);
  const isEmail = kind === "email";
  const [subject, setSubject] = useState(node.data.config?.subject ?? "");
  const [body, setBody] = useState(node.data.config?.body ?? "");
  const [model, setModel] = useState(node.data.config?.model ?? (isPage ? "Vendas" : ""));
  const [brief, setBrief] = useState("");
  const [aiBusy, setAiBusy] = useState(false);

  const title = isPage ? "Editar página" : KIND_VERB[kind];
  const bodyLabel = isPage
    ? "Conteúdo da página"
    : isEmail ? "Corpo do e-mail" : kind === "generic" ? "Conteúdo" : "Mensagem";

  async function generate() {
    setAiBusy(true);
    try {
      const { data } = await api.post<{ subject: string; body: string }>("/funnels/ai-compose", {
        kind,
        prompt: brief.trim() || node.data.label,
      });
      if (isEmail && data.subject) setSubject(data.subject);
      setBody(data.body);
    } finally {
      setAiBusy(false);
    }
  }

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-card" onClick={(e) => e.stopPropagation()}>
        <div className="mb-1 flex items-center gap-2">
          <span className="h-3 w-3 rounded-full" style={{ background: node.data.color }} />
          <h3 className="text-lg font-bold text-neutral-800">{title}</h3>
        </div>
        <p className="mb-4 text-xs text-neutral-400">{node.data.label}</p>

        {isPage && (
          <label className="mb-3 block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Modelo de página</span>
            <select value={model} onChange={(e) => setModel(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              {PAGE_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
        )}

        <div className="mb-3 rounded-lg bg-primary-50 p-2">
          <span className="mb-1 block text-xs font-medium text-primary-700">Gerar com IA</span>
          <div className="flex gap-2">
            <input value={brief} onChange={(e) => setBrief(e.target.value)} placeholder={`Sobre o que? (ex: ${node.data.label.toLowerCase()})`} className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
            <button onClick={generate} disabled={aiBusy} className="flex shrink-0 items-center gap-1 rounded-lg bg-primary-500 px-3 text-xs font-semibold text-white disabled:opacity-60">
              <Sparkles size={12} /> {aiBusy ? "..." : "Gerar"}
            </button>
          </div>
        </div>

        {isEmail && (
          <label className="mb-3 block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Assunto</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
          </label>
        )}
        <label className="mb-4 block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">{bodyLabel}</span>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={isEmail ? 8 : 5} placeholder={`Escreva ${bodyLabel.toLowerCase()}...`} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
        </label>

        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-pill bg-neutral-100 py-2.5 font-semibold text-neutral-600 hover:bg-neutral-200">Cancelar</button>
          <button onClick={() => onSave({ subject: isEmail ? subject : "", body, model: isPage ? model : undefined })} className="flex-1 rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500">
            Salvar no nó
          </button>
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
