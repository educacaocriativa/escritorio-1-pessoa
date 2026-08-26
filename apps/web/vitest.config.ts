import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { GuardaTimeoutTeste } from "./src/test/guardaTimeoutTeste";

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
    // Fuso fixo para que testes sensíveis a data (ex.: ComprovantePage) sejam determinísticos em
    // qualquer máquina/CI, não só em fusos "atrás" de UTC como o do Brasil.
    env: { TZ: "America/Sao_Paulo" },
    // Histórico (issue #231): o default de 5000ms causava flakes (PlatformUsers.test.tsx,
    // ContractBuilderPage.test.tsx) só sob a suíte completa em paralelo — isolados, ambos
    // passavam dentro do default. A causa real era `userEvent.type()` sem `delay: null` fazendo
    // um `setTimeout` REAL por tecla (ver os dois arquivos); corrigida nos testes, não aqui.
    // 15000ms FICA como está — não é para onde subir de novo se a suíte voltar a ficar perto do
    // teto (ver `GuardaTimeoutTeste` abaixo, que agora avisa cedo em vez de deixar a folga se
    // esgotar em silêncio de novo).
    testTimeout: 15000,
    reporters: ["default", new GuardaTimeoutTeste()],
  },
});
