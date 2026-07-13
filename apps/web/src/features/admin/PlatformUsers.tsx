import type { AccountInvite, StaffInvite, TenantUsers, User } from "@e1p/shared-types";
import {
  Building2, ChevronDown, GraduationCap, Power, Search, Trash2, UserPlus, Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { pluralize } from "../../lib/pluralize";
import { usePrimaryAction } from "../../store/pageActions";

// Domínio raiz para exibir o endereço de subdomínio do tenant (Story 4.4) — embutido no
// bundle em build-time via VITE_ROOT_DOMAIN (ver apps/web/Dockerfile), reflete o mesmo
// ROOT_DOMAIN configurado no Traefik/backend. Fallback "e1p.com" só pra dev local sem o build arg.
const ROOT_DOMAIN = import.meta.env.VITE_ROOT_DOMAIN ?? "e1p.com";

// Módulos que um funcionário pode receber (vazio = acesso a tudo).
const MODULES: { key: string; label: string }[] = [
  { key: "crm", label: "CRM" },
  { key: "agenda", label: "Agenda" },
  { key: "receivables", label: "Cobranças" },
  { key: "payables", label: "Contas a Pagar" },
  { key: "chart_of_accounts", label: "Plano de contas" },
  { key: "wallet", label: "Financeiro" },
  { key: "quotes", label: "Orçamentos" },
  { key: "contracts", label: "Contratos" },
  { key: "products", label: "Produtos" },
  { key: "stock", label: "Estoque" },
  { key: "marketing", label: "Marketing" },
  { key: "funnels", label: "Funis" },
  { key: "juridico", label: "Jurídico" },
];

export default function PlatformUsers() {
  const [nodes, setNodes] = useState<TenantUsers[]>([]);
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [newAccount, setNewAccount] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get<TenantUsers[]>("/admin/users");
    setNodes(data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Nova conta", useCallback(() => setNewAccount(true), []));

  const totals = useMemo(
    () => ({
      offices: nodes.length,
      staff: nodes.reduce((s, n) => s + n.staff_count, 0),
      customers: nodes.reduce((s, n) => s + n.customer_count, 0),
    }),
    [nodes],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return nodes;
    return nodes.filter(
      (n) =>
        n.tenant.legal_name.toLowerCase().includes(q) ||
        n.tenant.slug.toLowerCase().includes(q) ||
        n.admin?.name.toLowerCase().includes(q) ||
        n.admin?.email.toLowerCase().includes(q),
    );
  }, [nodes, query]);

  return (
    <div className="space-y-3">
      {/* Resumo enxuto */}
      <div className="flex flex-wrap items-center gap-2">
        <Chip icon={<Building2 size={13} />} value={totals.offices} label={pluralize(totals.offices, "escritório", "escritórios")} />
        <Chip icon={<Users size={13} />} value={totals.staff} label={pluralize(totals.staff, "funcionário", "funcionários")} />
        <Chip icon={<GraduationCap size={13} />} value={totals.customers} label={pluralize(totals.customers, "cliente", "clientes")} />
      </div>

      {/* Busca */}
      <div className="relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar escritório, subdomínio ou responsável…"
          className="w-full rounded-xl border border-neutral-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-primary-400"
        />
      </div>

      {/* Cartões por escritório — recolhidos por padrão */}
      <div className="space-y-2">
        {filtered.length === 0 ? (
          <p className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">
            {nodes.length === 0 ? "Nenhuma conta ainda." : "Nenhum resultado para a busca."}
          </p>
        ) : (
          filtered.map((n) => (
            <OfficeCard
              key={n.tenant.id}
              node={n}
              open={openId === n.tenant.id}
              onToggle={() => setOpenId(openId === n.tenant.id ? null : n.tenant.id)}
              onChanged={load}
            />
          ))
        )}
      </div>

      <NewAccountModal
        open={newAccount}
        onClose={() => setNewAccount(false)}
        onCreated={() => { setNewAccount(false); load(); }}
      />
    </div>
  );
}

function OfficeCard({
  node,
  open,
  onToggle,
  onChanged,
}: {
  node: TenantUsers;
  open: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const [addStaff, setAddStaff] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = node.admin?.is_active ?? true;

  async function toggleUser(u: User) {
    setError(null);
    try {
      await api.patch(`/admin/users/${u.id}`, { is_active: !u.is_active });
      onChanged();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }
  async function removeUser(u: User) {
    if (!confirm(`Excluir o usuário "${u.name}"?`)) return;
    setError(null);
    try {
      await api.delete(`/admin/users/${u.id}`);
      onChanged();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }
  async function deleteAccount() {
    if (!confirm(`Excluir a conta "${node.tenant.legal_name}" e TODOS os seus dados? Irreversível.`))
      return;
    await api.delete(`/admin/accounts/${node.tenant.id}`);
    onChanged();
  }

  return (
    <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
      <button onClick={onToggle} className="flex w-full items-center gap-3 p-4 text-left hover:bg-neutral-50">
        <span className={`h-2 w-2 shrink-0 rounded-full ${active ? "bg-accent-500" : "bg-neutral-300"}`} />
        <Building2 size={18} className="shrink-0 text-primary-600" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-neutral-800">{node.tenant.legal_name}</p>
          <p className="truncate text-xs text-neutral-400">
            {node.tenant.slug}.{ROOT_DOMAIN} · {node.admin?.name ?? "sem dono"}
          </p>
        </div>
        <Chip icon={<Users size={12} />} value={node.staff_count} compact />
        <Chip icon={<GraduationCap size={12} />} value={node.customer_count} compact />
        <ChevronDown size={18} className={`shrink-0 text-neutral-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="space-y-4 border-t border-neutral-100 p-4">
          {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
          {node.admin && (
            <Group title="Admin (dono)">
              <UserRow user={node.admin} onToggle={toggleUser} />
            </Group>
          )}

          <Group
            title={`Funcionários (${node.staff_count})`}
            action={
              <button
                onClick={() => setAddStaff(true)}
                className="flex items-center gap-1 rounded-pill bg-primary-50 px-2.5 py-1 text-xs font-semibold text-primary-600 hover:bg-primary-100"
              >
                <UserPlus size={13} /> Adicionar
              </button>
            }
          >
            {node.staff.length === 0 ? (
              <Empty text="Nenhum funcionário." />
            ) : (
              node.staff.map((u) => <UserRow key={u.id} user={u} onToggle={toggleUser} onDelete={removeUser} />)
            )}
          </Group>

          {node.customer_count > 0 && (
            <p className="text-xs text-neutral-400">
              {node.customer_count} cliente{node.customer_count > 1 ? "s" : ""} — veja na aba{" "}
              <strong>Clientes</strong>.
            </p>
          )}

          <div className="flex justify-end border-t border-neutral-100 pt-3">
            <button
              onClick={deleteAccount}
              className="flex items-center gap-1.5 rounded-pill px-3 py-1.5 text-xs font-semibold text-danger hover:bg-red-50"
            >
              <Trash2 size={13} /> Excluir conta inteira
            </button>
          </div>
        </div>
      )}

      {addStaff && (
        <AddStaffModal
          tenantId={node.tenant.id}
          onClose={() => setAddStaff(false)}
          onCreated={() => { setAddStaff(false); onChanged(); }}
        />
      )}
    </div>
  );
}

function Chip({
  icon, value, label, compact,
}: { icon: React.ReactNode; value: number | string; label?: string; compact?: boolean }) {
  return (
    <span className={`flex shrink-0 items-center gap-1 rounded-pill bg-neutral-100 text-neutral-500 ${compact ? "px-2 py-0.5 text-xs" : "px-3 py-1 text-sm"}`}>
      {icon} <span className="font-semibold text-neutral-700">{value}</span>
      {label && <span className="text-neutral-400">{label}</span>}
    </span>
  );
}

function Group({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{title}</p>
        {action}
      </div>
      <div className="divide-y divide-neutral-50">{children}</div>
    </div>
  );
}

function UserRow({ user, onToggle, onDelete }: { user: User; onToggle: (u: User) => void; onDelete?: (u: User) => void }) {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-neutral-700">
          {user.name}
          {!user.is_active && <span className="ml-2 text-xs text-neutral-400">(suspenso)</span>}
        </p>
        <p className="truncate text-xs text-neutral-400">{user.email}</p>
      </div>
      <div className="flex shrink-0 gap-1">
        <button
          onClick={() => onToggle(user)}
          title={user.is_active ? "Suspender" : "Reativar"}
          className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100"
        >
          <Power size={15} />
        </button>
        {onDelete && (
          <button onClick={() => onDelete(user)} title="Excluir" className="rounded-lg p-1.5 text-danger hover:bg-red-50">
            <Trash2 size={15} />
          </button>
        )}
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="py-2 text-xs text-neutral-400">{text}</p>;
}

function AddStaffModal({ tenantId, onClose, onCreated }: { tenantId: string; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [document, setDocument] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [delivery, setDelivery] = useState<"email" | "whatsapp">("email");
  const [modules, setModules] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [invite, setInvite] = useState<StaffInvite | null>(null);

  function toggle(key: string) {
    setModules((m) => (m.includes(key) ? m.filter((k) => k !== key) : [...m, key]));
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const { data } = await api.post<StaffInvite>(`/admin/accounts/${tenantId}/users`, {
        name, email, document, address, phone, delivery, allowed_modules: modules,
      });
      setInvite(data); // mostra a senha temporária + status do envio
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  // Tela de confirmação: usuário criado, senha temporária enviada.
  if (invite) {
    const sent = invite.delivery_status === "sent";
    const channel = invite.delivery === "whatsapp" ? "WhatsApp" : "e-mail";
    return (
      <Modal title="Usuário cadastrado" open onClose={() => { onClose(); onCreated(); }}>
        <div className="space-y-3 text-sm">
          <p className="text-neutral-600">
            <strong>{invite.user.name}</strong> foi cadastrado. {sent
              ? `A senha foi enviada por ${channel}.`
              : `O envio por ${channel} está em modo de teste (não saiu de verdade) — repasse a senha abaixo.`}
          </p>
          <div className="rounded-xl bg-neutral-50 p-3">
            <p className="text-xs text-neutral-400">Senha temporária</p>
            <p className="select-all font-mono text-base font-semibold text-neutral-800">{invite.temp_password}</p>
          </div>
          <p className="text-xs text-neutral-500">
            No primeiro acesso o usuário entra com essa senha e define uma nova.
          </p>
          <button
            onClick={() => { onClose(); onCreated(); }}
            className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500"
          >
            Concluir
          </button>
        </div>
      </Modal>
    );
  }

  const valid = name && email && document.replace(/\D/g, "").length >= 11 && address && phone.replace(/\D/g, "").length >= 8;

  return (
    <Modal title="Cadastrar usuário" open onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome completo" value={name} onChange={setName} />
        <div className="flex gap-2">
          <Field label="CPF" value={document} onChange={setDocument} placeholder="000.000.000-00" />
          <Field label="WhatsApp" value={phone} onChange={setPhone} placeholder="(27) 99999-0000" />
        </div>
        <Field label="E-mail" type="email" value={email} onChange={setEmail} />
        <Field label="Endereço" value={address} onChange={setAddress} placeholder="Rua, nº, bairro, cidade" />

        <div>
          <p className="mb-1.5 text-sm font-medium text-neutral-600">Enviar senha por</p>
          <div className="flex gap-2">
            {(["email", "whatsapp"] as const).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDelivery(d)}
                className={`flex-1 rounded-lg border py-2 text-sm font-medium ${
                  delivery === d ? "border-primary-400 bg-primary-50 text-primary-700" : "border-neutral-200 text-neutral-600"
                }`}
              >
                {d === "email" ? "E-mail" : "WhatsApp"}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-1.5 text-sm font-medium text-neutral-600">Acesso a módulos</p>
          <p className="mb-2 text-xs text-neutral-400">Nenhum marcado = acesso a tudo (você ajusta depois).</p>
          <div className="flex flex-wrap gap-1.5">
            {MODULES.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => toggle(m.key)}
                className={`rounded-pill px-2.5 py-1 text-xs font-medium ${
                  modules.includes(m.key) ? "bg-primary-500 text-white" : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !valid}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Cadastrando..." : "Cadastrar e enviar senha"}
        </button>
      </div>
    </Modal>
  );
}

function NewAccountModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [legalName, setLegalName] = useState("");
  const [slug, setSlug] = useState("");
  const [document, setDocument] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [delivery, setDelivery] = useState<"email" | "whatsapp">("email");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [invite, setInvite] = useState<AccountInvite | null>(null);

  function reset() {
    setLegalName(""); setSlug(""); setDocument(""); setName("");
    setEmail(""); setAddress(""); setPhone(""); setInvite(null);
  }
  function finish() {
    reset();
    onClose();
    onCreated();
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const { data } = await api.post<AccountInvite>("/admin/accounts", {
        legal_name: legalName, slug, document, name, email, address, phone, delivery,
      });
      setInvite(data);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  if (invite) {
    const sent = invite.delivery_status === "sent";
    const channel = invite.delivery === "whatsapp" ? "WhatsApp" : "e-mail";
    return (
      <Modal title="Conta criada" open onClose={finish}>
        <div className="space-y-3 text-sm">
          <p className="text-neutral-600">
            <strong>{invite.owner.name}</strong> ({invite.tenant.legal_name}) foi cadastrado.{" "}
            {sent ? `A senha foi enviada por ${channel}.` : `Envio por ${channel} em modo de teste — repasse a senha abaixo.`}
          </p>
          <div className="rounded-xl bg-neutral-50 p-3">
            <p className="text-xs text-neutral-400">Senha temporária</p>
            <p className="select-all font-mono text-base font-semibold text-neutral-800">{invite.temp_password}</p>
          </div>
          <p className="text-xs text-neutral-500">No primeiro acesso o dono define uma nova senha.</p>
          <button onClick={finish} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500">
            Concluir
          </button>
        </div>
      </Modal>
    );
  }

  const valid = legalName && slug && document.replace(/\D/g, "").length >= 11 && email && address && phone.replace(/\D/g, "").length >= 8;

  return (
    <Modal title="Nova conta (escritório + dono)" open onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome da empresa" value={legalName} onChange={setLegalName} />
        <Field label="Subdomínio" value={slug} onChange={setSlug} placeholder="empresa" />
        <hr className="border-neutral-100" />
        <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">Dados do responsável</p>
        <Field label="Nome completo" value={name} onChange={setName} />
        <div className="flex gap-2">
          <Field label="CPF/CNPJ" value={document} onChange={setDocument} placeholder="000.000.000-00" />
          <Field label="WhatsApp" value={phone} onChange={setPhone} placeholder="(27) 99999-0000" />
        </div>
        <Field label="E-mail" type="email" value={email} onChange={setEmail} />
        <Field label="Endereço" value={address} onChange={setAddress} placeholder="Rua, nº, bairro, cidade" />
        <div>
          <p className="mb-1.5 text-sm font-medium text-neutral-600">Enviar senha por</p>
          <div className="flex gap-2">
            {(["email", "whatsapp"] as const).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDelivery(d)}
                className={`flex-1 rounded-lg border py-2 text-sm font-medium ${
                  delivery === d ? "border-primary-400 bg-primary-50 text-primary-700" : "border-neutral-200 text-neutral-600"
                }`}
              >
                {d === "email" ? "E-mail" : "WhatsApp"}
              </button>
            ))}
          </div>
        </div>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !valid}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Cadastrando..." : "Cadastrar e enviar senha"}
        </button>
      </div>
    </Modal>
  );
}
