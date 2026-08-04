import type { Payable } from "@e1p/shared-types";
import { ChevronLeft, FileText, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import {
  CadastroDeContaEmbutido,
  EscolhaDaBaixa,
  type EscolhaDaBaixaState,
  useEscolhaDaBaixa,
} from "./EscolhaDaBaixa";

/** O que a bandeja devolve por comprovante (`GET /payables/receipts`). */
interface ReceiptInfo {
  id: string;
  filename: string;
  size: number;
}

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const kb = (n: number) =>
  n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
const dia = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("pt-BR", { timeZone: "UTC" });

/**
 * Data de HOJE no fuso LOCAL, no formato YYYY-MM-DD. `toISOString()` formataria o instante em
 * UTC — à noite no Brasil (UTC-3) o instante UTC já é o dia seguinte, então o campo de
 * vencimento pré-preenchido viraria "amanhã" silenciosamente. Não "simplificar" isso de volta
 * para `new Date().toISOString().slice(0, 10)`.
 */
function localToday(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Converte "45,00" / "45.00" / "4500" em centavos. Vazio ou inválido → 0. */
function toCents(raw: string): number {
  const clean = raw.replace(/\s/g, "").replace(/\./g, "").replace(",", ".");
  const n = Number.parseFloat(clean);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

function chip(p: Payable): { label: string; cls: string } {
  if (p.status === "paid") return { label: "Pago", cls: "bg-accent-50 text-accent-700" };
  if (p.is_overdue) return { label: "Vencida", cls: "bg-red-50 text-danger" };
  return { label: "A vencer", cls: "bg-amber-50 text-amber-700" };
}

/**
 * Tela de vinculação do comprovante, dimensionada para o polegar: cartões altos, um alvo de
 * toque por conta, e a ação principal fixa no rodapé.
 */
export default function ComprovantePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [candidates, setCandidates] = useState<Payable[]>([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [markPaid, setMarkPaid] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<ReceiptInfo | null>(null);

  /**
   * A escolha da baixa (Story 8.13) — **hoje** como data padrão, e não o `due_date` da conta
   * escolhida como nas outras duas telas.
   *
   * Não é inconsistência: o comprovante chega pelo share sheet **no instante do pagamento**, então
   * a data de caixa honesta desta porta é o dia de hoje — e era exatamente isso que o backend já
   * gravava antes desta story (IV1: a bandeja não muda de comportamento). O `due_date`, aqui,
   * também seria uma escolha pior: a lista de candidatas é ordenada por vencimento e quase sempre
   * traz contas a vencer, cujo `due_date` futuro bateria no teto de hoje com um 422 numa porta que
   * hoje funciona.
   *
   * O que mudou é que "hoje" deixou de ser decisão invisível do backend: virou um campo **visível
   * e editável**, dentro da barra fixa, ao lado do botão. O usuário confirma; não constrói.
   */
  const escolha = useEscolhaDaBaixa(localToday());

  // Identifica QUAL comprovante está na tela. Não existe `GET /payables/receipts/{id}`, mas a
  // bandeja é curta por construção (teto de 30), então filtrar a lista basta e evita rota nova.
  useEffect(() => {
    let cancelled = false;
    api
      .get<ReceiptInfo[]>("/payables/receipts")
      .then(({ data }) => {
        if (cancelled) return;
        setReceipt(data.find((r) => r.id === id) ?? null);
      })
      .catch(() => {
        /* o nome do arquivo é contexto, não função — sem ele a tela opera igual */
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const load = useCallback(async () => {
    const { data } = await api.get<Payable[]>(
      `/payables/receipts/candidates?q=${encodeURIComponent(q)}`,
    );
    return data;
  }, [q]);

  // A busca dispara uma nova requisição a cada tecla e o componente pode ser desmontado
  // (navegação para /pagar) enquanto uma chamada anterior ainda está em voo. O `cancelled`
  // por execução garante duas coisas: (1) uma resposta que chega depois que o efeito já foi
  // limpo nunca chama setState; (2) se o usuário digitar de novo antes da resposta anterior
  // voltar, e essa resposta antiga chegar fora de ordem, ela é descartada — só a busca mais
  // recente (cujo efeito ainda está "vivo") pode atualizar a lista.
  useEffect(() => {
    let cancelled = false;
    load()
      .then((data) => {
        if (cancelled) return;
        setCandidates(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(apiErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const chosen = useMemo(
    () => candidates.find((c) => c.id === selected) ?? null,
    [candidates, selected],
  );

  // Vincular a uma conta existente e criar uma conta nova são caminhos de mutação concorrentes
  // para o mesmo comprovante e precisam ser mutuamente exclusivos NAS DUAS direções — não só
  // "abrir a conta nova esconde o Anexar", mas também "selecionar uma candidata fecha a conta
  // nova". Sem isso, escolher uma candidata enquanto o formulário de conta nova está aberto
  // faz os dois guards (`!chosen` e `!showNew`) ficarem falsos ao mesmo tempo — nenhum dos dois
  // caminhos de envio renderiza e o usuário fica sem nenhuma forma de arquivar o comprovante.
  //
  // Tocar de novo na candidata JÁ selecionada desmarca (toggle) em vez de travar a seleção —
  // sem isso, a única forma de sair de "candidata escolhida" era filtrar a lista até ela sumir,
  // e "Criar conta nova" ficava inalcançável enquanto qualquer candidata estivesse marcada.
  function selectCandidate(candidateId: string) {
    setSelected((prev) => (prev === candidateId ? "" : candidateId));
    setShowNew(false);
  }

  function openNewBillForm() {
    setSelected("");
    setMarkPaid(true); // reinicia o padrão para a próxima seleção, já que esta troca de fluxo o abandona
    setShowNew(true);
  }

  // Vai haver baixa nesta submissão? Conta já paga não mostra o checkbox (não faz sentido "dar
  // baixa" de novo) e, nesse caso, **a conta bancária também não é exigida** — nem pela tela nem
  // pelo backend, cujo campo é obrigatório apenas quando `mark_paid=True`.
  const daBaixa = chosen !== null && chosen.status === "open" && markPaid;

  async function link() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/payables/receipts/${id}/link`, {
        bill_id: chosen.id,
        mark_paid: daBaixa,
        // Story 8.13: os dois campos só viajam quando há baixa. Mandá-los com `mark_paid=false`
        // seria afirmar de qual conta saiu um dinheiro que o usuário não disse ter saído.
        ...(daBaixa ? escolha.corpo() : {}),
      });
      navigate("/pagar", { replace: true });
    } catch (err) {
      // 409 acionável → abre o cadastro de conta embutido, com a mensagem do backend. A tela NÃO é
      // desmontada: ao salvar a conta, a baixa é retomada com a conta nova já selecionada e a
      // candidata escolhida continua na tela — o usuário não perde de vista o que estava pagando.
      setError(escolha.tratarErro(err) ?? apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    setBusy(true);
    try {
      await api.delete(`/payables/receipts/${id}`);
      navigate("/pagar", { replace: true });
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    // `pb-52` (208px) e não `pb-28`: a barra fixa cresceu com o seletor de conta e o dia, e o
    // último cartão da lista não pode ficar EMBAIXO dela. A aritmética (altura da barra × padding)
    // está em `baixa.ts` e é conferida por teste — ver `ALTURA_DA_BARRA`.
    <div className="mx-auto max-w-lg space-y-4 pb-52">
      <header className="space-y-3 rounded-2xl bg-white p-4 shadow-sm">
        {/* Esta tela roda FORA do shell (sem sidebar/topbar), então a saída mora aqui. "Cancelar"
            só sai — o comprovante continua na bandeja e o aviso em Contas a Pagar aponta pra ele.
            Quem quer se livrar do arquivo usa "Descartar", que é destrutivo e fica separado. */}
        <div className="flex items-center justify-between gap-3">
          <button
            onClick={() => navigate("/pagar")}
            className="flex shrink-0 items-center gap-1 text-sm font-medium text-neutral-500 hover:text-neutral-800"
          >
            <ChevronLeft size={16} /> Cancelar
          </button>
          <button
            onClick={discard}
            disabled={busy}
            className="flex shrink-0 items-center gap-1 text-xs text-neutral-400 hover:text-danger disabled:opacity-50"
          >
            <Trash2 size={14} /> Descartar
          </button>
        </div>
        <div className="flex items-center gap-3 border-t border-neutral-100 pt-3">
          <FileText size={22} className="shrink-0 text-neutral-400" />
          <div className="min-w-0 flex-1">
            {/* Mostrar QUAL arquivo está sendo arquivado importa quando a bandeja tem vários. */}
            <p className="truncate text-sm font-semibold text-neutral-700">
              {receipt?.filename ?? "Comprovante recebido"}
            </p>
            <p className="text-xs text-neutral-500">
              {receipt ? `${kb(receipt.size)} — escolha a conta` : "Escolha a conta a que ele pertence"}
            </p>
          </div>
        </div>
      </header>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Buscar conta por nome ou fornecedor"
        className="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-primary-400"
      />

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-danger">{error}</p>}

      <ul className="space-y-2">
        {candidates.map((c) => {
          const tag = chip(c);
          const active = c.id === selected;
          return (
            <li key={c.id}>
              <button
                onClick={() => selectCandidate(c.id)}
                className={`w-full rounded-2xl border p-4 text-left transition ${
                  active ? "border-primary-400 bg-primary-50" : "border-neutral-200 bg-white"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-neutral-800">
                      {c.description || c.supplier || "Conta"}
                    </p>
                    {c.supplier && c.description && (
                      <p className="truncate text-xs text-neutral-500">{c.supplier}</p>
                    )}
                    <p className="mt-1 text-xs text-neutral-500">Vence {dia(c.due_date)}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-bold text-neutral-800">{brl(c.amount_cents)}</p>
                    <span className={`rounded-pill px-2 py-0.5 text-[10px] font-semibold ${tag.cls}`}>
                      {tag.label}
                    </span>
                  </div>
                </div>
              </button>
            </li>
          );
        })}
        {candidates.length === 0 && (
          <li className="rounded-2xl bg-white p-6 text-center text-sm text-neutral-400">
            Nenhuma conta encontrada.
          </li>
        )}
      </ul>

      {/* Vincular a uma conta existente e criar uma conta nova são caminhos de mutação
          concorrentes para o mesmo comprovante — mantidos mutuamente exclusivos NAS DUAS
          direções por `selectCandidate`/`openNewBillForm` (acima), que resetam o outro fluxo
          ao entrar num deles. Sem esse reset cruzado, os guards abaixo (`!chosen` / `!showNew`)
          podem ficar false ao mesmo tempo e nenhum caminho de envio renderiza. */}
      {!chosen && (
        showNew ? (
          <NewBillForm receiptId={id} onError={setError} escolha={escolha} />
        ) : (
          <button
            onClick={openNewBillForm}
            className="w-full text-center text-sm font-semibold text-primary-600"
          >
            Criar conta nova com este comprovante
          </button>
        )
      )}

      {!showNew && (
        <div className="fixed inset-x-0 bottom-0 space-y-3 border-t border-neutral-100 bg-white p-4">
          {/* Achado de campo: com a conta escolhida e o checkbox num bloco separado, mais acima
              na página, quem tocava numa conta e ia direto no Anexar (sem rolar) NUNCA via o
              checkbox — a baixa acontecia com o padrão (marcado) sem confirmação visível. Fica
              aqui dentro, colado no botão que comete a ação: fisicamente não dá pra tocar em
              Anexar sem ver o que está sendo confirmado.

              ⚠️ **Story 8.13 (AC4): o seletor de conta e o dia entram AQUI DENTRO, pelo mesmo
              motivo.** É a terceira coisa que o botão comete — de qual conta o dinheiro saiu — e
              seria a terceira a ficar fora da área visível se morasse noutro bloco. Não mova para
              um modal, um "expandir", ou qualquer lugar que exija rolagem. */}
          {chosen && (
            <div className="mx-auto flex max-w-lg items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-neutral-700">
                  {chosen.description || chosen.supplier || "Conta"}
                </p>
                <p className="text-xs text-neutral-500">{brl(chosen.amount_cents)}</p>
              </div>
              {chosen.status === "open" && (
                <label className="flex shrink-0 items-center gap-2 text-xs font-medium text-neutral-600">
                  <input
                    type="checkbox"
                    checked={markPaid}
                    onChange={(e) => setMarkPaid(e.target.checked)}
                    className="h-4 w-4"
                  />
                  Marcar como paga
                </label>
              )}
            </div>
          )}
          {daBaixa && (
            <div className="mx-auto max-w-lg">
              <EscolhaDaBaixa estado={escolha} compact />
            </div>
          )}
          <button
            onClick={link}
            // Sem conta escolhida (tenant sem primária, estado válido) a ação fica DESABILITADA —
            // silêncio, nunca um palpite sobre para onde vai o dinheiro do dono (AC5).
            disabled={!chosen || busy || (daBaixa && !escolha.pronto)}
            className="mx-auto block w-full max-w-lg rounded-pill bg-accent-400 py-3 font-semibold text-white hover:bg-accent-500 disabled:opacity-50"
          >
            {busy
              ? "Anexando..."
              : daBaixa
                ? escolha.rotulo("Anexar e dar baixa")
                : "Anexar"}
          </button>
        </div>
      )}

      {/* O cadastro embutido do 409 acionável: abre POR CIMA desta tela, que continua montada. */}
      <CadastroDeContaEmbutido estado={escolha} />
    </div>
  );
}

/**
 * Formulário curto: o mínimo para registrar agora e refinar depois no computador.
 *
 * ⚠️ Ele **também** dá baixa (`mark_paid: true`), então **também** precisa da conta bancária desde
 * a Story 8.12 — sem ela o backend responde 422. A escolha vem do MESMO estado da tela (a barra
 * fixa some enquanto este formulário está aberto, e os dois caminhos são mutuamente exclusivos), e
 * fica dentro do MESMO cartão do botão "Criar e anexar", pela regra do AC4.
 */
function NewBillForm({
  receiptId,
  onError,
  escolha,
}: {
  receiptId: string;
  onError: (m: string | null) => void;
  escolha: EscolhaDaBaixaState;
}) {
  const navigate = useNavigate();
  const [description, setDescription] = useState("");
  const [supplier, setSupplier] = useState("");
  const [category, setCategory] = useState("Geral");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState(localToday);
  const [busy, setBusy] = useState(false);

  async function submit() {
    const cents = toCents(amount);
    if (cents <= 0) {
      onError("Informe um valor maior que zero.");
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await api.post(`/payables/receipts/${receiptId}/new-bill`, {
        description, supplier, category, amount_cents: cents,
        due_date: dueDate, mark_paid: true,
        ...escolha.corpo(),
      });
      navigate("/pagar", { replace: true });
    } catch (err) {
      onError(escolha.tratarErro(err) ?? apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-primary-400";

  return (
    <div className="space-y-2 rounded-2xl bg-white p-4 shadow-sm">
      <p className="text-sm font-semibold text-neutral-700">Conta nova</p>
      <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Descrição" className={input} />
      <input value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Fornecedor" className={input} />
      <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Categoria" className={input} />
      <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Valor (ex.: 45,00)" inputMode="decimal" className={input} />
      <input
        type="date"
        aria-label="Data de vencimento"
        value={dueDate}
        onChange={(e) => setDueDate(e.target.value)}
        className={input}
      />
      <EscolhaDaBaixa estado={escolha} />
      <button
        onClick={submit}
        disabled={busy || !escolha.pronto}
        className="w-full rounded-pill bg-primary-500 py-2.5 font-semibold text-white hover:bg-primary-600 disabled:opacity-50"
      >
        {busy ? "Criando..." : escolha.rotulo("Criar e anexar")}
      </button>
    </div>
  );
}
