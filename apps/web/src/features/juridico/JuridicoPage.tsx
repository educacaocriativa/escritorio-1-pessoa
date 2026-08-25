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
    // `Array.isArray`, e aqui não havia operador nenhum: `docs.slice(0, 6).map` roda no render.
    setDocs(Array.isArray(data) ? data : []);
  }, []);

  useEffect(() => {
    // `Array.isArray`, e aqui não havia operador nenhum. Este site escapa da varredura por
    // `.map`/`.length`/`.filter`: o consumo é `for (const s of skills)` dentro do `useMemo` abaixo —
    // igualmente em tempo de render, e igualmente fatal com payload não iterável.
    api
      .get<LegalSkillSummary[]>("/juridico/skills")
      .then(({ data }) => setSkills(Array.isArray(data) ? data : []));
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
          {/* ⚠️ `grid-cols-1` não é redundante com o `sm:grid-cols-2` (#182). Sem uma contagem de
              colunas no breakpoint base, a grade tem UMA coluna implícita de tamanho `auto`, e
              trilha `auto` cresce com o min-content do conteúdo — um título sem espaço a levava a
              585,5px numa tela de 360. `grid-cols-1` é `repeat(1, minmax(0, 1fr))` no Tailwind, e é
              o `minmax(0, …)` que segura a trilha. Medido: a lixeira `absolute right-3` ia junto,
              para x=583,5 → 597,5 — **inteiramente fora**, sem jeito de excluir um documento no
              celular — e `documentElement.scrollWidth` continuava dizendo 360. */}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {docs.slice(0, 6).map((d) => (
              // ⚠️ A lixeira é IRMÃ do card, nunca filha (#160) — ver o comentário longo em
              // `funis/FunisPage.tsx`. Resumo: com os dois alvos aninhados, 10px de deslocamento
              // entre `mousedown` e `mouseup` fazem o navegador emitir o `click` no ancestral
              // comum, e o toque na lixeira vira navegação (#149).
              <div key={d.id} className="relative">
                <button
                  data-testid={`abrir-documento-${d.id}`}
                  onClick={() => navigate(`/juridico/${d.id}`)}
                  className="flex w-full items-start gap-3 rounded-xl bg-white p-3 pr-9 text-left shadow-sm transition hover:shadow-md"
                >
                  <FileText className="mt-0.5 shrink-0 text-primary-600" size={18} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-neutral-700">{d.title}</p>
                    {/* O título acima é `truncate` (recorta com reticências); esta linha não pode
                        ser, porque o nome do cliente precisa ser lido inteiro. `break-words`
                        (#182): sem ele o `client_name` sem espaço saía 213,5px além da borda. */}
                    <p className="break-words text-xs text-neutral-400">
                      {categoryLabel(d.category)}
                      {d.client_name ? ` · ${d.client_name}` : ""}
                      {d.status === "failed" ? " · falhou" : ""}
                    </p>
                  </div>
                </button>
                <button
                  data-testid={`excluir-documento-${d.id}`}
                  aria-label={`Excluir ${d.title}`}
                  onClick={(e) => removeDoc(e, d.id)}
                  className="absolute right-3 top-3 text-neutral-300 hover:text-danger"
                >
                  <Trash2 size={14} />
                </button>
              </div>
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
            {/* `grid-cols-1` pelo mesmo motivo da grade de documentos acima (#182): sem ele o card
                de skill ia a 563,5px de largura numa tela de 360. */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {byCategory.get(cat)!.map((s) => (
                <button
                  key={s.skill}
                  onClick={() => navigate(`/juridico/novo?skill=${s.skill}`)}
                  className="flex h-full flex-col rounded-2xl bg-white p-4 text-left shadow-sm transition hover:shadow-md hover:ring-1 hover:ring-primary-300"
                >
                  {/* `break-words` no rótulo e no tipo de saída (#182): os dois vêm do catálogo de
                      skills e nenhum tem largura garantida — medido, saíam 187,5px além da borda.
                      A DESCRIÇÃO fica de fora de propósito: `line-clamp-3` já é `overflow: hidden`,
                      então ela RECORTA em vez de vazar. Mutante equivalente, medido: tirar
                      `break-words` só dela não muda número nenhum, e mudança que nenhuma régua vê é
                      peso morto (§5.4). */}
                  <p className="break-words text-sm font-semibold text-neutral-800">{s.label}</p>
                  <p className="mt-1 line-clamp-3 flex-1 text-xs text-neutral-500">
                    {s.description}
                  </p>
                  <p className="mt-3 break-words text-[11px] font-medium uppercase tracking-wide text-primary-600">
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
