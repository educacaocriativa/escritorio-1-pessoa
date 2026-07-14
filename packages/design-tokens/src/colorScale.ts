/**
 * Gera uma escala de 10 tons (50→900) a partir de UMA cor base (hex) — usada para derivar o tema
 * do app a partir do Brand Kit do tenant (uma única cor "primária"/"destaque" configurada em
 * Configurações), preservando a mesma "forma" (curva de luminosidade/saturação) das escalas
 * estáticas do design system (ver `colors.primary`/`colors.accent` em index.ts).
 *
 * O tom 500 é a própria cor de entrada (verbatim — é o que o tenant escolheu); os demais tons
 * interpolam a partir do L/S reais da cor de entrada até âncoras fixas quase-branco (50) e
 * quase-preto (900), usando os MESMOS pesos relativos da curva original — isso garante uma
 * rampa sempre monotônica (nunca "invertida") não importa a luminosidade da cor escolhida.
 */

export type ShadeKey = 50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900;

export const SHADE_KEYS: readonly ShadeKey[] = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];

const LIGHT_ANCHOR_L = 96.5; // luminosidade do tom mais claro (50), fixa p/ qualquer matiz
const DARK_ANCHOR_L = 20; // luminosidade do tom mais escuro (900), fixa
const DARK_SAT_DROP = 0.35; // saturação cai até 35% no tom mais escuro (evita ficar "lamacento")

// Peso de interpolação de cada tom entre a cor base (500) e as âncoras clara/escura — extraído
// da curva de luminosidade da escala `colors.primary` original (ver index.ts), reaproveitado como
// MOLDE para qualquer matiz de marca nova.
const LIGHT_WEIGHT: Partial<Record<ShadeKey, number>> = {
  400: 0.21,
  300: 0.45,
  200: 0.74,
  100: 0.91,
  50: 1,
};
const DARK_WEIGHT: Partial<Record<ShadeKey, number>> = { 600: 0.25, 700: 0.52, 800: 0.79, 900: 1 };

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function hexToHsl(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16) / 255;
  const g = parseInt(clean.slice(2, 4), 16) / 255;
  const b = parseInt(clean.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l * 100];
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  switch (max) {
    case r:
      h = (g - b) / d + (g < b ? 6 : 0);
      break;
    case g:
      h = (b - r) / d + 2;
      break;
    default:
      h = (r - g) / d + 4;
  }
  return [h * 60, s * 100, l * 100];
}

function hslToHex(h: number, s: number, l: number): string {
  const sN = s / 100;
  const lN = l / 100;
  const c = (1 - Math.abs(2 * lN - 1)) * sN;
  const hp = ((h % 360) + 360) % 360 / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  const m = lN - c / 2;
  let [r1, g1, b1] = [0, 0, 0];
  if (hp < 1) [r1, g1, b1] = [c, x, 0];
  else if (hp < 2) [r1, g1, b1] = [x, c, 0];
  else if (hp < 3) [r1, g1, b1] = [0, c, x];
  else if (hp < 4) [r1, g1, b1] = [0, x, c];
  else if (hp < 5) [r1, g1, b1] = [x, 0, c];
  else [r1, g1, b1] = [c, 0, x];
  const toHex = (v: number) =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${toHex(r1)}${toHex(g1)}${toHex(b1)}`;
}

/** Nome da CSS custom property de um tom — fonte única usada tanto pelo preset Tailwind (fallback
 * estático) quanto pelo injetor de tema em runtime (apps/web/src/lib/theme.ts), para os dois
 * lados nunca divergirem no nome da variável. */
export function cssVarName(token: "primary" | "accent", shade: ShadeKey): string {
  return `--e1p-${token}-${shade}`;
}

/** Gera as 10 tonalidades a partir de uma cor base hex (ex.: "#5D44F8"). */
export function generateScale(baseHex: string): Record<ShadeKey, string> {
  const [hue, sat, light] = hexToHsl(baseHex);
  const lightSpan = Math.max(0, LIGHT_ANCHOR_L - light);
  const darkSpan = Math.max(0, light - DARK_ANCHOR_L);
  const scale = {} as Record<ShadeKey, string>;
  for (const shade of SHADE_KEYS) {
    if (shade === 500) {
      scale[shade] = baseHex.toLowerCase();
      continue;
    }
    const lightWeight = LIGHT_WEIGHT[shade];
    if (lightWeight !== undefined) {
      scale[shade] = hslToHex(hue, sat, clamp(light + lightWeight * lightSpan, 0, 100));
    } else {
      const darkWeight = DARK_WEIGHT[shade] as number;
      scale[shade] = hslToHex(
        hue,
        clamp(sat * (1 - darkWeight * DARK_SAT_DROP), 0, 100),
        clamp(light - darkWeight * darkSpan, 0, 100),
      );
    }
  }
  return scale;
}
