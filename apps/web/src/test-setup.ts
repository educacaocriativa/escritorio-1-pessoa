// Setup global da suíte de testes (Story 7.3), referenciado em `vitest.config.ts` (setupFiles).
// Registra os matchers de DOM do `@testing-library/jest-dom` no `expect` do Vitest
// (`.toBeInTheDocument()`, `.toHaveValue()`, etc.). Fica dentro de `src/` de propósito: como
// o `tsconfig.json` inclui `["src"]`, este import de side-effect torna a AUGMENTAÇÃO de tipos
// dos matchers visível ao `tsc --noEmit` para TODOS os testes de componente — pilotos e os das
// Stories 7.4/7.5 — sem precisar de import por arquivo nem de mudança no tsconfig.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Limpeza do DOM entre os testes. O @testing-library/react só registra o cleanup automático
// quando há um `afterEach` GLOBAL (config `globals: true`); como mantemos `globals: false`
// (padrão de imports explícitos do projeto), registramos o cleanup aqui manualmente. Sem isto,
// o DOM de um teste vaza para o próximo (ex.: `queryByText` acha um elemento do render anterior).
// Vale para TODA a suíte de componentes — Stories 7.4/7.5 herdam sem precisar repetir.
afterEach(() => {
  cleanup();
});
