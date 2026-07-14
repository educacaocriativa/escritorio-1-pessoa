/**
 * Preset Tailwind do e1p. Importado por apps/web/tailwind.config.ts e (futuramente) pela mobile.
 * Mantém um único vocabulário visual em todos os apps.
 */
import { cssVarName, type ShadeKey } from "./colorScale";
import { colors, radii, typography } from "./index";

/**
 * `primary`/`accent` viram `var(--e1p-{token}-{tom}, <hex estático>)` — o fallback garante que,
 * sem nenhum tema de tenant aplicado (JS ainda não rodou, ou Brand Kit nunca customizado), a
 * aparência é IDÊNTICA à de hoje (mesmos hex fixos). Quando `apps/web/src/lib/theme.ts` seta as
 * CSS vars a partir do Brand Kit do tenant, essas classes passam a refletir a cor da marca sem
 * precisar recompilar o Tailwind — só `neutral`/`success`/`warning`/`danger`/`info` continuam
 * 100% estáticos (cores semânticas fixas: erro/sucesso não devem seguir a marca do tenant).
 */
function withCssVarFallback(
  token: "primary" | "accent",
  scale: Record<ShadeKey, string>,
): Record<ShadeKey, string> {
  const out = {} as Record<ShadeKey, string>;
  for (const shade of Object.keys(scale).map(Number) as ShadeKey[]) {
    out[shade] = `var(${cssVarName(token, shade)}, ${scale[shade]})`;
  }
  return out;
}

const preset = {
  theme: {
    extend: {
      colors: {
        primary: withCssVarFallback("primary", colors.primary),
        accent: withCssVarFallback("accent", colors.accent),
        neutral: colors.neutral,
        success: colors.success,
        warning: colors.warning,
        danger: colors.danger,
        info: colors.info,
      },
      borderRadius: {
        DEFAULT: radii.md,
        pill: radii.pill,
      },
      fontFamily: {
        sans: typography.fontFamily.sans,
      },
    },
  },
};

export default preset;
