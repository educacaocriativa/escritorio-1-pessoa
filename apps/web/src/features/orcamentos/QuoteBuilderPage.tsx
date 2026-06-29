import type { Client, PublicProposal, Quote } from "@e1p/shared-types";
import {
  ArrowLeft,
  ExternalLink,
  Eye,
  Plus,
  Save,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import ProposalView from "./ProposalView";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const toCents = (s: string) => Math.round(parseFloat((s || "").replace(",", ".") || "0") * 100);
const fromCents = (c: number) => (c / 100).toFixed(2).replace(".", ",");

type Service = { description: string; subtitle: string; quantity: number; price: string };
type Img = { url: string; caption: string };
type Stage = { title: string; when: string; description: string };

const TABS = ["Serviços", "Dados", "Imagens", "Cronograma", "Contrato", "Aparência"] as const;
type Tab = (typeof TABS)[number];

const blankService = (): Service => ({ description: "", subtitle: "", quantity: 1, price: "" });

export default function QuoteBuilderPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id || id === "novo";

  const [tab, setTab] = useState<Tab>("Serviços");
  const [quoteId, setQuoteId] = useState<string | null>(isNew ? null : id!);
  const [slug, setSlug] = useState<string | null>(null);
  const [status, setStatus] = useState<Quote["status"]>("draft");
  const [clients, setClients] = useState<Client[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  // form
  const [title, setTitle] = useState("");
  const [clientId, setClientId] = useState("");
  const [services, setServices] = useState<Service[]>([blankService()]);
  const [discount, setDiscount] = useState("");
  const [clientName, setClientName] = useState("");
  const [clientWhatsapp, setClientWhatsapp] = useState("");
  const [linkPassword, setLinkPassword] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("");
  const [showGallery, setShowGallery] = useState(false);
  const [gallery, setGallery] = useState<Img[]>([]);
  const [showSchedule, setShowSchedule] = useState(false);
  const [schedule, setSchedule] = useState<Stage[]>([]);
  const [showContract, setShowContract] = useState(false);
  const [contractText, setContractText] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [primaryColor, setPrimaryColor] = useState("#5D44F8");
  const [bgColor, setBgColor] = useState("#FFFFFF");
  const [textColor, setTextColor] = useState("#1F2937");
  const [accentColor, setAccentColor] = useState("#3DD68C");
  const [brief, setBrief] = useState("");
  const [aiBusy, setAiBusy] = useState(false);

  useEffect(() => {
    api.get<Client[]>("/crm/clients").then(({ data }) => setClients(data));
  }, []);

  const hydrate = useCallback((q: Quote) => {
    setQuoteId(q.id);
    setSlug(q.public_slug);
    setStatus(q.status);
    setTitle(q.title);
    setClientId(q.client_id ?? "");
    setServices(
      q.items.length
        ? q.items.map((i) => ({
            description: i.description,
            subtitle: i.subtitle ?? "",
            quantity: i.quantity,
            price: fromCents(i.unit_price_cents),
          }))
        : [blankService()],
    );
    setDiscount(q.discount_cents ? fromCents(q.discount_cents) : "");
    setClientName(q.client_name);
    setClientWhatsapp(q.client_whatsapp);
    setPaymentTerms(q.payment_terms);
    setShowGallery(q.show_gallery);
    setGallery(q.gallery.map((g) => ({ url: g.url, caption: g.caption ?? "" })));
    setShowSchedule(q.show_schedule);
    setSchedule(q.schedule.map((s) => ({ title: s.title, when: s.when ?? "", description: s.description ?? "" })));
    setShowContract(q.show_contract);
    setContractText(q.contract_text);
    setLogoUrl(q.logo_url);
    setPrimaryColor(q.primary_color);
    setBgColor(q.bg_color);
    setTextColor(q.text_color);
    setAccentColor(q.accent_color);
  }, []);

  useEffect(() => {
    if (!isNew && id) api.get<Quote>(`/quotes/${id}`).then(({ data }) => hydrate(data));
  }, [isNew, id, hydrate]);

  const items = useMemo(
    () =>
      services
        .filter((s) => s.description.trim())
        .map((s) => ({
          description: s.description,
          subtitle: s.subtitle,
          quantity: Math.max(1, s.quantity || 1),
          unit_price_cents: toCents(s.price),
        })),
    [services],
  );
  const subtotal = items.reduce((a, i) => a + i.quantity * i.unit_price_cents, 0);
  const total = Math.max(0, subtotal - toCents(discount));

  const preview: PublicProposal = {
    title: title || "Sua proposta",
    client_name: clientName,
    items,
    subtotal_cents: subtotal,
    discount_cents: toCents(discount),
    total_cents: total,
    payment_terms: paymentTerms,
    show_gallery: showGallery,
    gallery,
    show_schedule: showSchedule,
    schedule,
    show_contract: showContract,
    contract_text: contractText,
    logo_url: logoUrl,
    primary_color: primaryColor,
    bg_color: bgColor,
    text_color: textColor,
    accent_color: accentColor,
    status,
    valid_until: null,
  };

  function payload() {
    return {
      title,
      client_id: clientId || null,
      items,
      discount_cents: toCents(discount),
      client_name: clientName,
      client_whatsapp: clientWhatsapp,
      payment_terms: paymentTerms,
      link_password: linkPassword || (isNew ? null : ""),
      show_gallery: showGallery,
      gallery: gallery.filter((g) => g.url.trim()),
      show_schedule: showSchedule,
      schedule: schedule.filter((s) => s.title.trim()),
      show_contract: showContract,
      contract_text: contractText,
      logo_url: logoUrl,
      primary_color: primaryColor,
      bg_color: bgColor,
      text_color: textColor,
      accent_color: accentColor,
    };
  }

  async function save(): Promise<string | null> {
    if (!title.trim() || items.length === 0) {
      setError("Informe um título e ao menos um serviço.");
      return null;
    }
    setSaving(true);
    setError(null);
    try {
      let q: Quote;
      if (quoteId) {
        q = (await api.patch<Quote>(`/quotes/${quoteId}`, payload())).data;
      } else {
        q = (await api.post<Quote>("/quotes", payload())).data;
        window.history.replaceState(null, "", `/orcamentos/${q.id}`);
      }
      hydrate(q);
      setLinkPassword("");
      setSavedAt(new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }));
      return q.id;
    } catch (err) {
      setError(apiErrorMessage(err));
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function send() {
    const savedId = quoteId ?? (await save());
    if (!savedId) return;
    try {
      const { data } = await api.post<Quote>(`/quotes/${savedId}/send`);
      setStatus(data.status);
      setSavedAt("enviado");
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function view() {
    const savedId = await save();
    if (savedId && slug) window.open(`/orcamento/${slug}`, "_blank");
  }

  async function generateScope() {
    if (!brief.trim()) return;
    setAiBusy(true);
    try {
      const { data } = await api.post<{ description: string }>("/quotes/scope", { brief });
      setServices((s) => s.map((row, i) => (i === 0 ? { ...row, subtitle: data.description } : row)));
    } finally {
      setAiBusy(false);
    }
  }

  const readonly = status !== "draft";

  return (
    <div className="flex h-full flex-col">
      {/* Barra superior */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <button onClick={() => navigate("/orcamentos")} className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-700">
          <ArrowLeft size={16} /> Orçamentos
        </button>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-xs text-neutral-400">Total</p>
            <p className="text-lg font-bold text-neutral-800">{brl(total)}</p>
          </div>
          <button onClick={send} disabled={saving || readonly} className="flex items-center gap-1.5 rounded-pill bg-primary-500 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-600 disabled:opacity-50">
            <Send size={14} /> Enviar
          </button>
          <button onClick={view} disabled={saving} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-4 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-200 disabled:opacity-50">
            <Eye size={14} /> Ver
          </button>
          <button onClick={save} disabled={saving || readonly} className="flex items-center gap-1.5 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-50">
            <Save size={14} /> {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>

      {readonly && (
        <div className="mb-3 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-700">
          Este orçamento está <b>{status}</b> e não pode mais ser editado.
        </div>
      )}
      {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
      {savedAt && !error && (
        <div className="mb-3 text-xs text-neutral-400">
          {savedAt === "enviado" ? "Proposta enviada ao cliente." : `Salvo às ${savedAt}.`}
          {slug && (
            <a href={`/orcamento/${slug}`} target="_blank" rel="noreferrer" className="ml-2 inline-flex items-center gap-0.5 text-primary-600">
              link público <ExternalLink size={11} />
            </a>
          )}
        </div>
      )}

      <div className="grid flex-1 grid-cols-1 gap-6 overflow-hidden lg:grid-cols-2">
        {/* Editor */}
        <div className="flex flex-col overflow-hidden rounded-2xl bg-white shadow-sm">
          <div className="flex gap-1 overflow-x-auto border-b border-neutral-100 p-2">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`whitespace-nowrap rounded-pill px-3 py-1.5 text-sm font-medium ${tab === t ? "bg-primary-50 text-primary-700" : "text-neutral-500 hover:text-neutral-700"}`}>
                {t}
              </button>
            ))}
          </div>
          <div className={`flex-1 space-y-3 overflow-auto p-4 ${readonly ? "pointer-events-none opacity-60" : ""}`}>
            {tab === "Serviços" && (
              <ServicesTab
                services={services}
                setServices={setServices}
                discount={discount}
                setDiscount={setDiscount}
                title={title}
                setTitle={setTitle}
                brief={brief}
                setBrief={setBrief}
                aiBusy={aiBusy}
                onAi={generateScope}
              />
            )}
            {tab === "Dados" && (
              <DadosTab
                clients={clients}
                clientId={clientId}
                setClientId={setClientId}
                clientName={clientName}
                setClientName={setClientName}
                clientWhatsapp={clientWhatsapp}
                setClientWhatsapp={setClientWhatsapp}
                linkPassword={linkPassword}
                setLinkPassword={setLinkPassword}
                paymentTerms={paymentTerms}
                setPaymentTerms={setPaymentTerms}
              />
            )}
            {tab === "Imagens" && (
              <ListTab
                show={showGallery}
                setShow={setShowGallery}
                showLabel="Mostrar galeria"
                addLabel="Adicionar imagem"
                rows={gallery}
                setRows={setGallery}
                blank={{ url: "", caption: "" }}
                fields={[
                  { key: "url", placeholder: "URL da imagem (https://...)" },
                  { key: "caption", placeholder: "Legenda (opcional)" },
                ]}
              />
            )}
            {tab === "Cronograma" && (
              <ListTab
                show={showSchedule}
                setShow={setShowSchedule}
                showLabel="Mostrar cronograma"
                addLabel="Adicionar etapa"
                rows={schedule}
                setRows={setSchedule}
                blank={{ title: "", when: "", description: "" }}
                fields={[
                  { key: "title", placeholder: "Etapa" },
                  { key: "when", placeholder: "Quando (ex: Semana 1)" },
                  { key: "description", placeholder: "Descrição (opcional)" },
                ]}
              />
            )}
            {tab === "Contrato" && (
              <div className="space-y-3">
                <Toggle checked={showContract} onChange={setShowContract} label="Mostrar prévia de contrato" />
                <textarea value={contractText} onChange={(e) => setContractText(e.target.value)} rows={10} placeholder="Cole aqui as cláusulas do contrato que o cliente verá na proposta." className="w-full rounded-lg border border-neutral-200 p-3 text-sm outline-none focus:border-primary-400" />
              </div>
            )}
            {tab === "Aparência" && (
              <AparenciaTab
                logoUrl={logoUrl}
                setLogoUrl={setLogoUrl}
                primaryColor={primaryColor}
                setPrimaryColor={setPrimaryColor}
                bgColor={bgColor}
                setBgColor={setBgColor}
                textColor={textColor}
                setTextColor={setTextColor}
                accentColor={accentColor}
                setAccentColor={setAccentColor}
              />
            )}
          </div>
        </div>

        {/* Prévia */}
        <div className="overflow-auto rounded-2xl border border-neutral-100 bg-neutral-50 p-4">
          <p className="mb-2 text-center text-xs uppercase tracking-wide text-neutral-400">Pré-visualização</p>
          <div className="rounded-2xl bg-white shadow-sm">
            <ProposalView p={preview} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Campos reutilizáveis ────────────────────────────────────────────────────
function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (b: boolean) => void; label: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-neutral-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-primary-500" />
      {label}
    </label>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400";

// ── Aba Serviços ────────────────────────────────────────────────────────────
function ServicesTab({
  services, setServices, discount, setDiscount, title, setTitle, brief, setBrief, aiBusy, onAi,
}: {
  services: Service[];
  setServices: React.Dispatch<React.SetStateAction<Service[]>>;
  discount: string;
  setDiscount: (s: string) => void;
  title: string;
  setTitle: (s: string) => void;
  brief: string;
  setBrief: (s: string) => void;
  aiBusy: boolean;
  onAi: () => void;
}) {
  const set = (i: number, patch: Partial<Service>) =>
    setServices((s) => s.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-3">
      <Labeled label="Título da proposta">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Proposta comercial" className={inputCls} />
      </Labeled>
      <div className="rounded-lg bg-primary-50 p-2">
        <span className="mb-1 block text-xs font-medium text-primary-700">Descrever escopo com IA</span>
        <div className="flex gap-2">
          <input value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="ex: consultoria tributária para PME" className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
          <button onClick={onAi} disabled={aiBusy || !brief.trim()} className="flex shrink-0 items-center gap-1 rounded-lg bg-primary-500 px-3 text-xs font-semibold text-white disabled:opacity-60">
            <Sparkles size={12} /> {aiBusy ? "..." : "Gerar"}
          </button>
        </div>
      </div>
      {services.map((s, i) => (
        <div key={i} className="space-y-2 rounded-xl border border-neutral-100 p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-neutral-400">Serviço {i + 1}</span>
            {services.length > 1 && (
              <button onClick={() => setServices((r) => r.filter((_, idx) => idx !== i))} className="text-neutral-300 hover:text-danger">
                <Trash2 size={14} />
              </button>
            )}
          </div>
          <input value={s.description} onChange={(e) => set(i, { description: e.target.value })} placeholder="Título exibido" className={inputCls} />
          <input value={s.subtitle} onChange={(e) => set(i, { subtitle: e.target.value })} placeholder="Subtítulo" className={inputCls} />
          <div className="flex gap-2">
            <Labeled label="Qtd">
              <input type="number" min={1} value={s.quantity} onChange={(e) => set(i, { quantity: parseInt(e.target.value, 10) || 1 })} className="w-20 rounded-lg border border-neutral-200 px-2 py-2 text-sm outline-none" />
            </Labeled>
            <Labeled label="Valor unitário (R$)">
              <input value={s.price} onChange={(e) => set(i, { price: e.target.value })} placeholder="0,00" className={inputCls} />
            </Labeled>
          </div>
        </div>
      ))}
      <button onClick={() => setServices((s) => [...s, blankService()])} className="flex items-center gap-1 text-sm font-medium text-primary-600">
        <Plus size={14} /> Adicionar serviço
      </button>
      <Labeled label="Desconto (R$)">
        <input value={discount} onChange={(e) => setDiscount(e.target.value)} placeholder="0,00" className={inputCls} />
      </Labeled>
    </div>
  );
}

// ── Aba Dados ───────────────────────────────────────────────────────────────
function DadosTab(props: {
  clients: Client[];
  clientId: string;
  setClientId: (s: string) => void;
  clientName: string;
  setClientName: (s: string) => void;
  clientWhatsapp: string;
  setClientWhatsapp: (s: string) => void;
  linkPassword: string;
  setLinkPassword: (s: string) => void;
  paymentTerms: string;
  setPaymentTerms: (s: string) => void;
}) {
  return (
    <div className="space-y-3">
      <Labeled label="Cliente do CRM (opcional — gera a cobrança ao aprovar)">
        <select value={props.clientId} onChange={(e) => props.setClientId(e.target.value)} className={inputCls}>
          <option value="">Sem cliente do CRM</option>
          {props.clients.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </Labeled>
      <Labeled label="Nome do cliente">
        <input value={props.clientName} onChange={(e) => props.setClientName(e.target.value)} className={inputCls} />
      </Labeled>
      <Labeled label="WhatsApp do cliente (DDI+DDD)">
        <input value={props.clientWhatsapp} onChange={(e) => props.setClientWhatsapp(e.target.value)} placeholder="+55 11 90000-0000" className={inputCls} />
      </Labeled>
      <Labeled label="Senha do link (opcional)">
        <input value={props.linkPassword} onChange={(e) => props.setLinkPassword(e.target.value)} placeholder="deixe em branco para link aberto" className={inputCls} />
      </Labeled>
      <p className="-mt-1 text-xs text-neutral-400">Com senha, o cliente precisa digitá-la para ver a proposta.</p>
      <Labeled label="Condições de pagamento">
        <textarea value={props.paymentTerms} onChange={(e) => props.setPaymentTerms(e.target.value)} rows={3} placeholder="ex: 50% na assinatura, 50% na entrega" className={inputCls} />
      </Labeled>
    </div>
  );
}

// ── Abas de lista (Imagens / Cronograma) ────────────────────────────────────
function ListTab<T extends Record<string, string>>({
  show, setShow, showLabel, addLabel, rows, setRows, blank, fields,
}: {
  show: boolean;
  setShow: (b: boolean) => void;
  showLabel: string;
  addLabel: string;
  rows: T[];
  setRows: React.Dispatch<React.SetStateAction<T[]>>;
  blank: T;
  fields: { key: keyof T; placeholder: string }[];
}) {
  return (
    <div className="space-y-3">
      <Toggle checked={show} onChange={setShow} label={showLabel} />
      {rows.map((row, i) => (
        <div key={i} className="space-y-2 rounded-xl border border-neutral-100 p-3">
          <div className="flex justify-end">
            <button onClick={() => setRows((r) => r.filter((_, idx) => idx !== i))} className="text-neutral-300 hover:text-danger">
              <Trash2 size={14} />
            </button>
          </div>
          {fields.map((f) => (
            <input
              key={String(f.key)}
              value={row[f.key]}
              onChange={(e) => setRows((r) => r.map((x, idx) => (idx === i ? { ...x, [f.key]: e.target.value } : x)))}
              placeholder={f.placeholder}
              className={inputCls}
            />
          ))}
        </div>
      ))}
      <button onClick={() => setRows((r) => [...r, { ...blank }])} className="flex items-center gap-1 text-sm font-medium text-primary-600">
        <Plus size={14} /> {addLabel}
      </button>
    </div>
  );
}

// ── Aba Aparência ───────────────────────────────────────────────────────────
function AparenciaTab(props: {
  logoUrl: string;
  setLogoUrl: (s: string) => void;
  primaryColor: string;
  setPrimaryColor: (s: string) => void;
  bgColor: string;
  setBgColor: (s: string) => void;
  textColor: string;
  setTextColor: (s: string) => void;
  accentColor: string;
  setAccentColor: (s: string) => void;
}) {
  const colors: [string, string, (s: string) => void][] = [
    ["Cor primária", props.primaryColor, props.setPrimaryColor],
    ["Fundo", props.bgColor, props.setBgColor],
    ["Texto", props.textColor, props.setTextColor],
    ["Destaque (aceite)", props.accentColor, props.setAccentColor],
  ];
  return (
    <div className="space-y-3">
      <Labeled label="Logo (URL — altura ideal ~56px)">
        <input value={props.logoUrl} onChange={(e) => props.setLogoUrl(e.target.value)} placeholder="https://.../logo.png" className={inputCls} />
      </Labeled>
      <div className="grid grid-cols-2 gap-3">
        {colors.map(([label, value, set]) => (
          <div key={label}>
            <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
            <div className="flex items-center gap-2">
              <input type="color" value={value} onChange={(e) => set(e.target.value)} className="h-9 w-10 cursor-pointer rounded border border-neutral-200" />
              <input value={value} onChange={(e) => set(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm uppercase outline-none" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
