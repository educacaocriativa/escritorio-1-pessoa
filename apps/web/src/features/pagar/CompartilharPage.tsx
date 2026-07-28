import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import { takeSharedFile } from "../../lib/shareInbox";

/**
 * Rota de trânsito do Web Share Target. Sem UI própria além do spinner: o service worker
 * redireciona para cá com `?k=<chave>`, nós pegamos o arquivo do IndexedDB, subimos para a
 * bandeja e seguimos para a tela de vinculação.
 *
 * Os dois caminhos de erro são tratados explicitamente — chave perdida (recarregou a página)
 * e falha do SW — porque a alternativa é uma tela em branco logo depois de um compartilhamento,
 * que parece bug do app.
 *
 * Duas garantias adicionais (achadas em revisão):
 * - `takeSharedFile` também pode REJEITAR (erro de IndexedDB), não só resolver `null` — por isso
 *   ele roda dentro do mesmo try/catch do upload, e não isolado antes dele.
 * - o guard de StrictMode é por combinação de parâmetros (`token`), não um booleano permanente:
 *   se o SW navegar a mesma janela para uma nova chave sem reload de documento, o efeito deve
 *   processar o novo compartilhamento normalmente. Um `cancelled` de escopo por execução garante
 *   que uma promessa antiga (de uma chave/tela já abandonada) nunca chame `setError`/`navigate`
 *   depois que o efeito foi limpo.
 */
export default function CompartilharPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const startedFor = useRef<string | null>(null);

  const key = params.get("k");
  const swError = params.get("erro");

  useEffect(() => {
    let cancelled = false;

    // StrictMode monta duas vezes com os mesmos parâmetros — o token evita reprocessar o mesmo
    // compartilhamento nessa segunda montagem. Mas se `key`/`swError` mudarem (SW navegando a
    // mesma janela para uma chave nova, sem reload), o token muda e o efeito processa de novo.
    const token = `k=${key ?? ""}|erro=${swError ?? ""}`;
    if (startedFor.current === token) return;
    startedFor.current = token;

    if (swError) {
      setError("Não conseguimos receber o arquivo compartilhado. Tente de novo.");
      return;
    }
    if (!key) {
      setError("Não encontramos o arquivo compartilhado.");
      return;
    }

    (async () => {
      try {
        const file = await takeSharedFile(key);
        if (cancelled) return;
        if (!file) {
          setError("Não encontramos o arquivo compartilhado. Ele pode já ter sido enviado.");
          return;
        }
        const fd = new FormData();
        fd.append("file", file);
        const { data } = await api.post<{ id: string }>("/payables/receipts", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        if (cancelled) return;
        navigate(`/comprovante/${data.id}`, { replace: true });
      } catch (err) {
        if (cancelled) return;
        setError(apiErrorMessage(err));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [key, swError, navigate]);

  if (error) {
    return (
      <div className="mx-auto max-w-md space-y-3 p-6 text-center">
        <p className="text-sm text-neutral-600">{error}</p>
        <Link to="/pagar" className="inline-block text-sm font-semibold text-primary-600">
          Ir para Contas a pagar
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-64 items-center justify-center text-sm text-neutral-500">
      Enviando comprovante...
    </div>
  );
}
