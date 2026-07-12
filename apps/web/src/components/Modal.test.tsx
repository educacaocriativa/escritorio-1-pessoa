import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Field } from "./Modal";

// Teste-piloto da infraestrutura de teste de componente (Story 7.3 — AC2).
// Serve de MODELO para as Stories 7.4/7.5 e demais itens de cobertura de UI do catálogo:
//   - render() de @testing-library/react
//   - queries via `screen`, preferindo getByLabelText/getByRole (checagem de acessibilidade)
//   - interação via @testing-library/user-event
//   - callbacks/mocks de rede via vi.fn()/vi.mock (nunca bater no backend real)
// `Field` foi escolhido por ser um componente REAL em uso (modais de Nova conta/Nova cobrança,
// formulários de contrato/orçamento) e totalmente desacoplado (sem Context/Router/API).
describe("Field (teste-piloto de componente — Story 7.3)", () => {
  it("caminho feliz: renderiza o label e propaga a digitação via onChange", async () => {
    const onChange = vi.fn();
    render(<Field label="E-mail" value="" onChange={onChange} />);

    // O texto do label aparece no DOM...
    expect(screen.getByText("E-mail")).toBeInTheDocument();
    // ...e o input está associado a ele (label envolvendo o input => associação implícita).
    const input = screen.getByLabelText("E-mail");
    expect(input).toBeInTheDocument();

    // Digitar um caractere dispara onChange com o valor digitado.
    await userEvent.type(input, "a");
    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("caminho infeliz: label ausente não é encontrado e, sem interação, onChange não é chamado", () => {
    const onChange = vi.fn();
    render(<Field label="Nome" value="" onChange={onChange} />);

    // queryBy* retorna null (não lança) quando o elemento não existe — prova de que a query
    // reporta ausência corretamente, base para asserções negativas nas próximas stories.
    expect(screen.queryByText("E-mail")).toBeNull();
    expect(screen.queryByLabelText("Telefone")).toBeNull();

    // Sem digitação/interação, o callback nunca dispara e o input reflete o `value` vazio.
    const input = screen.getByLabelText("Nome");
    expect(input).toHaveValue("");
    expect(onChange).not.toHaveBeenCalled();
  });
});
