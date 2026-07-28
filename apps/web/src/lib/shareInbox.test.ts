// Este teste não usa DOM nenhum — só IndexedDB (via fake-indexeddb) + File. Roda em ambiente
// "node" (em vez do "jsdom" global do projeto) de propósito: o `File` do jsdom não sobrevive
// ao `structuredClone` nativo que o fake-indexeddb usa para clonar valores na gravação (vira
// objeto vazio, sem nome/tipo/conteúdo) — é uma lacuna de interoperabilidade jsdom↔Node, não um
// bug do shareInbox.ts. Sob "node", `File` é o global nativo, que clona corretamente
// (confirmado manualmente: `structuredClone(new File(...))` preserva name/type/conteúdo).
// @vitest-environment node
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
