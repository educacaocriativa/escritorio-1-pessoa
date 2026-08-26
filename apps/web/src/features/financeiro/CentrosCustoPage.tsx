import { Archive, Pencil } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import {
  type CostCenter,
  type CostCenterBucket,
  type CostCenterReport,
  COST_CENTER_KINDS,
  formatBRL,
  kindLabel,
} from "./costCenters";

/**
 * Centros de custo (Story 5.5) — 2ª dimensão de análise. CRUD (criar/editar/arquivar) + um
 * comparativo do mês por centro de custo (cruza o resultado lado a lado, incl. "Não atribuído").
 * A dimensão é sempre opcional; quem não usa não é obrigado. Design "Portal", PT-BR.
 */

/** Primeiro/último dia do mês corrente (bordas de data de calendário, sem depender de fuso). */
function currentMonthRange(): { start: string; end: string } {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth();
  const lastDay = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const mm = String(m + 1).padStart(2, "0");
  return { start: `${y}-${mm}-01`, end: `${y}-${mm}-${String(lastDay).padStart(2, "0")}` };
}

export default function CentrosCustoPage() {
  const [centers, setCenters] = useState<CostCenter[]>([]);
  const [report, setReport] = useState<CostCenterReport | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CostCenter | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const { start, end } = currentMonthRange();
    try {
      const [c, r] = await Promise.all([
        api.get<CostCenter[]>("/cost-centers", {
          params: { include_archived: includeArchived },
        }),
        api.get<CostCenterReport>("/financial-intelligence/by-cost-center", {
          params: { start, end },
        }),
      ]);
      setCenters(c.data);
      // Guarda de FORMA (issue #247): `report.buckets.length`/`.map` rodam direto no render, sem
      // `?.`. `Array.isArray`, no molde de `CrmPage.tsx` (#225): guarda por CAMPO, com `null`
      // quando o campo não é array — a render já checa `report && report.buckets...`, então
      // `null` é o mesmo estado seguro que existe ANTES da resposta chegar.
      setReport(Array.isArray(r.data?.buckets) ? r.data : null);
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }, [includeArchived]);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo centro de custo", useCallback(() => setOpen(true), []));

  async function archive(id: string) {
    if (!confirm("Arquivar este centro de custo? O histórico já vinculado é preservado.")) return;
    await api.post(`/cost-centers/${id}/archive`);
    load();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Centros de custo</p>
          <h1 className="text-2xl font-bold text-neutral-800">Centros de custo</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Uma 2ª dimensão opcional (por sócio, área ou unidade) para cruzar o financeiro. Quem não
            usa não é obrigado — lançamentos sem centro aparecem como "Não atribuído".
          </p>
        </div>
        {/* O alvo é a LINHA INTEIRA do rótulo, não a caixinha: o `<input>` nasce com **13×13px**
            e engordá-lo para 44×44 desenharia um quadrado do tamanho de um botão. O `<label>` já
            alterna o estado em qualquer ponto da sua área — mesma convenção do «Mostrar
            arquivadas» de `ContasSaldosPage.tsx`. O `h-5 w-5` é só para a caixinha parar de ser um
            ponto; quem cumpre os 44px é o `min-h-[44px]` da linha. */}
        <label className="flex min-h-[44px] items-center gap-3 text-sm text-neutral-600">
          <input
            type="checkbox"
            className="h-5 w-5 shrink-0"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          Mostrar arquivados
        </label>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {centers.length === 0 ? (
        <p className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">
          Nenhum centro de custo ainda. Clique em "Novo centro de custo".
        </p>
      ) : (
        <div data-testid="lista-centros" className="overflow-hidden rounded-2xl bg-white shadow-sm">
          <ul className="divide-y divide-neutral-50">
            {centers.map((c) => (
              // Sem o `flex-wrap` desta linha, um nome longo empurrava as duas acoes para fora
              // do cartao: «Editar» comecava em x=637 e «Arquivar» em x=699 numa tela de 360px —
              // INTEIRAMENTE fora, sem rolagem de escape. Nao dava para editar nem arquivar um
              // centro de custo no celular. Medido em #144.
              //
              // ⚠️ **O `min-w-0` dos dois `<span>` abaixo é que faz o `break-words` valer algo**
              // (#157). Item de flex nasce com `min-width: auto`, ou seja, não encolhe abaixo do
              // seu min-content — e o min-content de um nome de 74 chars SEM espaço é o nome
              // inteiro. Enquanto isso valer, o span CRESCE em vez de transbordar: o
              // `scrollWidth` dele continua igual ao `clientWidth`, e a régua que lê `scrollWidth`
              // não acusa nada. Quem via o defeito era a BORDA do cartão — 215,5px de nome e
              // 301,4px do pill terminando fora dela, com a página inteira ainda medindo 360
              // porque o `overflow-hidden` do cartão engolia o excesso em silêncio.
              //
              // `min-w-0` sozinho também não basta: encolhida a caixa, o texto sem espaço não tem
              // onde quebrar e vaza como tinta. Os dois juntos, medidos, zeram os dois cortes.
              <li
                key={c.id}
                data-testid="item-centro"
                className="flex flex-wrap items-center justify-between gap-2 px-5 py-3"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    className={
                      c.archived_at
                        ? "min-w-0 break-words text-sm text-neutral-400 line-through"
                        : "min-w-0 break-words text-sm font-medium text-neutral-800"
                    }
                  >
                    {c.name}
                  </span>
                  <span className="whitespace-nowrap rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                    {kindLabel(c.kind)}
                  </span>
                  {c.archived_at && (
                    <span className="whitespace-nowrap rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                      Arquivado
                    </span>
                  )}
                </span>
                {!c.archived_at && (
                  <span className="flex items-center gap-3">
                    {/* `min-h-[44px]` nas DUAS ações. O #156 as trouxe para dentro da tela e
                        parou aí: alcançáveis, e de **16px** de altura. «Arquivar» é destrutiva e
                        pede confirmação, mas errar o alvo dela não é de graça — é a classe do PR
                        #56. A fonte não cresce, só a área: o cartão fica mais alto e rolar na
                        vertical é nativo e gratuito. Medido em #181. */}
                    <button
                      onClick={() => setEditing(c)}
                      className="inline-flex min-h-[44px] items-center gap-1 px-1 text-xs font-medium text-neutral-500 hover:text-primary-600"
                    >
                      <Pencil size={14} />
                      Editar
                    </button>
                    <button
                      onClick={() => archive(c.id)}
                      className="inline-flex min-h-[44px] items-center gap-1 px-1 text-xs font-medium text-neutral-500 hover:text-danger"
                    >
                      <Archive size={14} />
                      Arquivar
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report && report.buckets.length > 0 && <ComparativeCard report={report} />}

      <CostCenterModal
        open={open || editing !== null}
        editing={editing}
        onClose={() => {
          setOpen(false);
          setEditing(null);
        }}
        onSaved={load}
      />
    </div>
  );
}

/**
 * Comparativo do mês: resultado por centro de custo lado a lado (inclui "Não atribuído").
 *
 * ⚠️ **DOIS desenhos do mesmo dado, e a escolha foi MEDIDA (#157), não preferida.** Abaixo de
 * `sm` saem cartões; de `sm` para cima, a tabela — que é o formato certo no desktop, onde o ponto
 * deste card é justamente comparar sócio com sócio lado a lado.
 *
 * O caminho óbvio seria dar deslizador à tabela, como a DRE (`DrePage.tsx:131`). **Medido em
 * 20/08/2026: não resolve.** Trocando o `overflow-hidden` por `overflow-x-auto` + `min-w-[36rem]`,
 * a régua de `textoForaDaTela` continua acusando os MESMOS 12 cortes, com os MESMOS números
 * (306,5 / 443,3 / 572,3 / 699,5). E não é fresta da régua: ela compara a borda do texto com a do
 * ancestral que RECORTA, e um deslizador recorta. O que o `overflow-x-auto` muda é que o dono
 * PODE alcançar o valor — não que ele o LEIA. Num comparativo o valor é *a* informação, e
 * informação que exige rolagem lateral para existir é informação que o dono não lê.
 *
 * É a mesma conclusão que a `InvestimentosPage` já escreveu com outras palavras ("a lição do #58
 * era role, não corte; a daqui é mais funda: em 360px uma tabela de 3 colunas não cabe, e a saída
 * não é fazer a rolagem funcionar melhor — é não precisar dela"). Aqui são 4 colunas, uma delas um
 * nome livre de até 120 chars.
 */
function ComparativeCard({ report }: { report: CostCenterReport }) {
  return (
    <div data-testid="comparativo-centros" className="overflow-hidden rounded-2xl bg-white shadow-sm">
      <div className="border-b border-neutral-100 px-5 py-3">
        <h2 className="font-semibold text-neutral-800">Resultado por centro de custo (este mês)</h2>
        <p className="text-xs text-neutral-400">
          Mesma fórmula/exclusões da DRE (regime de competência). Compare sócios/áreas lado a lado.
        </p>
      </div>

      {/* Abaixo de `sm`: um cartão por centro. Este `sm:hidden` e o `hidden sm:table` da tabela
          são um PAR — quebrar um só põe os dois desenhos na tela ao mesmo tempo, e a régua acusa
          os 12 cortes de volta. */}
      <ul className="divide-y divide-neutral-50 sm:hidden">
        {report.buckets.map((b) => (
          <Cartao key={b.cost_center_id ?? "__nao_atribuido__"} bucket={b} />
        ))}
      </ul>

      <table className="hidden w-full text-sm sm:table">
        <thead>
          <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
            <th className="px-5 py-2 font-medium">Centro de custo</th>
            <th className="px-5 py-2 font-medium">Receita</th>
            <th className="px-5 py-2 font-medium">Resultado</th>
            <th className="px-5 py-2 font-medium">Lançamentos</th>
          </tr>
        </thead>
        <tbody>
          {report.buckets.map((b) => (
            <Row key={b.cost_center_id ?? "__nao_atribuido__"} bucket={b} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Tom do resultado — uma definição só, para o cartão e a linha não divergirem no 1º ajuste. */
const tomDoResultado = (bucket: CostCenterBucket) =>
  bucket.resultado_cents < 0 ? "text-danger" : "text-emerald-600";

/**
 * O mesmo bucket em 360px. Rótulo à esquerda, valor à direita com `whitespace-nowrap` — o padrão
 * que a `InvestimentosPage` fixou depois do "R$ 3." no lugar de "R$ 3.000,00".
 *
 * `min-w-0` no nome pelo mesmo motivo do cartão da lista: sem ele o item de flex não encolhe
 * abaixo do min-content, e o `break-words` ao lado vira peso morto.
 */
function Cartao({ bucket }: { bucket: CostCenterBucket }) {
  const unassigned = bucket.cost_center_id === null;
  return (
    <li data-testid="linha-centro" className={`px-5 py-3 ${unassigned ? "bg-amber-50" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 break-words text-sm font-medium text-neutral-800">
          {bucket.name}
        </span>
        {bucket.kind && !unassigned && (
          <span className="whitespace-nowrap rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
            {kindLabel(bucket.kind)}
          </span>
        )}
      </div>
      <dl className="mt-2 space-y-1 text-xs">
        <LinhaDoCartao rotulo="Receita">
          <span className="tabular-nums text-neutral-600">{formatBRL(bucket.receita_cents)}</span>
        </LinhaDoCartao>
        <LinhaDoCartao rotulo="Resultado">
          <span className={`font-medium tabular-nums ${tomDoResultado(bucket)}`}>
            {formatBRL(bucket.resultado_cents)}
          </span>
        </LinhaDoCartao>
        <LinhaDoCartao rotulo="Lançamentos">
          <span className="tabular-nums text-neutral-500">{bucket.lancamentos}</span>
        </LinhaDoCartao>
      </dl>
    </li>
  );
}

function LinhaDoCartao({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-neutral-400">{rotulo}</dt>
      <dd className="whitespace-nowrap">{children}</dd>
    </div>
  );
}

function Row({ bucket }: { bucket: CostCenterBucket }) {
  const unassigned = bucket.cost_center_id === null;
  return (
    <tr
      data-testid="linha-centro"
      className={`border-b border-neutral-50 last:border-0 ${unassigned ? "bg-amber-50" : ""}`}
    >
      <td className="px-5 py-2.5 text-neutral-800">
        {bucket.name}
        {bucket.kind && !unassigned && (
          <span className="ml-2 rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
            {kindLabel(bucket.kind)}
          </span>
        )}
      </td>
      <td className="px-5 py-2.5 tabular-nums text-neutral-600">{formatBRL(bucket.receita_cents)}</td>
      <td className={`px-5 py-2.5 font-medium tabular-nums ${tomDoResultado(bucket)}`}>
        {formatBRL(bucket.resultado_cents)}
      </td>
      <td className="px-5 py-2.5 tabular-nums text-neutral-500">{bucket.lancamentos}</td>
    </tr>
  );
}

function CostCenterModal({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: CostCenter | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("socio");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(editing?.name ?? "");
      setKind(editing?.kind ?? "socio");
      setError(null);
    }
  }, [open, editing]);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/cost-centers/${editing.id}`, { name, kind });
      } else {
        await api.post("/cost-centers", { name, kind });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={editing ? "Editar centro de custo" : "Novo centro de custo"} open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome" value={name} onChange={setName} placeholder="Ex.: Sócio João, Unidade Centro" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {COST_CENTER_KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !name.trim()}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : editing ? "Salvar" : "Criar centro de custo"}
        </button>
      </div>
    </Modal>
  );
}
