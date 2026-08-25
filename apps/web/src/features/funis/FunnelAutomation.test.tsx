import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
import { AutomationFields, FunnelAutomationDrawer } from "./FunnelAutomation";

// Rede sempre mockada (IV2): usada só pelos testes da Drawer abaixo (#225) — os testes de
// AutomationFields, acima, não tocam em `api`.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Issue #224 — separador de milhar no valor digitado (parseCentsBRL)
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// A conta manual antiga (`Math.round(parseFloat(e.target.value.replace(",", ".") || "0") * 100)`)
// só troca a PRIMEIRA vírgula por ponto e nunca remove o ponto de milhar: "1.234,56" vira
// "1.234.56", `parseFloat` para no segundo ponto e devolve 1.234 → 123 centavos, não 123456.
// `parseCentsBRL` (contas.ts) trata o milhar corretamente.
//
// ⚠️ **Medido, não assumido:** este campo é um input CONTROLADO cujo `value` é sempre
// `(cfg.amount_cents / 100).toString()` — recalculado a CADA `onChange`. Digitar caractere por
// caractere (`user.type`) faz cada tecla de pontuação ("." ou ",") ser imediatamente descartada no
// re-render seguinte, então o separador de milhar NUNCA sobrevive a uma digitação incremental
// aqui — só chega inteiro via colar (`fireEvent.change` de uma vez, como um paste real do
// clipboard). É por isso que o teste dispara UM `fireEvent.change` com a string completa, e não
// `user.type`: é o único caminho realista pelo qual o bug de milhar é alcançável neste campo.
describe("AutomationFields — separador de milhar (#224)", () => {
  it("create_charge: colar '1.234,56' vira amount_cents 123456, não 123", () => {
    const onChange = vi.fn();
    render(
      <AutomationFields
        data={{ key: "gerar-cobranca", action: "create_charge", config: {} }}
        onChange={onChange}
      />,
    );

    const campo = screen.getByPlaceholderText("Valor (R$)");
    fireEvent.change(campo, { target: { value: "1.234,56" } });

    expect(onChange).toHaveBeenCalledWith({ amount_cents: 123456 });
  });

  it("create_quote: colar '1.234,56' vira amount_cents 123456, não 123", () => {
    const onChange = vi.fn();
    render(
      <AutomationFields
        data={{ key: "gerar-orcamento", action: "create_quote", config: {} }}
        onChange={onChange}
      />,
    );

    const campo = screen.getByPlaceholderText("Valor (R$)");
    fireEvent.change(campo, { target: { value: "1.234,56" } });

    expect(onChange).toHaveBeenCalledWith({ amount_cents: 123456 });
  });
});

// ── `GET /funnels/:id/runs` e `GET /crm/clients` fora de forma (issue #225) ──────────────────
//
// `setRuns(data)`/`setClients(data)` recebiam o payload CRU. `runs.map` está atrás de
// `runs.length === 0`, mas `clients.map` (select "Inscrever contato") NÃO está — ele é montado
// direto sempre que a drawer abre.
describe("FunnelAutomationDrawer — jornadas/clientes fora de forma não derrubam a drawer (#225)", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  function renderDrawer() {
    return render(
      <FunnelAutomationDrawer funnelId="f-1" onClose={() => {}} onNotify={() => {}} />,
    );
  }

  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → a drawer abre, sem jornadas nem clientes", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/funnels/f-1/runs") return Promise.resolve({ data: payload } as never);
      if (url === "/crm/clients") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderDrawer();
    await assentar();

    expect(screen.getByText("Nenhuma jornada ainda. Inscreva um contato.")).toBeInTheDocument();
    expect(screen.getByText("— Selecione —")).toBeInTheDocument();
  });

  it("contra-teste: jornada e cliente de verdade continuam aparecendo", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/funnels/f-1/runs")
        return Promise.resolve({
          data: [{ id: "r-1", client_name: "Maria Silva", status: "running", step_count: 2 }],
        } as never);
      if (url === "/crm/clients")
        return Promise.resolve({ data: [{ id: "c-1", name: "Maria Silva" }] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderDrawer();
    await assentar();

    // "Maria Silva" aparece 2x: na jornada (lista) e na option do select de clientes.
    expect(await screen.findAllByText("Maria Silva")).toHaveLength(2);
  });
});
