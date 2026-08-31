import type { PayableStatus } from "@e1p/shared-types";
import { useState } from "react";
import type { CostCenter } from "../financeiro/costCenters";
import type { ChartAccount } from "../financeiro/planoContas";
import type { FiltroPagar } from "./filtros";

/**
 * Os recortes de status que a tela oferece. "Em aberto" são DOIS status, não um; "Todos" é
 * ZERO status — `paraQuery`/`paraUrl`/`ordem` (`filtros.ts`) já tratam `status: []` como "sem
 * filtro", então este recorte não precisa de nenhum código novo fora desta lista.
 */
const RECORTES: { value: string; label: string; status: PayableStatus[] }[] = [
  { value: "todos", label: "Todos", status: [] },
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
 * ⚠️ **Dois dos cinco controles ficam atrás de "Mais filtros" no celular — e isso foi MEDIDO, não
 * suposto.** A primeira versão punha os cinco na mesma linha com `flex-wrap`: em 360px eles
 * refluíam em CINCO linhas e a barra sozinha ocupava ~300px. Somada aos cards de topo (192px), ela
 * empurrava a tabela para `y=765` — fora de uma dobra de 740px. A lista é o motivo de a página
 * existir; ela não pode nascer abaixo da dobra para que um filtro de centro de custo caiba acima.
 *
 * Acima de `sm` os cinco aparecem juntos: lá há largura para isso e o custo não existe.
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
  const [maisFiltros, setMaisFiltros] = useState(false);
  const padraoAtivo =
    valor.q === "" && valor.centroDeCusto === "" && valor.categoria === "" && valor.de === null;
  // As duas dimensões extras ficam recolhidas SÓ no celular; de `sm` para cima elas são visíveis
  // sempre, e o botão que as revela desaparece.
  const extras = `${maisFiltros ? "flex" : "hidden"} sm:flex w-full gap-3 sm:w-auto`;

  return (
    <div data-testid="filtros-da-lista" className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={valor.q}
          onChange={(e) => onChange({ ...valor, q: e.target.value })}
          placeholder="Buscar fornecedor ou descrição"
          aria-label="Buscar fornecedor ou descrição"
          className={`${campo} w-full min-w-0 sm:w-auto sm:flex-1 sm:basis-56`}
        />

        <select
          aria-label="Status"
          value={valorDoRecorte(valor.status)}
          onChange={(e) => {
            const r = RECORTES.find((x) => x.value === e.target.value)!;
            // Histórico não tem por que herdar o horizonte de "o que eu devo": quem procura o que
            // já pagou quer olhar para trás, e um teto no fim do mês que vem não recorta nada ali.
            // `r.status.length > 0` evita que "Todos" (status: []) caia aqui por vacuidade do
            // `.every` — mesma guarda que `ordem()` usa em `filtros.ts`.
            const olhandoParaTras =
              r.status.length > 0 && r.status.every((s) => s === "paid" || s === "canceled");
            onChange({ ...valor, status: r.status, ate: olhandoParaTras ? null : valor.ate });
          }}
          className={`${campo} min-w-0 flex-1 sm:flex-none`}
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
          className={`${campo} min-w-0 flex-1 sm:flex-none`}
        />

        <div className={extras}>
          <select
            aria-label="Centro de custo"
            value={valor.centroDeCusto}
            onChange={(e) => onChange({ ...valor, centroDeCusto: e.target.value })}
            className={`${campo} min-w-0 flex-1 sm:flex-none`}
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
            className={`${campo} min-w-0 flex-1 sm:flex-none`}
          >
            <option value="">Todas as categorias</option>
            {categorias.map((a) => (
              <option key={a.id} value={a.id}>
                {a.categoria}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <button
          onClick={() => setMaisFiltros((v) => !v)}
          aria-expanded={maisFiltros}
          className="min-h-[44px] text-xs font-medium text-neutral-500 hover:text-primary-600 sm:hidden"
        >
          {maisFiltros ? "Menos filtros" : "Mais filtros"}
        </button>

        {!padraoAtivo && (
          <button
            onClick={() =>
              onChange({ ...valor, q: "", centroDeCusto: "", categoria: "", de: null })
            }
            className="min-h-[44px] text-xs font-medium text-neutral-500 hover:text-primary-600"
          >
            Limpar filtros
          </button>
        )}
      </div>
    </div>
  );
}
