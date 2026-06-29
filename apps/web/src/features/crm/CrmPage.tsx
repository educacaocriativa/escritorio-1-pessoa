import type { Board, BoardColumn, Client } from "@e1p/shared-types";

/**
 * CRM & Funil Kanban — board de colunas com cards de clientes.
 * Esqueleto da UI (drag-and-drop e fetch entram com o login). O backend já expõe
 * /crm/board, /crm/clients e /crm/clients/{id}/move.
 */
export default function CrmPage() {
  // Estrutura ilustrativa das colunas padrão (virá de GET /crm/board).
  const board: Board = {
    columns: ["Entrada", "Em contato", "Proposta", "Ganho", "Perda"].map((name, i) => ({
      stage: {
        id: String(i),
        name,
        position: i,
        is_won: name === "Ganho",
        is_lost: name === "Perda",
      },
      clients: [],
    })),
  };

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / CRM</p>
        <h1 className="text-2xl font-bold text-neutral-800">Funil de clientes</h1>
      </div>

      <div className="flex gap-4 overflow-x-auto pb-4">
        {board.columns.map((col) => (
          <Column key={col.stage.id} column={col} />
        ))}
      </div>
    </div>
  );
}

function Column({ column }: { column: BoardColumn }) {
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
          column.clients.map((c) => <Card key={c.id} client={c} />)
        )}
      </div>
    </div>
  );
}

function Card({ client }: { client: Client }) {
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
    </div>
  );
}
