// Este teste não usa DOM nenhum — só IndexedDB (via fake-indexeddb) + File. Roda em ambiente
// "node" (em vez do "jsdom" global do projeto) de propósito: o `File` do jsdom não sobrevive
// ao `structuredClone` nativo que o fake-indexeddb usa para clonar valores na gravação (vira
// objeto vazio, sem nome/tipo/conteúdo) — é uma lacuna de interoperabilidade jsdom↔Node, não um
// bug do shareInbox.ts. Sob "node", `File` é o global nativo, que clona corretamente
// (confirmado manualmente: `structuredClone(new File(...))` preserva name/type/conteúdo).
// @vitest-environment node
import { readFileSync } from "node:fs";
import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import { SHARE_DB_NAME, SHARE_STORE, takeSharedFile } from "./shareInbox";

/** Grava direto no IndexedDB, imitando o que o service worker faz no POST do share target. */
async function seed(key: string, file: File): Promise<void> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(SHARE_DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(SHARE_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(SHARE_STORE, "readwrite");
    tx.objectStore(SHARE_STORE).put(file, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

describe("shareInbox", () => {
  it("devolve o arquivo gravado e apaga a chave depois de ler", async () => {
    const file = new File(["conteudo"], "comprovante.pdf", { type: "application/pdf" });
    await seed("k1", file);

    const lido = await takeSharedFile("k1");
    expect(lido?.name).toBe("comprovante.pdf");
    expect(lido?.type).toBe("application/pdf");

    // consumo único: a segunda leitura não encontra mais nada
    expect(await takeSharedFile("k1")).toBeNull();
  });

  it("devolve null para chave inexistente em vez de lançar", async () => {
    expect(await takeSharedFile("nao-existe")).toBeNull();
  });
});

/**
 * Um limite de tempo, para separar "resolveu/rejeitou" de "PENDUROU".
 *
 * Achado por mutação (#214): três handlers deste arquivo (`onerror` do open, `onerror` do get,
 * `onerror` da transação de apagar) existem só para TERMINAR a promessa. Esvaziar qualquer um
 * deles não produz erro nenhum — produz uma promessa que nunca assenta, e a rota `/compartilhar`
 * gira para sempre com o comprovante do dono dentro. Um `rejects.toThrow()` sozinho não pega
 * isso: ele espera para sempre junto. O limite é o que transforma "pendurou" em asserção.
 */
const PENDUROU = Symbol("pendurou");
function comLimite<T>(p: Promise<T>, ms = 500): Promise<T | typeof PENDUROU> {
  let t: ReturnType<typeof setTimeout>;
  return Promise.race([
    p.finally(() => clearTimeout(t)),
    new Promise<typeof PENDUROU>((r) => {
      t = setTimeout(() => r(PENDUROU), ms);
    }),
  ]);
}

type Fase = "open" | "get" | "delete";
type Handler = ((e: unknown) => void) | undefined;

/**
 * Um `indexedDB` de mentira que falha numa fase escolhida. O `fake-indexeddb` implementa o
 * caminho FELIZ com fidelidade, mas não oferece gatilho para forçar `onerror` — e é justamente o
 * caminho de erro que não tinha prova nenhuma.
 */
function indexedDbQueFalhaEm(fase: Fase, arquivo: File): IDBFactory {
  const dispararDepois = (alvo: Record<string, unknown>, nome: string) => {
    setTimeout(() => (alvo[nome] as Handler)?.({}), 0);
  };
  return {
    open() {
      const req: Record<string, unknown> = {
        result: null,
        error: new Error("falha simulada em " + fase),
      };
      setTimeout(() => {
        if (fase === "open") {
          dispararDepois(req, "onerror");
          return;
        }
        req.result = {
          close: () => {},
          transaction: (_lojas: string, modo: string) => {
            const tx: Record<string, unknown> = {
              objectStore: () => ({
                get: () => {
                  const r: Record<string, unknown> = {
                    result: undefined,
                    error: new Error("falha simulada no get"),
                  };
                  setTimeout(() => {
                    if (fase === "get") {
                      (r.onerror as Handler)?.({});
                      return;
                    }
                    r.result = arquivo;
                    (r.onsuccess as Handler)?.({});
                  }, 0);
                  return r;
                },
                delete: () => {},
              }),
            };
            if (modo === "readwrite") {
              dispararDepois(tx, fase === "delete" ? "onerror" : "oncomplete");
            }
            return tx;
          },
        };
        (req.onsuccess as Handler)?.({});
      }, 0);
      return req;
    },
  } as unknown as IDBFactory;
}

async function comIndexedDbFalho<T>(fase: Fase, arquivo: File, fn: () => Promise<T>): Promise<T> {
  const real = globalThis.indexedDB;
  globalThis.indexedDB = indexedDbQueFalhaEm(fase, arquivo);
  try {
    return await fn();
  } finally {
    globalThis.indexedDB = real;
  }
}

/**
 * Um `indexedDB` de mentira em que o banco AINDA NÃO EXISTE: o `open` dispara
 * `onupgradeneeded` antes do `onsuccess`, e a transação só funciona se o store tiver sido
 * criado ali. É de mentira, e não um `deleteDatabase` no `fake-indexeddb` real, porque um
 * `deleteDatabase` bloqueado por conexão vazada fica ENFILEIRADO e trava todo `open` seguinte
 * do arquivo — o que trocaria a asserção deste teste por um `Test timed out` de 15s em todos.
 */
function indexedDbComBancoNovo(): IDBFactory {
  return {
    open() {
      const req: Record<string, unknown> = { result: null, error: null };
      let temStore = false;
      setTimeout(() => {
        req.result = {
          createObjectStore: (nome: string) => {
            temStore = nome === SHARE_STORE;
          },
          close: () => {},
          transaction: (lojas: string) => {
            if (!temStore) {
              throw new DOMException(`No objectStore named ${lojas}`, "NotFoundError");
            }
            return {
              objectStore: () => ({
                get: () => {
                  const r: Record<string, unknown> = { result: undefined };
                  setTimeout(() => (r.onsuccess as Handler)?.({}), 0);
                  return r;
                },
              }),
            };
          },
        };
        (req.onupgradeneeded as Handler)?.({});
        (req.onsuccess as Handler)?.({});
      }, 0);
      return req;
    },
  } as unknown as IDBFactory;
}

describe("shareInbox — os caminhos que só a mutação cobrava (#214)", () => {
  it("cria o object store quando o banco ainda NÃO existe", async () => {
    // Esvaziar o `onupgradeneeded` do `openDb` sobrevivia porque o `seed()` acima (que imita o
    // service worker) cria o store ANTES, e aí `openDb` só encontra banco pronto. Na vida real a
    // ordem pode ser a inversa — o app abre /compartilhar num navegador onde o SW ainda não
    // gravou nada — e sem o store a leitura estoura NotFoundError em vez de devolver `null`.
    const real = globalThis.indexedDB;
    globalThis.indexedDB = indexedDbComBancoNovo();
    try {
      await expect(comLimite(takeSharedFile("qualquer"))).resolves.toBeNull();
    } finally {
      globalThis.indexedDB = real;
    }
  });

  it("o banco que não ABRE vira null — e não uma promessa pendurada", async () => {
    const r = await comIndexedDbFalho("open", new File([""], "n.pdf"), () =>
      comLimite(takeSharedFile("k")),
    );

    expect(r).toBeNull();
  });

  it("a LEITURA que falha rejeita — e não uma promessa pendurada", async () => {
    const r = await comIndexedDbFalho("get", new File([""], "n.pdf"), () =>
      comLimite(
        takeSharedFile("k")
          .then(() => "resolveu" as const)
          .catch(() => "rejeitou" as const),
      ),
    );

    expect(r).toBe("rejeitou");
  });

  it("apagar é best-effort: a transação que FALHA ainda entrega o arquivo", async () => {
    // A produção promete, em comentário, "apagar é best-effort; o arquivo já foi entregue". Sem
    // este teste, esvaziar o `tx.onerror` transformava a promessa da ENTREGA numa que nunca
    // assenta: o dono perde o comprovante em vez de perder só a limpeza da chave.
    const arquivo = new File(["c"], "comprovante.pdf", { type: "application/pdf" });

    const r = await comIndexedDbFalho("delete", arquivo, () => comLimite(takeSharedFile("k")));

    expect(r).not.toBe(PENDUROU);
    expect((r as File | null)?.name).toBe("comprovante.pdf");
  });

  it("chave inexistente NÃO abre transação de escrita", async () => {
    // Fixar `if (file)` em `true` devolve o mesmo `null`, porque apagar chave que não existe é um
    // no-op silencioso. O que muda é o MODO da transação: toda leitura vazia passaria a tomar o
    // lock de escrita do store. E leitura vazia é o caso COMUM — é o que acontece a cada
    // recarregar/voltar em /compartilhar.
    const modos: string[] = [];
    const original = IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction = function (
      this: IDBDatabase,
      lojas: string | string[],
      modo?: IDBTransactionMode,
    ) {
      modos.push(modo ?? "readonly");
      return original.call(this, lojas, modo);
    };
    try {
      await seed("k-modo", new File(["x"], "x.pdf"));
      modos.length = 0;
      expect(await takeSharedFile("nao-existe-mesmo")).toBeNull();
    } finally {
      IDBDatabase.prototype.transaction = original;
    }

    expect(modos).toEqual(["readonly"]);
  });

  // ÚLTIMO do arquivo de propósito: é o único que deixa o banco APAGADO, e sob o mutante que
  // vaza a conexão ele deixa um `deleteDatabase` pendurado para sempre.
  it("FECHA a conexão: a conexão vazada trava a próxima migração do banco", async () => {
    // Apagar o `finally { db.close() }` (ou só a chamada dentro dele) não quebra nada visível — a
    // leitura devolve o arquivo do mesmo jeito. O que vaza é a CONEXÃO, e conexão aberta bloqueia
    // qualquer `versionchange` futuro. Este arquivo e o `sw.js` compartilham o banco de propósito
    // ("Mantenha DB_NAME/STORE em sincronia"): a primeira migração travaria em `onblocked`.
    await seed("k-fecha", new File(["x"], "x.pdf", { type: "application/pdf" }));
    expect(await takeSharedFile("k-fecha")).not.toBeNull();

    const eventos: string[] = [];
    const apagou = new Promise<void>((resolve, reject) => {
      const req = indexedDB.deleteDatabase(SHARE_DB_NAME);
      req.onblocked = () => eventos.push("blocked");
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });

    const r = await comLimite(apagou);

    expect(eventos).toEqual([]);
    expect(r).not.toBe(PENDUROU);
  });
});

describe("o contrato com o service worker (#214)", () => {
  it("DB_NAME e STORE são os MESMOS de public/sw.js", () => {
    // O cabeçalho de `shareInbox.ts` manda: "Mantenha DB_NAME/STORE em sincronia com public/sw.js
    // — são o mesmo banco". Nada verificava isso. Achado por mutação (#214): zerar qualquer um
    // dos dois literais sobrevive à suíte INTEIRA, `CompartilharPage.test.tsx` incluído, porque
    // todo consumidor dentro do `src/` (e o próprio `seed()` deste arquivo) lê a constante
    // exportada — a mentira é consistente consigo mesma. Quem grava do outro lado é o `sw.js`,
    // um arquivo fora do `src/` que nenhum teste importa, e ele tem os nomes cravados. Sob a
    // divergência, o share do Android grava num banco e a rota /compartilhar lê de outro: o
    // comprovante do dono some sem erro nenhum na tela.
    const sw = readFileSync(new URL("../../public/sw.js", import.meta.url), "utf8");

    expect(sw).toContain(`const DB_NAME = "${SHARE_DB_NAME}";`);
    expect(sw).toContain(`const STORE = "${SHARE_STORE}";`);
  });
});
