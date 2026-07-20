import type {
  TenantProfile,
  WhatsappTemplate,
  WhatsappTemplateCategory,
  WhatsappTemplateCreate,
} from "@e1p/shared-types";
import { WHATSAPP_PURPOSES } from "@e1p/shared-types";
import { Check, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

const CATEGORY_LABEL: Record<WhatsappTemplateCategory, string> = {
  MARKETING: "Marketing",
  UTILITY: "Utilidade",
  AUTHENTICATION: "Autenticação",
};

const STATUS_LABEL: Record<WhatsappTemplate["status"], string> = {
  PENDING: "Pendente",
  APPROVED: "Aprovado",
  REJECTED: "Rejeitado",
  PAUSED: "Pausado",
  DISABLED: "Desativado",
};

const STATUS_CLASS: Record<WhatsappTemplate["status"], string> = {
  PENDING: "bg-amber-50 text-amber-700",
  APPROVED: "bg-green-50 text-green-700",
  REJECTED: "bg-red-50 text-danger",
  PAUSED: "bg-neutral-100 text-neutral-500",
  DISABLED: "bg-neutral-100 text-neutral-500",
};

/** Conta o maior índice `{{n}}` presente no corpo do template (0 se não houver nenhum). */
function countVariables(bodyText: string): number {
  const matches = [...bodyText.matchAll(/\{\{(\d+)\}\}/g)];
  return matches.reduce((max, m) => Math.max(max, Number(m[1])), 0);
}

export default function WhatsappSection() {
  return (
    <div className="space-y-6">
      <CredentialsCard />
      <TemplatesCard />
      <BindingsCard />
    </div>
  );
}

/** Card "WhatsApp Business (Meta Cloud API)" — credenciais por tenant. */
function CredentialsCard() {
  const [profile, setProfile] = useState<TenantProfile | null>(null);
  const [token, setToken] = useState("");
  const [tokenTouched, setTokenTouched] = useState(false);
  const [appSecret, setAppSecret] = useState("");
  const [appSecretTouched, setAppSecretTouched] = useState(false);
  const [phoneId, setPhoneId] = useState("");
  const [wabaId, setWabaId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<TenantProfile>("/settings/profile");
    setProfile(data);
    setPhoneId(data.whatsapp_phone_id ?? "");
    setWabaId(data.whatsapp_waba_id ?? "");
    setToken("");
    setTokenTouched(false);
    setAppSecret("");
    setAppSecretTouched(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const patch: Pick<TenantProfile, "whatsapp_phone_id" | "whatsapp_waba_id"> & {
        whatsapp_token?: string;
        whatsapp_app_secret?: string;
      } = {
        whatsapp_phone_id: phoneId.trim(),
        whatsapp_waba_id: wabaId.trim(),
      };
      if (tokenTouched) patch.whatsapp_token = token;
      if (appSecretTouched) patch.whatsapp_app_secret = appSecret;
      const { data } = await api.patch<TenantProfile>("/settings/profile", patch);
      setProfile(data);
      setPhoneId(data.whatsapp_phone_id ?? "");
      setWabaId(data.whatsapp_waba_id ?? "");
      setToken("");
      setTokenTouched(false);
      setAppSecret("");
      setAppSecretTouched(false);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const configured = profile?.whatsapp_configured ?? false;

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="font-semibold text-neutral-800">WhatsApp Business (Meta Cloud API)</h2>
        {profile &&
          (configured ? (
            <span className="flex items-center gap-1 rounded-pill bg-green-50 px-3 py-1 text-xs font-semibold text-green-700">
              <Check size={12} /> Conectado
            </span>
          ) : (
            <span className="rounded-pill bg-neutral-100 px-3 py-1 text-xs font-semibold text-neutral-500">
              Não conectado
            </span>
          ))}
      </div>
      <p className="mb-4 text-xs text-neutral-400">
        Essas credenciais vêm do painel Meta for Developers / WhatsApp Business Platform e são
        específicas deste escritório — não são compartilhadas com outros tenants.
      </p>

      {!profile ? (
        <p className="text-sm text-neutral-400">Carregando...</p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="mb-1 block text-xs font-medium text-neutral-600">
                Token de acesso
              </span>
              <input
                type="password"
                value={token}
                onChange={(e) => {
                  setToken(e.target.value);
                  setTokenTouched(true);
                }}
                placeholder={configured ? "••••••••" : "Cole o token de acesso"}
                className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
              />
            </label>
            <label className="block sm:col-span-2">
              <span className="mb-1 block text-xs font-medium text-neutral-600">
                App Secret
              </span>
              <input
                type="password"
                value={appSecret}
                onChange={(e) => {
                  setAppSecret(e.target.value);
                  setAppSecretTouched(true);
                }}
                placeholder={configured ? "••••••••" : "Cole o App Secret do seu App na Meta"}
                className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-neutral-600">
                Phone Number ID
              </span>
              <input
                value={phoneId}
                onChange={(e) => setPhoneId(e.target.value)}
                className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-neutral-600">WABA ID</span>
              <input
                value={wabaId}
                onChange={(e) => setWabaId(e.target.value)}
                className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
              />
            </label>
          </div>

          {profile.whatsapp_verify_token && (
            <div className="mt-4 rounded-xl border border-neutral-100 bg-neutral-50 p-4">
              <p className="mb-2 text-xs font-semibold text-neutral-600">
                Configure o webhook no painel da Meta (WhatsApp → Configuration):
              </p>
              <div className="mb-2">
                <span className="mb-1 block text-xs text-neutral-500">Callback URL</span>
                <code className="block truncate rounded-lg bg-white px-3 py-2 text-xs">
                  {`${window.location.origin}/api/public/whatsapp/webhook`}
                </code>
              </div>
              <div>
                <span className="mb-1 block text-xs text-neutral-500">Verify token</span>
                <code className="block truncate rounded-lg bg-white px-3 py-2 text-xs">
                  {profile.whatsapp_verify_token}
                </code>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>
          )}

          <button
            onClick={save}
            disabled={saving}
            className="mt-4 flex items-center gap-1.5 rounded-pill bg-primary-600 px-5 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Check size={14} /> {saving ? "Salvando..." : "Salvar"}
          </button>
        </>
      )}
    </div>
  );
}

/** Card "Templates de Mensagem" — a Meta exige template pré-aprovado para toda mensagem
 * business-initiated fora da janela de 24h de atendimento. */
function TemplatesCard() {
  const [configured, setConfigured] = useState(false);
  const [templates, setTemplates] = useState<WhatsappTemplate[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [{ data: profile }, { data: list }] = await Promise.all([
      api.get<TenantProfile>("/settings/profile"),
      api.get<WhatsappTemplate[]>("/whatsapp-templates"),
    ]);
    setConfigured(profile.whatsapp_configured);
    setTemplates(Array.isArray(list) ? list : []);
    setLoaded(true);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function sync(id: string) {
    setBusyId(id);
    setError(null);
    try {
      const { data } = await api.post<WhatsappTemplate>(`/whatsapp-templates/${id}/sync`);
      setTemplates((prev) => prev.map((t) => (t.id === id ? data : t)));
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function remove(id: string) {
    if (!confirm("Excluir este template? Essa ação não pode ser desfeita.")) return;
    setBusyId(id);
    setError(null);
    try {
      await api.delete(`/whatsapp-templates/${id}`);
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="font-semibold text-neutral-800">Templates de Mensagem</h2>
        {configured && (
          <button
            onClick={() => setShowForm((v) => !v)}
            className="flex items-center gap-1.5 rounded-pill bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700"
          >
            <Plus size={14} /> Novo template
          </button>
        )}
      </div>
      <p className="mb-4 text-xs text-neutral-400">
        A revisão da Meta pode levar de minutos a horas. Somente templates com status Aprovado
        podem ser usados para enviar mensagens.
      </p>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>
      )}

      {!loaded ? (
        <p className="text-sm text-neutral-400">Carregando...</p>
      ) : !configured ? (
        <p className="text-sm text-neutral-400">
          Configure as credenciais do WhatsApp acima primeiro.
        </p>
      ) : (
        <>
          {showForm && (
            <TemplateForm
              onCancel={() => setShowForm(false)}
              onCreated={async () => {
                setShowForm(false);
                await load();
              }}
            />
          )}

          {templates.length === 0 ? (
            <p className="text-sm text-neutral-400">Nenhum template criado ainda.</p>
          ) : (
            <div className="space-y-2">
              {templates.map((t) => (
                <div key={t.id} className="rounded-xl border border-neutral-100 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-neutral-800">
                        {t.name} <span className="font-normal text-neutral-400">({t.language})</span>
                      </p>
                      <p className="text-xs text-neutral-500">
                        {t.category_approved && t.category_approved !== t.category_requested
                          ? `solicitado: ${CATEGORY_LABEL[t.category_requested]} → aprovado: ${CATEGORY_LABEL[t.category_approved]}`
                          : CATEGORY_LABEL[t.category_approved ?? t.category_requested]}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-pill px-3 py-1 text-xs font-semibold ${STATUS_CLASS[t.status]}`}
                      >
                        {STATUS_LABEL[t.status]}
                      </span>
                      <button
                        onClick={() => sync(t.id)}
                        disabled={busyId === t.id}
                        title="Sincronizar"
                        className="text-neutral-300 hover:text-primary-600 disabled:opacity-50"
                      >
                        <RefreshCw size={16} />
                      </button>
                      <button
                        onClick={() => remove(t.id)}
                        disabled={busyId === t.id}
                        title="Excluir"
                        className="text-neutral-300 hover:text-danger disabled:opacity-50"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                  {t.rejected_reason && (
                    <p className="mt-2 text-xs text-danger">{t.rejected_reason}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Card "Vínculos de Template por Propósito" — liga um template APROVADO a cada propósito
 * fixo que o próprio produto define (lembrete de cobrança, envio de contrato/orçamento,
 * convite de staff, aviso interno de card movido). Diferente do nó livre do Funil de Vendas:
 * aqui a lista de propósitos é fixa (`WHATSAPP_PURPOSES`) e cada um exige um template com a
 * contagem exata de variáveis — o backend valida isso no PATCH e retorna 422 se não bater. */
function BindingsCard() {
  const [templates, setTemplates] = useState<WhatsappTemplate[]>([]);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const load = useCallback(async () => {
    const [{ data: profile }, { data: list }] = await Promise.all([
      api.get<TenantProfile>("/settings/profile"),
      api.get<WhatsappTemplate[]>("/whatsapp-templates"),
    ]);
    setTemplates(Array.isArray(list) ? list : []);
    const initial: Record<string, string> = {};
    for (const p of WHATSAPP_PURPOSES) {
      initial[p.key] = profile.whatsapp_template_bindings?.[p.key] ?? "";
    }
    setBindings(initial);
    setLoaded(true);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const approvedTemplates = useMemo(
    () => templates.filter((t) => t.status === "APPROVED"),
    [templates],
  );

  function setBinding(purposeKey: string, templateId: string) {
    setBindings((prev) => ({ ...prev, [purposeKey]: templateId }));
    setSuccess(false);
  }

  async function save() {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await api.patch<TenantProfile>("/settings/profile", {
        whatsapp_template_bindings: bindings,
      });
      setSuccess(true);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h2 className="mb-1 font-semibold text-neutral-800">Vínculos de Template por Propósito</h2>
      <p className="mb-4 text-xs text-neutral-400">
        Escolha qual template aprovado o sistema deve usar automaticamente em cada fluxo. Deixe
        "Nenhum (texto livre)" para continuar enviando texto livre nesse fluxo.
      </p>

      {!loaded ? (
        <p className="text-sm text-neutral-400">Carregando...</p>
      ) : (
        <>
          <div className="space-y-2">
            {WHATSAPP_PURPOSES.map((p) => {
              const matching = approvedTemplates.filter(
                (t) => t.variable_count === p.variables.length,
              );
              return (
                <div key={p.key} className="rounded-xl border border-neutral-100 px-4 py-3">
                  <p className="text-sm font-semibold text-neutral-800">{p.label}</p>
                  <p className="mb-2 text-xs text-neutral-400">
                    Variáveis: {p.variables.join(", ")}
                  </p>
                  <select
                    aria-label={p.label}
                    value={bindings[p.key] ?? ""}
                    onChange={(e) => setBinding(p.key, e.target.value)}
                    className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
                  >
                    <option value="">— Nenhum (texto livre) —</option>
                    {matching.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                  {matching.length === 0 && (
                    <p className="mt-1 text-xs text-neutral-400">
                      Nenhum template aprovado com {p.variables.length} variáveis ainda.
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          {error && (
            <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>
          )}
          {success && (
            <div className="mt-3 rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">
              Vínculos salvos
            </div>
          )}

          <button
            onClick={save}
            disabled={saving}
            className="mt-4 flex items-center gap-1.5 rounded-pill bg-primary-600 px-5 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Check size={14} /> {saving ? "Salvando..." : "Salvar vínculos"}
          </button>
        </>
      )}
    </div>
  );
}

function TemplateForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("pt_BR");
  const [category, setCategory] = useState<WhatsappTemplateCategory>("MARKETING");
  const [bodyText, setBodyText] = useState("");
  const [examples, setExamples] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const variableCount = useMemo(() => countVariables(bodyText), [bodyText]);

  useEffect(() => {
    setExamples((prev) => {
      const next = prev.slice(0, variableCount);
      while (next.length < variableCount) next.push("");
      return next;
    });
  }, [variableCount]);

  async function submit() {
    setCreating(true);
    setError(null);
    try {
      const payload: WhatsappTemplateCreate = {
        name: name.trim(),
        language: language.trim(),
        category,
        body_text: bodyText,
        variable_examples: examples,
      };
      await api.post<WhatsappTemplate>("/whatsapp-templates", payload);
      await onCreated();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-neutral-200 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Nome</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="ex: boas_vindas_lead"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
          <span className="mt-1 block text-xs text-neutral-400">
            minúsculas, números e underscore apenas — ex: boas_vindas_lead
          </span>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Idioma</span>
          <input
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
        </label>
        <label className="block sm:col-span-2">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Categoria</span>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as WhatsappTemplateCategory)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="MARKETING">Marketing</option>
            <option value="UTILITY">Utilidade</option>
            <option value="AUTHENTICATION">Autenticação</option>
          </select>
        </label>
        <label className="block sm:col-span-2">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Texto</span>
          <textarea
            value={bodyText}
            onChange={(e) => setBodyText(e.target.value)}
            rows={3}
            placeholder="Use {{1}}, {{2}} etc para variáveis"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
        </label>
        {examples.map((ex, i) => (
          <label className="block" key={i}>
            <span className="mb-1 block text-xs font-medium text-neutral-600">
              Exemplo da variável {i + 1}
            </span>
            <input
              value={ex}
              onChange={(e) =>
                setExamples((prev) => prev.map((v, idx) => (idx === i ? e.target.value : v)))
              }
              className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
            />
          </label>
        ))}
      </div>

      {error && (
        <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>
      )}

      <div className="mt-4 flex gap-2">
        <button
          onClick={submit}
          disabled={creating || !name.trim() || !bodyText.trim()}
          className="flex items-center gap-1.5 rounded-pill bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
        >
          <Check size={14} /> {creating ? "Criando..." : "Criar template"}
        </button>
        <button
          onClick={onCancel}
          className="rounded-pill border border-neutral-200 px-4 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-50"
        >
          Cancelar
        </button>
      </div>
    </div>
  );
}
