import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Config dedicada de testes (Story 7.3). Mantida SEPARADA de `vite.config.ts` para que o
// build de produção (nginx estático) fique inalterado — o Vitest prefere `vitest.config.ts`
// automaticamente. O plugin `react()` habilita JSX/TSX nos testes de componente; o ambiente
// `jsdom` global dá `document`/`window` a TODA a suíte (os 9 testes de lógica pura existentes
// não dependem de nada `node`-específico que o jsdom não ofereça).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: false, // testes importam { describe, it, expect, vi } de "vitest" (padrão do projeto)
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
