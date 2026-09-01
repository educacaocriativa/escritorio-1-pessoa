import type { AccountInvite, StaffInvite, TenantUsers, User } from "@e1p/shared-types";
import {
  Building2, ChevronDown, GraduationCap, Pencil, Power, Search, Trash2, UserPlus, Users,
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

// ── Resultado do convite: a única voz sobre o que aconteceu com a senha ──────────────────────
//
// Os dois modais (funcionário e conta nova) tinham cópias divergentes desta tela, e ambas
// erravam do mesmo jeito. Bug real de produção (2026-08-05): o Master leu
// "modo de teste (não saiu de verdade) — repasse a senha abaixo" sobre uma caixa de senha
// VAZIA. Eram dois defeitos somados:
//   (a) só `sent` contava como sucesso, mas o WhatsApp devolve `queued` desde a Onda 3 (a
//       entrega real é do worker) — o caminho normal era relatado como falha;
//   (b) em produção a API não devolve a senha (Story 2.1 AC3) e o JSX renderizava
//       `{invite.temp_password}` cru, deixando o rótulo órfão sobre o nada.
// Daí a caixa da senha só existir quando há senha, e a frase derivar do status inteiro.

const CANAL: Record<string, string> = { whatsapp: "WhatsApp", email: "e-mail" };

/** Frase + se a entrega aconteceu. `entregue: false` é o que autoriza o tom de alerta. */
function mensagemDeEntrega(status: string, canal: string): { texto: string; entregue: boolean } {
  switch (status) {
    case "sent":
      return { texto: `A senha foi enviada por ${canal}.`, entregue: true };
    case "queued":
      // A fila é o caminho normal, não uma degradação: o worker entrega fora do request.
      return { texto: `A senha foi enviada por ${canal} e chega em instantes.`, entregue: true };
    case "unconfigured":
      return {
        texto: `A senha NÃO foi enviada: o ${canal} desta conta não está conectado.`,
        entregue: false,
      };
    case "failed":
      return { texto: `A senha NÃO foi enviada: o envio por ${canal} falhou.`, entregue: false };
    default:
      // "logged" — provedor sem credencial devolve isso; é o modo de teste de verdade.
      return {
        texto: `O envio por ${canal} está em modo de teste (não saiu de verdade).`,
        entregue: false,
      };
  }
}

function InviteResult({
  quem, delivery, deliveryStatus, tempPassword, rodape, onConcluir,
}: {
  quem: string;
  delivery: string;
  deliveryStatus: string;
  tempPassword?: string | null;
  rodape: string;
  onConcluir: () => void;
}) {
  const canal = CANAL[delivery] ?? delivery;
  const { texto, entregue } = mensagemDeEntrega(deliveryStatus, canal);
  return (
    <div className="space-y-3 text-sm">
      <p className="text-neutral-600">
        <strong>{quem}</strong> foi cadastrado. {texto}
        {!entregue && tempPassword ? " Repasse a senha abaixo." : ""}
      </p>
      {tempPassword ? (
        <div className="rounded-xl bg-neutral-50 p-3">
          <p className="text-xs text-neutral-400">Senha temporária</p>
          <p className="select-all font-mono text-base font-semibold text-neutral-800">
            {tempPassword}
          </p>
        </div>
      ) : null}
      {!entregue && !tempPassword ? (
        // Sem entrega E sem senha à mão, dizer "repasse abaixo" seria mandar o Master fazer o
        // impossível. O caminho honesto é conectar o transporte e cadastrar de novo.
        <p className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800">
          A senha não aparece aqui por segurança e o envio não aconteceu, então este usuário
          ainda não tem como entrar. Conecte o {canal} em Configurações e cadastre novamente.
        </p>
      ) : null}
      <p className="text-xs text-neutral-500">{rodape}</p>
      <button
        onClick={onConcluir}
        className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500"
      >
        Concluir
      </button>
    </div>
  );
}

// Módulos que um funcionário pode receber (vazio = acesso a tudo).
//
// ⚠️ Precisa espelhar o conjunto de `module` usado em `app/navigation.ts` — é o mesmo nome que
// `require_module` usa no backend. Faltava aqui `cockpit`, `bank`, `financial_intelligence`,
// `investments`, `cost_centers`, `pages` e `settings`: o Master nunca teve como CONCEDER esses
// módulos a um funcionário, porque a lista que alimenta este seletor nunca os teve. Foi assim
// que um funcionário cadastrado com módulos restritos ficou sem acesso a Configurações — não dava
// para marcar essa caixa, porque a caixa não existia.
export const MODULES: { key: string; label: string }[] = [
  { key: "cockpit", label: "Dashboard" },
  { key: "agenda", label: "Agenda" },
  { key: "crm", label: "CRM" },
  { key: "wallet", label: "Financeiro" },
  { key: "bank", label: "Contas & Saldos" },
  { key: "receivables", label: "Cobranças" },
  { key: "payables", label: "Contas a Pagar" },
  { key: "financial_intelligence", label: "DRE, Lucratividade & Projeção" },
  { key: "investments", label: "Investimentos" },
  { key: "chart_of_accounts", label: "Plano de contas" },
  { key: "cost_centers", label: "Centros de custo" },
  { key: "quotes", label: "Orçamentos" },
  { key: "contracts", label: "Contratos" },
  { key: "products", label: "Produtos" },
  { key: "stock", label: "Estoque" },
  { key: "marketing", label: "Marketing" },
  { key: "funnels", label: "Funil de Vendas" },
  { key: "pages", label: "Sites" },
  { key: "juridico", label: "Jurídico" },
  { key: "settings", label: "Configurações" },
];

/** Grade de módulos reutilizada pelo cadastro e pela edição — a mesma lista, o mesmo toggle. */
function ModulePicker({ selected, onToggle }: { selected: string[]; onToggle: (key: string) => void }) {
  return (
    <div>
      <p className="mb-1.5 text-sm font-medium text-neutral-600">Acesso a módulos</p>
      <p className="mb-2 text-xs text-neutral-400">Nenhum marcado = acesso a tudo.</p>
      <div className="flex flex-wrap gap-1.5">
        {MODULES.map((m) => (
          <button
            key={m.key}
            type="button"
            onClick={() => onToggle(m.key)}
            className={`rounded-pill px-2.5 py-1 text-xs font-medium ${
              selected.includes(m.key) ? "bg-primary-500 text-white" : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function PlatformUsers() {
  const [nodes, setNodes] = useState<TenantUsers[]>([]);
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [newAccount, setNewAccount] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get<TenantUsers[]>("/admin/users");
    // `Array.isArray`, e aqui não havia operador nenhum: `nodes.reduce`/`nodes.filter` rodam nos
    // `useMemo` abaixo, em tempo de RENDER — fora do alcance de qualquer `catch` deste `load`.
    setNodes(Array.isArray(data) ? data : []);
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
  const [editUser, setEditUser] = useState<User | null>(null);
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
              node.staff.map((u) => (
                <UserRow key={u.id} user={u} onToggle={toggleUser} onEdit={setEditUser} onDelete={removeUser} />
              ))
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

      {editUser && (
        <EditPermissionsModal
          user={editUser}
          onClose={() => setEditUser(null)}
          onSaved={() => { setEditUser(null); onChanged(); }}
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

function UserRow({
  user, onToggle, onEdit, onDelete,
}: {
  user: User;
  onToggle: (u: User) => void;
  onEdit?: (u: User) => void;
  onDelete?: (u: User) => void;
}) {
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
        {onEdit && (
          <button
            onClick={() => onEdit(user)}
            title="Editar permissões"
            className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100"
          >
            <Pencil size={15} />
          </button>
        )}
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
    return (
      <Modal title="Usuário cadastrado" open onClose={() => { onClose(); onCreated(); }}>
        <InviteResult
          quem={invite.user.name}
          delivery={invite.delivery}
          deliveryStatus={invite.delivery_status}
          tempPassword={invite.temp_password}
          rodape="No primeiro acesso o usuário entra com essa senha e define uma nova."
          onConcluir={() => { onClose(); onCreated(); }}
        />
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

        <ModulePicker selected={modules} onToggle={toggle} />
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

/**
 * Edita `allowed_modules` de um funcionário JÁ cadastrado. `AddStaffModal` só marca o acesso na
 * criação; até aqui não havia nenhum jeito de VER ou AJUSTAR depois — o Master tinha de consultar
 * a rede do navegador para descobrir por que um item da sidebar sumiu para alguém.
 *
 * Só faz sentido para `role === "sub_user"`: o dono (`owner`) sempre vê tudo, independente de
 * `allowed_modules` (`lib/access.ts::hasModule`), então editar a lista dele não teria efeito
 * nenhum — `OfficeCard` não oferece este modal para a linha do admin.
 */
function EditPermissionsModal({
  user, onClose, onSaved,
}: {
  user: User;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [modules, setModules] = useState<string[]>(user.allowed_modules);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggle(key: string) {
    setModules((m) => (m.includes(key) ? m.filter((k) => k !== key) : [...m, key]));
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/admin/users/${user.id}`, { allowed_modules: modules });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Permissões de ${user.name}`} open onClose={onClose}>
      <div className="space-y-3">
        <ModulePicker selected={modules} onToggle={toggle} />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Salvar permissões"}
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
    return (
      <Modal title="Conta criada" open onClose={finish}>
        <InviteResult
          quem={`${invite.owner.name} (${invite.tenant.legal_name})`}
          delivery={invite.delivery}
          deliveryStatus={invite.delivery_status}
          tempPassword={invite.temp_password}
          rodape="No primeiro acesso o dono define uma nova senha."
          onConcluir={finish}
        />
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
