import type { Board, BoardColumn, Client } from "@e1p/shared-types";
import { Archive, ArrowUpRight, GripVertical, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

export default function CrmPage() {
  const [board, setBoard] = useState<Board>({ columns: [] });
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dragOver, setDragOver] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<Board>("/crm/board");
      setBoard(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo cliente", useCallback(() => setOpen(true), []));

  async function moveTo(clientId: string, fromStage: string | null, stageId: string) {
    if (fromStage === stageId) return;
    // otimista: move o card na UI antes da resposta
    setBoard((b) => optimisticMove(b, clientId, stageId));
    try {
      await api.post(`/crm/clients/${clientId}/move`, { stage_id: stageId });
    } finally {
      load();
    }
  }

  async function createStage() {
    const name = window.prompt("Nome da nova etapa:")?.trim();
    if (!name) return;
    try {
      await api.post("/crm/stages", { name });
    } catch (err) {
      alert(apiErrorMessage(err));
    } finally {
      load();
    }
  }

  async function archiveStage(stageId: string, name: string) {
    if (!confirm(`Arquivar a etapa "${name}"? Os clientes dela vão para a primeira etapa.`)) return;
    try {
      await api.post(`/crm/stages/${stageId}/archive`);
    } catch (err) {
      alert(apiErrorMessage(err));
    } finally {
      load();
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / CRM</p>
        <h1 className="text-2xl font-bold text-neutral-800">Funil de clientes</h1>
        <p className="text-xs text-neutral-400">Arraste os cards entre as colunas.</p>
      </div>

      {loading ? (
        <p className="text-sm text-neutral-400">Carregando...</p>
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {board.columns.map((col) => (
            <Column
              key={col.stage.id}
              column={col}
              isOver={dragOver === col.stage.id}
              onArchive={() => archiveStage(col.stage.id, col.stage.name)}
              onDragOverCol={() => setDragOver(col.stage.id)}
              onDragLeaveCol={() => setDragOver((s) => (s === col.stage.id ? null : s))}
              onDropCard={(clientId, fromStage) => {
                setDragOver(null);
                moveTo(clientId, fromStage, col.stage.id);
              }}
            />
          ))}
          <button
            onClick={createStage}
            className="flex h-12 w-56 shrink-0 items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-neutral-200 text-sm font-medium text-neutral-400 hover:border-primary-300 hover:text-primary-600"
          >
            <Plus size={16} />
            Nova etapa
          </button>
        </div>
      )}

      <NewClientModal open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
  );
}

function optimisticMove(board: Board, clientId: string, stageId: string): Board {
  let moved: Client | undefined;
  const stripped = board.columns.map((c) => {
    const found = c.clients.find((cl) => cl.id === clientId);
    if (found) moved = { ...found, stage_id: stageId };
    return { ...c, clients: c.clients.filter((cl) => cl.id !== clientId) };
  });
  if (!moved) return board;
  return {
    columns: stripped.map((c) =>
      c.stage.id === stageId ? { ...c, clients: [...c.clients, moved!] } : c,
    ),
  };
}

function Column({
  column,
  isOver,
  onArchive,
  onDragOverCol,
  onDragLeaveCol,
  onDropCard,
}: {
  column: BoardColumn;
  isOver: boolean;
  onArchive: () => void;
  onDragOverCol: () => void;
  onDragLeaveCol: () => void;
  onDropCard: (clientId: string, fromStage: string | null) => void;
}) {
  const accent = column.stage.is_won
    ? "text-accent-600"
    : column.stage.is_lost
      ? "text-danger"
      : "text-neutral-600";
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        onDragOverCol();
      }}
      onDragLeave={onDragLeaveCol}
      onDrop={(e) => {
        e.preventDefault();
        const clientId = e.dataTransfer.getData("text/client-id");
        const fromStage = e.dataTransfer.getData("text/from-stage") || null;
        if (clientId) onDropCard(clientId, fromStage);
      }}
      className={`flex w-72 shrink-0 flex-col rounded-2xl p-3 transition ${
        isOver ? "bg-primary-100 ring-2 ring-primary-300" : "bg-neutral-100"
      }`}
    >
      <div className="group mb-3 flex items-center justify-between px-1">
        <span className={`text-sm font-semibold ${accent}`}>{column.stage.name}</span>
        <div className="flex items-center gap-1">
          <span className="rounded-pill bg-white px-2 text-xs text-neutral-500">
            {column.clients.length}
          </span>
          <button
            onClick={onArchive}
            title="Arquivar etapa"
            className="text-neutral-300 opacity-0 transition hover:text-neutral-600 group-hover:opacity-100"
          >
            <Archive size={14} />
          </button>
        </div>
      </div>
      <div className="flex min-h-[60px] flex-col gap-2">
        {column.clients.length === 0 ? (
          <div className="rounded-xl border border-dashed border-neutral-200 py-6 text-center text-xs text-neutral-400">
            Solte um card aqui
          </div>
        ) : (
          column.clients.map((c) => <Card key={c.id} client={c} stageId={column.stage.id} />)
        )}
      </div>
    </div>
  );
}

function Card({ client, stageId }: { client: Client; stageId: string }) {
  const navigate = useNavigate();
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/client-id", client.id);
        e.dataTransfer.setData("text/from-stage", stageId);
        e.dataTransfer.effectAllowed = "move";
      }}
      className="group flex cursor-grab items-start gap-2 rounded-xl bg-white p-3 shadow-sm active:cursor-grabbing"
    >
      <GripVertical size={16} className="mt-0.5 shrink-0 text-neutral-300" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-neutral-800">{client.name}</p>
        {client.tags.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {client.tags.map((t) => (
              <span key={t} className="rounded-pill bg-primary-50 px-2 text-[10px] text-primary-700">
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
      <button
        onClick={() => navigate(`/crm/clients/${client.id}`)}
        title="Abrir ficha 360°"
        className="shrink-0 text-neutral-300 transition hover:text-primary-600 group-hover:text-neutral-500"
      >
        <ArrowUpRight size={16} />
      </button>
    </div>
  );
}

function NewClientModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [tags, setTags] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.post("/crm/clients", {
        name,
        phone: phone || null,
        tags: tags ? tags.split(",").map((t) => t.trim()) : [],
      });
      onCreated();
      setName("");
      setPhone("");
      setTags("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Novo cliente" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome" value={name} onChange={setName} placeholder="Maria Silva" />
        <Field label="Telefone" value={phone} onChange={setPhone} placeholder="+55 11 99999-9999" />
        <Field label="Tags (separadas por vírgula)" value={tags} onChange={setTags} placeholder="VIP, Lead" />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !name}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Criar cliente"}
        </button>
      </div>
    </Modal>
  );
}
