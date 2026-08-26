import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import { takeSharedFile } from "../../lib/shareInbox";

type Result = { ok: true; id: string } | { ok: false; message: string };

/**
 * Busca o arquivo no IndexedDB e sobe para a bandeja. Não toca estado do componente — devolve um
 * `Result` para quem chamou decidir o que fazer (ver Achado 5 abaixo: mais de uma montagem do
 * StrictMode pode se inscrever na mesma promessa).
 */
async function uploadSharedFile(key: string): Promise<Result> {
  try {
    const file = await takeSharedFile(key);
    if (!file) {
      return { ok: false, message: "Não encontramos o arquivo compartilhado. Ele pode já ter sido enviado." };
    }
    const fd = new FormData();
    fd.append("file", file);
    const { data } = await api.post<{ id: string }>("/payables/receipts", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return { ok: true, id: data.id };
  } catch (err) {
    return { ok: false, message: apiErrorMessage(err) };
  }
}

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
 *
 * Achado 5 (#226): `startedFor` respondia DUAS perguntas diferentes com uma variável só — "já
 * comecei a buscar essa chave?" (precisa sobreviver entre montagens, senão duplica o upload) e
 * "esta execução do efeito foi cancelada?" (é por-execução). A 2ª montagem do StrictMode via que
 * `startedFor` já batia com o token e retornava ANTES de sequer se inscrever para saber o
 * resultado — então quando a 1ª montagem era cancelada pela limpeza do StrictMode, ninguém mais
 * vivo chamava `setError`/navegava, e o spinner ficava preso para sempre. A correção: o token
 * ainda deduplica a REQUISIÇÃO (`pendingFor`/`pending`), mas a promessa em voo fica guardada num
 * ref e toda execução do efeito — mesmo a que não iniciou o fetch — se inscreve nela com o seu
 * próprio `cancelled` local, então a montagem que sobrevive sempre resolve o estado.
 */
export default function CompartilharPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const pendingFor = useRef<string | null>(null);
  const pending = useRef<Promise<Result> | null>(null);

  const key = params.get("k");
  const swError = params.get("erro");

  useEffect(() => {
    let cancelled = false;

    if (swError) {
      setError("Não conseguimos receber o arquivo compartilhado. Tente de novo.");
      return;
    }
    if (!key) {
      setError("Não encontramos o arquivo compartilhado.");
      return;
    }

    // StrictMode monta duas vezes com os mesmos parâmetros — o token evita DUPLICAR o
    // upload nessa segunda montagem, reaproveitando a promessa já em voo. Mas se `key`
    // mudar (SW navegando a mesma janela para uma chave nova, sem reload), o token muda e
    // um novo upload é iniciado.
    const token = `k=${key}`;
    if (pendingFor.current !== token || !pending.current) {
      pendingFor.current = token;
      pending.current = uploadSharedFile(key);
    }

    // Toda execução do efeito se inscreve no resultado — inclusive a que NÃO iniciou o
    // upload — para que a montagem que sobrevive ao StrictMode sempre resolva o estado
    // (setError ou navigate), mesmo quando a montagem que começou o fetch foi cancelada.
    pending.current.then((result) => {
      if (cancelled) return;
      if (result.ok) {
        navigate(`/comprovante/${result.id}`, { replace: true });
      } else {
        setError(result.message);
      }
    });

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
