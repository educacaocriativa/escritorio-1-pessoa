import type { Board, BoardColumn, Client } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

export default function CrmPage() {
  const [board, setBoard] = useState<Board>({ columns: [] });
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);

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

  const stages = board.columns.map((c) => c.stage);

  async function move(clientId: string, stageId: string) {
    await api.post(`/crm/clients/${clientId}/move`, { stage_id: stageId });
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / CRM</p>
        <h1 className="text-2xl font-bold text-neutral-800">Funil de clientes</h1>
      </div>

      {loading ? (
        <p className="text-sm text-neutral-400">Carregando...</p>
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {board.columns.map((col) => (
            <Column key={col.stage.id} column={col} stages={stages} onMove={move} />
          ))}
        </div>
      )}

      <NewClientModal open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
  );
}

function Column({
  column,
  stages,
  onMove,
}: {
  column: BoardColumn;
  stages: Board["columns"][number]["stage"][];
  onMove: (clientId: string, stageId: string) => void;
}) {
  const accent = column.stage.is_won
    ? "text-accent-600"
    : column.stage.is_lost
      ? "text-danger"
      : "text-neutral-600";
  return (
    <div className="flex w-72 shrink-0 flex-col rounded-2xl bg-neutral-100 p-3">
      <div className="mb-3 flex items-center justify-between px-1">
        <span className={`text-sm font-semibold ${accent}`}>{column.stage.name}</span>
        <span className="rounded-pill bg-white px-2 text-xs text-neutral-500">
          {column.clients.length}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {column.clients.length === 0 ? (
          <div className="rounded-xl border border-dashed border-neutral-200 py-6 text-center text-xs text-neutral-400">
            Sem clientes
          </div>
        ) : (
          column.clients.map((c) => (
            <Card key={c.id} client={c} stages={stages} onMove={onMove} />
          ))
        )}
      </div>
    </div>
  );
}

function Card({
  client,
  stages,
  onMove,
}: {
  client: Client;
  stages: Board["columns"][number]["stage"][];
  onMove: (clientId: string, stageId: string) => void;
}) {
  return (
    <div className="rounded-xl bg-white p-3 shadow-sm">
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
      <select
        value={client.stage_id ?? ""}
        onChange={(e) => onMove(client.id, e.target.value)}
        className="mt-2 w-full rounded-lg border border-neutral-200 px-2 py-1 text-xs text-neutral-500 outline-none"
      >
        {stages.map((s) => (
          <option key={s.id} value={s.id}>
            Mover para: {s.name}
          </option>
        ))}
      </select>
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
