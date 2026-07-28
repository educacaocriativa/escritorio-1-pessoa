/**
 * Ponte entre o service worker e o app para o Web Share Target.
 *
 * O SW recebe o POST do share sheet do Android e guarda o arquivo aqui sob uma chave
 * aleatória; a rota /compartilhar lê e apaga. O IndexedDB é o único canal possível: o SW não
 * pode entregar um File por query string nem por postMessage confiável durante o redirect.
 *
 * Mantenha DB_NAME/STORE em sincronia com public/sw.js — são o mesmo banco.
 */
export const SHARE_DB_NAME = "e1p-share";
export const SHARE_STORE = "files";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(SHARE_DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(SHARE_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Lê o arquivo compartilhado e REMOVE a chave (consumo único). null se não existir. */
export async function takeSharedFile(key: string): Promise<File | null> {
  let db: IDBDatabase;
  try {
    db = await openDb();
  } catch {
    return null;
  }
  try {
    const file = await new Promise<File | null>((resolve, reject) => {
      const tx = db.transaction(SHARE_STORE, "readonly");
      const req = tx.objectStore(SHARE_STORE).get(key);
      req.onsuccess = () => resolve((req.result as File) ?? null);
      req.onerror = () => reject(req.error);
    });
    if (file) {
      await new Promise<void>((resolve) => {
        const tx = db.transaction(SHARE_STORE, "readwrite");
        tx.objectStore(SHARE_STORE).delete(key);
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve(); // apagar é best-effort; o arquivo já foi entregue
      });
    }
    return file;
  } finally {
    db.close();
  }
}
