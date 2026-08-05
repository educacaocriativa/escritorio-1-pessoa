/**
 * O que cada transporte de WhatsApp sabe fazer — espelho de
 * `apps/api/app/core/whatsapp/capabilities.py`.
 *
 * Template aprovado e janela de 24h são regras da Cloud API da Meta; a Evolution (Baileys) não
 * conhece nenhuma das duas. A tela precisa saber disso para não oferecer um seletor de template
 * a quem conectou por QR code — não existe template nenhum para escolher, e a lista viria vazia
 * com o botão de salvar travado (foi exatamente esse o bug no nó de WhatsApp do funil).
 *
 * Mesma regra de resolução do backend: qualquer valor diferente de "evolution" — inclusive
 * `null` (nunca conectou) — é Meta.
 */
import type { TenantProfile } from "@e1p/shared-types";

export type WhatsappCapabilities = {
  /** Exige template aprovado pela Meta fora da janela de 24h. */
  templates: boolean;
  /** Tem janela de 24h (só responde livre depois que o contato escreve). */
  sessionWindow: boolean;
};

export const META: WhatsappCapabilities = { templates: true, sessionWindow: true };
export const EVOLUTION: WhatsappCapabilities = { templates: false, sessionWindow: false };

export function capabilitiesFor(
  provider: TenantProfile["whatsapp_provider"] | undefined,
): WhatsappCapabilities {
  return provider === "evolution" ? EVOLUTION : META;
}
