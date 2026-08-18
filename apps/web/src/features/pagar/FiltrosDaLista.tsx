import type { PayableStatus } from "@e1p/shared-types";
import type { CostCenter } from "../financeiro/costCenters";
import type { ChartAccount } from "../financeiro/planoContas";
import type { FiltroPagar } from "./filtros";

/** Os recortes de status que a tela oferece. "Em aberto" são DOIS status, não um. */
const RECORTES: { value: string; label: string; status: PayableStatus[] }[] = [
  { value: "abertas", label: "Em aberto", status: ["open", "scheduled"] },
  { value: "paid", label: "Pago", status: ["paid"] },
  { value: "scheduled", label: "Agendada", status: ["scheduled"] },
  { value: "canceled", label: "Cancelado", status: ["canceled"] },
];

function valorDoRecorte(status: PayableStatus[]): string {
  const achado = RECORTES.find(
    (r) => r.status.length === status.length && r.status.every((s) => status.includes(s)),
  );
  return achado?.value ?? "abertas";
}

const campo =
  "min-h-[44px] rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400";

/**
 * A barra de recorte da lista.
 *
 * `flex-wrap` e não largura fixa: em 360px estes cinco controles refluem em duas linhas em vez de
 * se espremerem a ponto de o polegar não acertar nenhum. O gate de layout mede isso de verdade em
 * `e2e/pagar-360.spec.ts` — por `boundingBox`, não por classe CSS.
 *
 * ⚠️ Os controles usam SÓ `aria-label`, sem um `<label>` irmão com o mesmo texto: os dois juntos
 * fazem `getByLabel` casar duas vezes e o gate falha por strict mode do Playwright, não por
 * defeito da tela.
 */
export default function FiltrosDaLista({
  valor,
  onChange,
  categorias,
  centros,
}: {
  valor: FiltroPagar;
  onChange: (f: FiltroPagar) => void;
  categorias: ChartAccount[];
  centros: CostCenter[];
}) {
  const padraoAtivo =
    valor.q === "" && valor.centroDeCusto === "" && valor.categoria === "" && valor.de === null;

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={valor.q}
          onChange={(e) => onChange({ ...valor, q: e.target.value })}
          placeholder="Buscar fornecedor ou descrição"
          aria-label="Buscar fornecedor ou descrição"
          className={`${campo} min-w-0 flex-1 basis-56`}
        />

        <select
          aria-label="Status"
          value={valorDoRecorte(valor.status)}
          onChange={(e) => {
            const r = RECORTES.find((x) => x.value === e.target.value)!;
            // Histórico não tem por que herdar o horizonte de "o que eu devo": quem procura o que
            // já pagou quer olhar para trás, e um teto no fim do mês que vem não recorta nada ali.
            const olhandoParaTras = r.status.every((s) => s === "paid" || s === "canceled");
            onChange({ ...valor, status: r.status, ate: olhandoParaTras ? null : valor.ate });
          }}
          className={campo}
        >
          {RECORTES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>

        <input
          type="date"
          aria-label="Vencimento até"
          value={valor.ate ?? ""}
          onChange={(e) => onChange({ ...valor, ate: e.target.value || null })}
          className={campo}
        />

        <select
          aria-label="Centro de custo"
          value={valor.centroDeCusto}
          onChange={(e) => onChange({ ...valor, centroDeCusto: e.target.value })}
          className={campo}
        >
          <option value="">Todos os centros</option>
          {centros.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>

        <select
          aria-label="Categoria"
          value={valor.categoria}
          onChange={(e) => onChange({ ...valor, categoria: e.target.value })}
          className={campo}
        >
          <option value="">Todas as categorias</option>
          {categorias.map((a) => (
            <option key={a.id} value={a.id}>
              {a.categoria}
            </option>
          ))}
        </select>
      </div>

      {!padraoAtivo && (
        <button
          onClick={() => onChange({ ...valor, q: "", centroDeCusto: "", categoria: "", de: null })}
          className="mt-3 min-h-[44px] text-xs font-medium text-neutral-500 hover:text-primary-600"
        >
          Limpar filtros
        </button>
      )}
    </div>
  );
}
