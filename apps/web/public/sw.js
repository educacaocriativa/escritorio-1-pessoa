/**
 * Service worker MÍNIMO — existe por um motivo só: o share sheet do Android entrega o
 * arquivo via POST, e uma SPA não tem como receber um POST sem interceptá-lo aqui.
 *
 * NÃO faz cache de NADA. Sem precache, sem runtime caching, sem Workbox. Isso elimina por
 * construção a classe de bugs "deploy novo no ar, mas o celular mostra a versão velha" —
 * o principal risco de introduzir PWA num app servido estaticamente por nginx.
 *
 * DB_NAME/STORE devem casar com src/lib/shareInbox.ts.
 */
const DB_NAME = "e1p-share";
const STORE = "files";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function put(key, file) {
  const db = await openDb();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(file, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Só o POST do share target é interceptado. Todo o resto vai direto à rede.
  if (event.request.method !== "POST" || url.pathname !== "/compartilhar") return;

  event.respondWith(
    (async () => {
      try {
        const form = await event.request.formData();
        const file = form.get("file");
        if (!file) return Response.redirect("/compartilhar?erro=sem-arquivo", 303);
        const key = crypto.randomUUID();
        await put(key, file);
        return Response.redirect(`/compartilhar?k=${key}`, 303);
      } catch {
        return Response.redirect("/compartilhar?erro=falha", 303);
      }
    })(),
  );
});
