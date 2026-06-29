import type { Account, PlatformEarningsSummary, SplitRates } from "@e1p/shared-types";
import { Power, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const brl = (cents: number) =>
  (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export default function AdminDashboard() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<Account[]>("/admin/accounts");
      setAccounts(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Nova conta", useCallback(() => setOpen(true), []));

  async function toggleActive(a: Account) {
    await api.patch(`/admin/accounts/${a.owner.id}`, { is_active: !a.owner.is_active });
    load();
  }

  async function remove(a: Account) {
    if (!confirm(`Excluir a conta "${a.tenant.legal_name}" e todos os seus dados? Isso é irreversível.`))
      return;
    await api.delete(`/admin/accounts/${a.tenant.id}`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Administração</p>
        <h1 className="text-2xl font-bold text-neutral-800">Plataforma</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SplitRatesCard />
        <PlatformEarningsCard />
      </div>

      <h2 className="text-lg font-bold text-neutral-800">Contas</h2>
      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {loading ? (
          <p className="p-8 text-center text-sm text-neutral-400">Carregando...</p>
        ) : accounts.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhuma conta. Clique em "Nova" para criar a primeira.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-5 py-3 font-medium">Empresa</th>
                <th className="px-5 py-3 font-medium">Subdomínio</th>
                <th className="px-5 py-3 font-medium">Responsável</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium text-right">Ações</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.tenant.id} className="border-b border-neutral-50 last:border-0">
                  <td className="px-5 py-3 font-medium text-neutral-800">{a.tenant.legal_name}</td>
                  <td className="px-5 py-3 text-neutral-500">{a.tenant.slug}.e1p.com</td>
                  <td className="px-5 py-3 text-neutral-600">
                    {a.owner.name}
                    <span className="block text-xs text-neutral-400">{a.owner.email}</span>
                  </td>
                  <td className="px-5 py-3">
                    <span
                      className={`rounded-pill px-2 py-0.5 text-xs ${
                        a.owner.is_active
                          ? "bg-accent-50 text-accent-700"
                          : "bg-neutral-100 text-neutral-500"
                      }`}
                    >
                      {a.owner.is_active ? "Ativa" : "Suspensa"}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => toggleActive(a)}
                        title={a.owner.is_active ? "Suspender" : "Reativar"}
                        className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100"
                      >
                        <Power size={16} />
                      </button>
                      <button
                        onClick={() => remove(a)}
                        title="Excluir"
                        className="rounded-lg p-1.5 text-danger hover:bg-red-50"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewAccountModal open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
  );
}

function SplitRatesCard() {
  const [rates, setRates] = useState<SplitRates>({
    product_pct: 40,
    service_pct: 30,
    recurring_pct: 20,
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<SplitRates>("/wallet/split-rates").then(({ data }) => setRates(data));
  }, []);

  function set(key: keyof SplitRates, v: string) {
    setSaved(false);
    setRates((r) => ({ ...r, [key]: Number(v) }));
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const { data } = await api.put<SplitRates>("/wallet/split-rates", rates);
      setRates(data);
      setSaved(true);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const row = (label: string, key: keyof SplitRates) => (
    <div className="flex items-center justify-between">
      <span className="text-sm text-neutral-600">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          min={0}
          max={95}
          value={rates[key]}
          onChange={(e) => set(key, e.target.value)}
          className="w-16 rounded-lg border border-neutral-200 px-2 py-1 text-right text-sm outline-none focus:border-primary-400"
        />
        <span className="text-sm text-neutral-400">%</span>
      </div>
    </div>
  );

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h3 className="mb-1 font-semibold text-neutral-800">Taxas de split</h3>
      <p className="mb-4 text-xs text-neutral-400">
        Percentual retido pela plataforma por tipo de venda.
      </p>
      <div className="space-y-3">
        {row("Produtos", "product_pct")}
        {row("Serviços", "service_pct")}
        {row("Recorrentes", "recurring_pct")}
      </div>
      {error && <p className="mt-3 rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
      <button
        onClick={save}
        disabled={saving}
        className="mt-4 w-full rounded-pill bg-accent-400 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
      >
        {saving ? "Salvando..." : saved ? "Salvo ✓" : "Salvar taxas"}
      </button>
    </div>
  );
}

function PlatformEarningsCard() {
  const [e, setE] = useState<PlatformEarningsSummary | null>(null);
  useEffect(() => {
    api.get<PlatformEarningsSummary>("/wallet/platform-earnings").then(({ data }) => setE(data));
  }, []);
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h3 className="mb-4 font-semibold text-neutral-800">Ganhos da plataforma</h3>
      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-neutral-500">Volume transacionado (GMV)</span>
          <span className="font-medium tabular-nums">{e ? brl(e.gmv_cents) : "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">Taxas retidas</span>
          <span className="font-bold tabular-nums text-accent-700">
            {e ? brl(e.fees_cents) : "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">Transações</span>
          <span className="tabular-nums">{e?.transaction_count ?? "—"}</span>
        </div>
      </div>
    </div>
  );
}

function NewAccountModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [legalName, setLegalName] = useState("");
  const [slug, setSlug] = useState("");
  const [document, setDocument] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.post("/admin/accounts", {
        legal_name: legalName,
        slug,
        document,
        name,
        email,
        password,
      });
      onCreated();
      onClose();
      setLegalName("");
      setSlug("");
      setDocument("");
      setName("");
      setEmail("");
      setPassword("");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova conta" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome da empresa" value={legalName} onChange={setLegalName} />
        <div className="flex gap-2">
          <Field label="Subdomínio" value={slug} onChange={setSlug} placeholder="empresa" />
          <Field label="CPF/CNPJ" value={document} onChange={setDocument} />
        </div>
        <Field label="Responsável" value={name} onChange={setName} />
        <Field label="E-mail" type="email" value={email} onChange={setEmail} />
        <Field label="Senha inicial" type="password" value={password} onChange={setPassword} />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !legalName || !slug || !email || !password}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Criando..." : "Criar conta"}
        </button>
      </div>
    </Modal>
  );
}
