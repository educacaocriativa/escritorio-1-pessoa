import { cssVarName, generateScale, SHADE_KEYS } from "@e1p/design-tokens";

/** Só os dois campos do Brand Kit (Configurações) que viram tema — cores semânticas
 * (sucesso/erro/aviso) e neutros continuam fixos de propósito, nunca seguem a marca do tenant. */
export interface BrandColors {
  primary_color: string;
  accent_color: string;
}

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

/**
 * Aplica o Brand Kit do tenant como CSS custom properties no `<html>` — as classes Tailwind
 * `bg-primary-*`/`text-accent-*` etc. já apontam para `var(--e1p-primary-*, <fallback>)` (ver
 * `packages/design-tokens/src/tailwind-preset.ts`), então isto é o suficiente para o tema do
 * app inteiro (sidebar, botões, links) refletir a cor da marca — sem recompilar nada.
 *
 * Hex inválido/vazio é ignorado silenciosamente por campo (fail-safe: mantém o fallback estático
 * do preset em vez de quebrar o tema inteiro por um valor ruim).
 */
export function applyBrandTheme(brand: Partial<BrandColors>): void {
  const root = document.documentElement;
  for (const [token, hex] of [
    ["primary", brand.primary_color],
    ["accent", brand.accent_color],
  ] as const) {
    if (!hex || !HEX_RE.test(hex)) continue;
    const scale = generateScale(hex);
    for (const shade of SHADE_KEYS) {
      root.style.setProperty(cssVarName(token, shade), scale[shade]);
    }
  }
}
