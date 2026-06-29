import type { PublicContract } from "@e1p/shared-types";
import { CheckCircle2, PenLine } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiErrorMessage, publicApi } from "../../lib/api";

/** Página pública de assinatura (cliente abre o link, sem login). */
export default function PublicContractPage() {
  const { slug = "" } = useParams();
  const [contract, setContract] = useState<PublicContract | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [document, setDocument] = useState("");
  const [accept, setAccept] = useState(false);
  const [signing, setSigning] = useState(false);
  const [signedAt, setSignedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await publicApi.get<PublicContract>(`/public/contracts/${slug}`);
      setContract(data);
      setSignedAt(data.signed_at);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  async function sign() {
    setError(null);
    setSigning(true);
    try {
      const { data } = await publicApi.post<{ signed_at: string }>(
        `/public/contracts/${slug}/sign`,
        { name, document, accept: true },
      );
      setSignedAt(data.signed_at);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSigning(false);
    }
  }

  if (loading) return <Centered>Carregando contrato...</Centered>;
  if (error && !contract) return <Centered>{error}</Centered>;
  if (!contract) return <Centered>Contrato indisponível.</Centered>;

  const done = contract.status === "signed" || !!signedAt;

  return (
    <div className="min-h-screen bg-neutral-100 py-8">
      <div className="mx-auto max-w-2xl space-y-4 px-4">
        <div className="rounded-2xl bg-white p-8 shadow-card">
          <p className="text-xs uppercase tracking-wide text-neutral-400">{contract.company_name}</p>
          <h1 className="mb-6 text-2xl font-bold text-neutral-800">{contract.title}</h1>
          <div className="space-y-4">
            {contract.clauses.map((c, i) => (
              <div key={i}>
                {c.title && (
                  <h2 className="text-sm font-bold uppercase tracking-wide text-neutral-500">
                    {i + 1}. {c.title}
                  </h2>
                )}
                <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-neutral-700">
                  {c.text}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Assinatura */}
        <div className="rounded-2xl bg-white p-6 shadow-card">
          {done ? (
            <div className="flex items-center gap-3 text-accent-600">
              <CheckCircle2 size={22} />
              <div>
                <p className="font-semibold">Contrato assinado</p>
                {(contract.signer_name || name) && (
                  <p className="text-sm text-neutral-500">
                    por {contract.signer_name || name}
                    {signedAt && ` · ${new Date(signedAt).toLocaleString("pt-BR")}`}
                  </p>
                )}
              </div>
            </div>
          ) : contract.status === "cancelled" ? (
            <p className="text-sm text-danger">Este contrato foi cancelado.</p>
          ) : (
            <>
              <div className="mb-3 flex items-center gap-2 text-neutral-700">
                <PenLine size={18} /> <span className="font-semibold">Assinar contrato</span>
              </div>
              <div className="space-y-3">
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nome completo" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
                <input value={document} onChange={(e) => setDocument(e.target.value)} placeholder="CPF ou CNPJ" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
                <label className="flex items-start gap-2 text-sm text-neutral-600">
                  <input type="checkbox" checked={accept} onChange={(e) => setAccept(e.target.checked)} className="mt-0.5 h-4 w-4 accent-primary-500" />
                  Li e concordo com os termos deste contrato, e reconheço esta assinatura eletrônica
                  como válida.
                </label>
                {error && <p className="text-sm text-danger">{error}</p>}
                <button
                  onClick={sign}
                  disabled={signing || !accept || name.trim().length < 2 || document.trim().length < 3}
                  className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
                >
                  {signing ? "Assinando..." : "Assinar eletronicamente"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 p-4 text-neutral-500">
      {children}
    </div>
  );
}
