import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AutomationFields } from "./FunnelAutomation";

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
