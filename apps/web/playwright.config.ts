import { defineConfig, devices } from "@playwright/test";

/**
 * Gate de LAYOUT, não suíte de integração.
 *
 * Sobe só o Vite; a API é interceptada por `page.route` (ver `e2e/support/api.ts`). Sem backend,
 * sem Docker, sem banco — foi por achar que medir custava caro que seis telas subiram sem medição
 * e três PRs de correção em campo foram pagos (#56, #58, #89).
 *
 * Porta 5273, não 5173: a 5173 colide com outro projeto nas máquinas de desenvolvimento. Sempre
 * `127.0.0.1` — `localhost` resolve para ::1 em algumas delas e o Vite não atende ali.
 *
 * ⚠️ **E a 5273 colide entre WORKTREES do próprio e1p** (#123). Duas sessões no mesmo repo, uma por
 * worktree, disputam esta porta — e com `reuseExistingServer` o Playwright REUSA o Vite do outro
 * checkout e mede **o código do outro branch**, sem dizer nada. Medido em 18/08/2026: 35 dos 41
 * testes vermelhos contra um servidor que não era deste checkout, com `getByTestId` "não
 * encontrado" para um `data-testid` escrito no arquivo. O modo de falha OPOSTO — verde contra o
 * código alheio — é indistinguível de aprovação, e por isso `reuseExistingServer` é `false`
 * sempre: porta ocupada passa a ser erro alto ("port is already used") em vez de medição falsa.
 * Para rodar duas worktrees ao mesmo tempo: `E2E_PORT=5373 pnpm e2e`.
 */
const PORTA = Number(process.env.E2E_PORT ?? 5273);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  // O `html` no CI NÃO é enfeite: sem ele o diretório `playwright-report/` nunca é criado, e o
  // passo `upload-artifact` do ci.yml — que aponta para exatamente esse caminho — subia NADA. O
  // sintoma só aparece quando o gate quebra: o job fica vermelho, o artefato prometido não existe,
  // e quem for investigar não tem screenshot, nem trace, nem error-context. Medido em 18/08/2026
  // num flake real do `agenda-evento-360`: `runs/32200297688/artifacts` devolveu lista VAZIA.
  // `open: "never"` porque runner não tem navegador para abrir. O reporter HTML EMBUTE os anexos
  // (screenshot/trace) que o `use` abaixo já gerava em `test-results/` e que ninguém publicava.
  reporter: process.env.CI
    ? [["github"], ["list"], ["html", { open: "never" }]]
    : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORTA}`,
    locale: "pt-BR",
    timezoneId: "America/Sao_Paulo",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      // O aparelho de referência da dívida: 360px de largura é o piso que o produto declara
      // atender, e é onde o dono lê o WhatsApp de manhã.
      name: "360px",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 360, height: 740 },
        deviceScaleFactor: 2,
        isMobile: false,
      },
    },
  ],
  webServer: {
    command: `pnpm vite --port ${PORTA} --host 127.0.0.1`,
    url: `http://127.0.0.1:${PORTA}`,
    // `false` inclusive fora do CI — ver o ⚠️ do cabeçalho: reusar o servidor de outra worktree é
    // medir o branch errado em silêncio.
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
