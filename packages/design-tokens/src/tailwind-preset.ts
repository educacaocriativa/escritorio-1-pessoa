/**
 * Preset Tailwind do e1p. Importado por apps/web/tailwind.config.ts e (futuramente) pela mobile.
 * Mantém um único vocabulário visual em todos os apps.
 */
import { colors, radii, typography } from "./index";

const preset = {
  theme: {
    extend: {
      colors: {
        primary: colors.primary,
        accent: colors.accent,
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
