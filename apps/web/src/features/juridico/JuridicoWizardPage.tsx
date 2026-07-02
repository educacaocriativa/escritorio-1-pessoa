import type { Client, LegalDocument, LegalWizardConfig, LegalWizardField } from "@e1p/shared-types";
import { ArrowLeft, Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";

type Answers = Record<string, string | string[]>;

export default function JuridicoWizardPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const skill = params.get("skill") ?? "";

  const [cfg, setCfg] = useState<LegalWizardConfig | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [clientId, setClientId] = useState("");
  const [clients, setClients] = useState<Client[]>([]);
  const [extracted, setExtracted] = useState<{ name: string; chars: number }[]>([]);
  const [extractedText, setExtractedText] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!skill) return;
    api
      .get<LegalWizardConfig>(`/juridico/skills/${skill}`)
      .then(({ data }) => setCfg(data))
      .catch(() => setError("Especialidade não encontrada."));
    api.get<Client[]>("/crm/clients").then(({ data }) => setClients(data));
  }, [skill]);

  const set = useCallback((key: string, value: string | string[]) => {
    setAnswers((a) => ({ ...a, [key]: value }));
  }, []);

  async function onUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setExtracting(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        const { data } = await api.post<{ filename: string; chars: number; text: string }>(
          "/juridico/extract",
          form,
          { headers: { "Content-Type": "multipart/form-data" } },
        );
        setExtracted((prev) => [...prev, { name: data.filename, chars: data.chars }]);
        setExtractedText((prev) =>
          `${prev}\n\n### Arquivo: ${data.filename}\n${data.text}`.trim(),
        );
      }
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setExtracting(false);
    }
  }

  const missingRequired = useMemo(() => {
    if (!cfg) return true;
    for (const step of cfg.steps) {
      for (const f of step.fields) {
        if (!f.required) continue;
        if (f.type === "upload") {
          if (extracted.length === 0) return true;
        } else if (!answers[f.key] || (answers[f.key] as string).length === 0) {
          return true;
        }
      }
    }
    return false;
  }, [cfg, answers, extracted]);

  async function generate() {
    setGenerating(true);
    setError("");
    try {
      const { data } = await api.post<LegalDocument>("/juridico/documents", {
        skill,
        answers,
        client_id: clientId || null,
        extracted_text: extractedText,
      });
      navigate(`/juridico/${data.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
      setGenerating(false);
    }
  }

  if (!skill) {
    return <p className="text-sm text-neutral-500">Nenhuma especialidade selecionada.</p>;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <button
        onClick={() => navigate("/juridico")}
        className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
      >
        <ArrowLeft size={16} /> Voltar
      </button>

      <div>
        <p className="text-sm text-neutral-500">Jurídico / Nova peça</p>
        <h1 className="text-2xl font-bold text-neutral-800">{cfg?.label ?? skill}</h1>
        {cfg?.description && <p className="mt-1 text-sm text-neutral-500">{cfg.description}</p>}
      </div>

      {cfg?.steps.map((step) => (
        <section key={step.id} className="space-y-4 rounded-2xl bg-white p-5 shadow-sm">
          <div>
            <h2 className="text-sm font-semibold text-neutral-800">{step.title}</h2>
            {step.description && (
              <p className="mt-0.5 text-xs text-neutral-500">{step.description}</p>
            )}
          </div>
          {step.fields.map((f) => (
            <Field
              key={f.key}
              field={f}
              value={(answers[f.key] as string) ?? ""}
              onChange={(v) => set(f.key, v)}
              onUpload={onUpload}
              extracting={extracting}
              extracted={extracted}
            />
          ))}
        </section>
      ))}

      <section className="space-y-2 rounded-2xl bg-white p-5 shadow-sm">
        <label className="text-sm font-medium text-neutral-700">Cliente vinculado (opcional)</label>
        <select
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm"
        >
          <option value="">— Nenhum —</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <p className="text-xs text-neutral-400">
          Vincular liga este documento à Ficha 360° do cliente no CRM.
        </p>
      </section>

      {error && (
        <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>
      )}

      <button
        onClick={generate}
        disabled={generating || missingRequired || extracting}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {generating ? (
          <>
            <Loader2 className="animate-spin" size={18} /> A IA está redigindo…
          </>
        ) : (
          "Gerar documento"
        )}
      </button>
      <p className="text-center text-xs text-neutral-400">
        Dados sensíveis (CPF, e-mail, telefone) são anonimizados antes de ir à IA.
      </p>
    </div>
  );
}

function Field({
  field,
  value,
  onChange,
  onUpload,
  extracting,
  extracted,
}: {
  field: LegalWizardField;
  value: string;
  onChange: (v: string) => void;
  onUpload: (files: FileList | null) => void;
  extracting: boolean;
  extracted: { name: string; chars: number }[];
}) {
  const label = (
    <label className="text-sm font-medium text-neutral-700">
      {field.label}
      {field.required && <span className="text-danger"> *</span>}
    </label>
  );

  if (field.type === "upload") {
    return (
      <div className="space-y-2">
        {label}
        <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-neutral-300 px-3 py-4 text-sm text-neutral-500 hover:border-primary-400 hover:text-primary-600">
          {extracting ? <Loader2 className="animate-spin" size={16} /> : <Upload size={16} />}
          {extracting ? "Extraindo texto…" : "Enviar arquivo(s) — PDF, Word, imagem"}
          <input
            type="file"
            multiple={field.multiple}
            accept={field.accept}
            className="hidden"
            onChange={(e) => onUpload(e.target.files)}
          />
        </label>
        {extracted.length > 0 && (
          <ul className="space-y-1 text-xs text-neutral-500">
            {extracted.map((x, i) => (
              <li key={i}>
                ✓ {x.name} — {x.chars.toLocaleString("pt-BR")} caracteres extraídos
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  if (field.type === "select") {
    return (
      <div className="space-y-1.5">
        {label}
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm"
        >
          <option value="">— Selecione —</option>
          {field.options?.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </div>
    );
  }

  if (field.type === "textarea") {
    return (
      <div className="space-y-1.5">
        {label}
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          rows={4}
          className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm"
        />
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {label}
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.placeholder}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm"
      />
    </div>
  );
}
