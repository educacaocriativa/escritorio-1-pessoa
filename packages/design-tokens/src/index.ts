/**
 * Design tokens do e1p — derivados do design Figma "Portal" (CRM UI Dashboard).
 * Fonte da verdade para cores/spacing/tipografia. NUNCA hardcode cores nos componentes:
 * importe daqui (ou use as classes Tailwind geradas pelo preset).
 */

export const colors = {
  // Primária — índigo/roxo da sidebar do "Portal"
  primary: {
    50: "#eef0ff",
    100: "#e0e2ff",
    200: "#c7caff",
    300: "#a5a8fb",
    400: "#8385f5",
    500: "#5d5fef", // base (sidebar)
    600: "#4f4fe0",
    700: "#4040c2",
    800: "#35359c",
    900: "#2f2f7a",
  },
  // Verde — acento de ações, ativos, links
  accent: {
    50: "#ecfdf3",
    100: "#d1fadf",
    200: "#a6f4c5",
    300: "#6fe8a6",
    400: "#3dd68c", // base (botões, "Add New Project")
    500: "#22c277",
    600: "#16a35f",
    700: "#13824d",
    800: "#136640",
    900: "#115437",
  },
  // Neutros — fundos, textos, bordas
  neutral: {
    0: "#ffffff",
    50: "#f5f5f7", // fundo de card
    100: "#ececef",
    200: "#dcdce1",
    300: "#c4c4cc",
    400: "#9a9aa6",
    500: "#6f6f7d",
    600: "#4c4c58",
    700: "#34343d",
    800: "#25262b", // footer escuro
    900: "#16161a",
  },
  // Estados de badge (Status/Priority/Payment no "Latest Projects")
  badge: {
    active: { bg: "#d1fadf", fg: "#136640" }, // verde
    high: { bg: "#ffe0e0", fg: "#b42318" }, // vermelho
    done: { bg: "#dbeafe", fg: "#1e4fa3" }, // azul
    inProgress: { bg: "#fef7c3", fg: "#a15c07" }, // amarelo
  },
  // Semânticos
  success: "#22c277",
  warning: "#f5a623",
  danger: "#e5484d",
  info: "#3b82f6",
} as const;

export const radii = {
  sm: "8px",
  md: "12px",
  lg: "16px",
  xl: "24px",
  pill: "9999px",
} as const;

export const spacing = {
  xs: "4px",
  sm: "8px",
  md: "16px",
  lg: "24px",
  xl: "32px",
  "2xl": "48px",
} as const;

export const typography = {
  fontFamily: {
    sans: ['"Inter"', "system-ui", "sans-serif"],
  },
} as const;

export const tokens = { colors, radii, spacing, typography } as const;
export default tokens;
