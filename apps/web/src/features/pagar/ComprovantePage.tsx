import type { Payable } from "@e1p/shared-types";
import { FileText, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
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
  function selectCandidate(candidateId: string) {
    setSelected(candidateId);
    setShowNew(false);
  }

  function openNewBillForm() {
    setSelected("");
    setMarkPaid(true); // reinicia o padrão para a próxima seleção, já que esta troca de fluxo o abandona
    setShowNew(true);
  }

  async function link() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/payables/receipts/${id}/link`, {
        bill_id: chosen.id,
        // conta já paga não mostra o checkbox — não faz sentido "dar baixa" de novo
        mark_paid: chosen.status === "open" ? markPaid : false,
      });
      navigate("/pagar", { replace: true });
    } catch (err) {
      setError(apiErrorMessage(err));
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
    <div className="mx-auto max-w-lg space-y-4 pb-28">
      <header className="flex items-center gap-3 rounded-2xl bg-white p-4 shadow-sm">
        <FileText size={22} className="shrink-0 text-neutral-400" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-neutral-700">Comprovante recebido</p>
          <p className="text-xs text-neutral-500">Escolha a conta a que ele pertence</p>
        </div>
        <button
          onClick={discard}
          disabled={busy}
          className="flex shrink-0 items-center gap-1 text-xs text-neutral-400 hover:text-danger"
        >
          <Trash2 size={14} /> Descartar
        </button>
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

      {chosen?.status === "open" && (
        <label className="flex items-center gap-2 rounded-2xl bg-white p-4 text-sm text-neutral-700 shadow-sm">
          <input
            type="checkbox"
            checked={markPaid}
            onChange={(e) => setMarkPaid(e.target.checked)}
            className="h-4 w-4"
          />
          Marcar como paga
        </label>
      )}

      {/* Vincular a uma conta existente e criar uma conta nova são caminhos de mutação
          concorrentes para o mesmo comprovante — mantidos mutuamente exclusivos NAS DUAS
          direções por `selectCandidate`/`openNewBillForm` (acima), que resetam o outro fluxo
          ao entrar num deles. Sem esse reset cruzado, os guards abaixo (`!chosen` / `!showNew`)
          podem ficar false ao mesmo tempo e nenhum caminho de envio renderiza. */}
      {!chosen && (
        showNew ? (
          <NewBillForm receiptId={id} onError={setError} />
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
        <div className="fixed inset-x-0 bottom-0 border-t border-neutral-100 bg-white p-4">
          <button
            onClick={link}
            disabled={!chosen || busy}
            className="mx-auto block w-full max-w-lg rounded-pill bg-accent-400 py-3 font-semibold text-white hover:bg-accent-500 disabled:opacity-50"
          >
            {busy ? "Anexando..." : "Anexar"}
          </button>
        </div>
      )}
    </div>
  );
}

/** Formulário curto: o mínimo para registrar agora e refinar depois no computador. */
function NewBillForm({
  receiptId,
  onError,
}: {
  receiptId: string;
  onError: (m: string | null) => void;
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
      });
      navigate("/pagar", { replace: true });
    } catch (err) {
      onError(apiErrorMessage(err));
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
      <button
        onClick={submit}
        disabled={busy}
        className="w-full rounded-pill bg-primary-500 py-2.5 font-semibold text-white hover:bg-primary-600 disabled:opacity-50"
      >
        {busy ? "Criando..." : "Criar e anexar"}
      </button>
    </div>
  );
}
