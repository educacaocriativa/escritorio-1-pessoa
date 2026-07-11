import type { PublicImage } from "@e1p/shared-types";
import { api } from "./api";

/** Formatos aceitos para imagem pública (espelha PUBLIC_IMAGE_TYPES no backend). */
export const PUBLIC_IMAGE_ACCEPT = "image/jpeg,image/png";

/**
 * Sobe uma imagem intencionalmente PÚBLICA (logo/foto de proposta, carrossel, site) e devolve a
 * URL renderável em `<img src>` — reusa a camada de storage do módulo de Anexos (Epic 3.5).
 *
 * O backend responde `{ id, url }` com `url` relativa à SUA árvore de rotas (`/public-images/{id}`).
 * Como o front sempre fala com a API através do proxy `/api` (Vite em dev, Caddy em prod — ambos
 * removem o prefixo), a URL que renderiza no navegador é `/api/public-images/{id}`. Prefixamos aqui
 * usando `api.defaults.baseURL` como fonte única de verdade, e o valor retornado é persistido
 * direto no campo (logo_url / gallery[].url / photo_url / block.url) — inclusive no snapshot das
 * páginas públicas, que renderizam a string crua sem token.
 */
export async function uploadPublicImage(file: File): Promise<string> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await api.post<PublicImage>("/attachments/public-images", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  const base = api.defaults.baseURL ?? "";
  return `${base}${data.url}`;
}
