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
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5273",
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
    command: "pnpm vite --port 5273 --host 127.0.0.1",
    url: "http://127.0.0.1:5273",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
