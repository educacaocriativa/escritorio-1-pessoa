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
 */
export default function CompartilharPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const key = params.get("k");
  const swError = params.get("erro");

  useEffect(() => {
    if (started.current) return; // StrictMode monta duas vezes; o consumo da chave é único
    started.current = true;

    if (swError) {
      setError("Não conseguimos receber o arquivo compartilhado. Tente de novo.");
      return;
    }
    if (!key) {
      setError("Não encontramos o arquivo compartilhado.");
      return;
    }

    (async () => {
      const file = await takeSharedFile(key);
      if (!file) {
        setError("Não encontramos o arquivo compartilhado. Ele pode já ter sido enviado.");
        return;
      }
      try {
        const fd = new FormData();
        fd.append("file", file);
        const { data } = await api.post<{ id: string }>("/payables/receipts", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        navigate(`/comprovante/${data.id}`, { replace: true });
      } catch (err) {
        setError(apiErrorMessage(err));
      }
    })();
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
