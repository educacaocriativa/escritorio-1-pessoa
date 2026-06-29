import type { PublicProposal } from "@e1p/shared-types";
import { Lock } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiErrorMessage, publicApi } from "../../lib/api";
import ProposalView from "./ProposalView";

/** Página pública da proposta (cliente abre o link, sem login). */
export default function PublicProposalPage() {
  const { slug = "" } = useParams();
  const [proposal, setProposal] = useState<PublicProposal | null>(null);
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [accepted, setAccepted] = useState(false);

  const fetchProposal = useCallback(
    async (pwd?: string) => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await publicApi.get<PublicProposal>(`/public/proposals/${slug}`, {
          params: pwd ? { password: pwd } : undefined,
        });
        setProposal(data);
        setNeedsPassword(false);
      } catch (err) {
        const e = err as { response?: { status?: number } };
        if (e.response?.status === 401) {
          setNeedsPassword(true);
          if (pwd) setError("Senha incorreta.");
        } else if (e.response?.status === 404) {
          setError("Proposta não encontrada.");
        } else {
          setError(apiErrorMessage(err));
        }
      } finally {
        setLoading(false);
      }
    },
    [slug],
  );

  useEffect(() => {
    fetchProposal();
  }, [fetchProposal]);

  async function accept() {
    setAccepting(true);
    try {
      await publicApi.post(`/public/proposals/${slug}/accept`, {
        password: password || null,
      });
      setAccepted(true);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setAccepting(false);
    }
  }

  if (loading) {
    return <Centered>Carregando proposta...</Centered>;
  }

  if (needsPassword) {
    return (
      <Centered>
        <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-card">
          <div className="mb-3 flex items-center gap-2 text-neutral-700">
            <Lock size={18} /> <span className="font-semibold">Proposta protegida</span>
          </div>
          <p className="mb-3 text-sm text-neutral-500">Digite a senha para visualizar.</p>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fetchProposal(password)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
            placeholder="Senha do link"
          />
          {error && <p className="mt-2 text-sm text-danger">{error}</p>}
          <button
            onClick={() => fetchProposal(password)}
            className="mt-3 w-full rounded-pill bg-primary-500 py-2.5 font-semibold text-white hover:bg-primary-600"
          >
            Ver proposta
          </button>
        </div>
      </Centered>
    );
  }

  if (error || !proposal) {
    return <Centered>{error ?? "Proposta indisponível."}</Centered>;
  }

  return (
    <div className="min-h-screen w-full py-8" style={{ background: proposal.bg_color }}>
      <div className="rounded-2xl bg-white/0">
        <ProposalView p={proposal} onAccept={accept} accepting={accepting} accepted={accepted} />
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
