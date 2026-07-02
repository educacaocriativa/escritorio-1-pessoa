import type { LegalDocumentSummary, LegalSkillSummary } from "@e1p/shared-types";
import { FileText, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { CATEGORY_META, CATEGORY_ORDER, categoryLabel } from "./categories";

export default function JuridicoPage() {
  const navigate = useNavigate();
  const [skills, setSkills] = useState<LegalSkillSummary[]>([]);
  const [docs, setDocs] = useState<LegalDocumentSummary[]>([]);

  const loadDocs = useCallback(async () => {
    const { data } = await api.get<LegalDocumentSummary[]>("/juridico/documents");
    setDocs(data);
  }, []);

  useEffect(() => {
    api.get<LegalSkillSummary[]>("/juridico/skills").then(({ data }) => setSkills(data));
    loadDocs();
  }, [loadDocs]);

  const byCategory = useMemo(() => {
    const map = new Map<string, LegalSkillSummary[]>();
    for (const s of skills) {
      const arr = map.get(s.category) ?? [];
      arr.push(s);
      map.set(s.category, arr);
    }
    return map;
  }, [skills]);

  async function removeDoc(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm("Excluir este documento?")) return;
    await api.delete(`/juridico/documents/${id}`);
    loadDocs();
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="text-sm text-neutral-500">Página / Jurídico</p>
        <h1 className="text-2xl font-bold text-neutral-800">Assistente Jurídico</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Escolha uma especialidade, preencha o roteiro e a IA redige a peça — com anonimização de
          dados sensíveis e protocolo anti-alucinação de jurisprudência.
        </p>
      </div>

      {docs.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-neutral-700">Documentos recentes</h2>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {docs.slice(0, 6).map((d) => (
              <button
                key={d.id}
                onClick={() => navigate(`/juridico/${d.id}`)}
                className="flex items-start gap-3 rounded-xl bg-white p-3 text-left shadow-sm transition hover:shadow-md"
              >
                <FileText className="mt-0.5 shrink-0 text-primary-600" size={18} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-neutral-700">{d.title}</p>
                  <p className="text-xs text-neutral-400">
                    {categoryLabel(d.category)}
                    {d.client_name ? ` · ${d.client_name}` : ""}
                    {d.status === "failed" ? " · falhou" : ""}
                  </p>
                </div>
                <button
                  onClick={(e) => removeDoc(e, d.id)}
                  className="shrink-0 text-neutral-300 hover:text-danger"
                >
                  <Trash2 size={14} />
                </button>
              </button>
            ))}
          </div>
        </section>
      )}

      {CATEGORY_ORDER.filter((c) => byCategory.has(c)).map((cat) => {
        const Icon = CATEGORY_META[cat]?.icon ?? FileText;
        return (
          <section key={cat} className="space-y-3">
            <div className="flex items-center gap-2">
              <Icon className="text-primary-600" size={18} />
              <h2 className="text-sm font-semibold text-neutral-700">{categoryLabel(cat)}</h2>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {byCategory.get(cat)!.map((s) => (
                <button
                  key={s.skill}
                  onClick={() => navigate(`/juridico/novo?skill=${s.skill}`)}
                  className="flex h-full flex-col rounded-2xl bg-white p-4 text-left shadow-sm transition hover:shadow-md hover:ring-1 hover:ring-primary-300"
                >
                  <p className="text-sm font-semibold text-neutral-800">{s.label}</p>
                  <p className="mt-1 line-clamp-3 flex-1 text-xs text-neutral-500">
                    {s.description}
                  </p>
                  <p className="mt-3 text-[11px] font-medium uppercase tracking-wide text-primary-600">
                    {s.output_type}
                  </p>
                </button>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
