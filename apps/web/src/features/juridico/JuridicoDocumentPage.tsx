import type { LegalDocument } from "@e1p/shared-types";
import { ArrowLeft, Check, Copy, Download, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../lib/api";

export default function JuridicoDocumentPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<LegalDocument | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.get<LegalDocument>(`/juridico/documents/${id}`).then(({ data }) => setDoc(data));
  }, [id]);

  async function copy() {
    if (!doc) return;
    await navigator.clipboard.writeText(doc.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function downloadDocx() {
    const { data } = await api.get(`/juridico/documents/${id}/docx`, { responseType: "blob" });
    const url = URL.createObjectURL(data as Blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${doc?.title ?? "documento"}.docx`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (!doc) return <p className="text-sm text-neutral-500">Carregando…</p>;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <button
        onClick={() => navigate("/juridico")}
        className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
      >
        <ArrowLeft size={16} /> Voltar ao Assistente
      </button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-neutral-500">Jurídico / Documento</p>
          <h1 className="text-2xl font-bold text-neutral-800">{doc.title}</h1>
          <p className="mt-1 text-xs text-neutral-400">
            {doc.client_name ? `Cliente: ${doc.client_name} · ` : ""}
            {doc.output_tokens > 0 ? `${doc.output_tokens} tokens gerados` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={copy}
            className="flex items-center gap-1.5 rounded-lg border border-neutral-200 px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-50"
          >
            {copied ? <Check size={15} /> : <Copy size={15} />}
            {copied ? "Copiado" : "Copiar"}
          </button>
          <button
            onClick={downloadDocx}
            className="flex items-center gap-1.5 rounded-lg bg-primary-500 px-3 py-2 text-sm font-medium text-white hover:bg-primary-600"
          >
            <Download size={15} /> Word (.docx)
          </button>
        </div>
      </div>

      {doc.status === "failed" ? (
        <div className="rounded-2xl bg-warning/10 p-5 text-sm text-neutral-700">{doc.content}</div>
      ) : (
        <article className="whitespace-pre-wrap rounded-2xl bg-white p-6 text-sm leading-relaxed text-neutral-800 shadow-sm">
          {doc.content}
        </article>
      )}

      {doc.metadata_raw && (
        <details className="rounded-2xl bg-neutral-50 p-4 text-sm text-neutral-600">
          <summary className="flex cursor-pointer items-center gap-1.5 font-medium text-neutral-700">
            <FileText size={15} /> Metadados & avisos de revisão
          </summary>
          <pre className="mt-3 whitespace-pre-wrap font-sans text-xs text-neutral-500">
            {doc.metadata_raw}
          </pre>
        </details>
      )}
    </div>
  );
}
