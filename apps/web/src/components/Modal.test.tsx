import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Modal, { Field } from "./Modal";

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

// Achado de acessibilidade em 360px (Story 8.11): o painel do `Modal` não tinha `max-h`/
// `overflow-y-auto`, então um modal com muitos campos (ex.: AccountModal de Contas & Saldos,
// ~750-900px de conteúdo empilhado) transbordava SEM rolagem em telas pequenas, escondendo o
// botão de salvar. Como `jsdom` não calcula layout real, o que dá para garantir aqui é a REGRA
// ESTRUTURAL: o painel tem `overflow-y-auto` (rolagem quando necessário) e `max-h-[85vh]` (nunca
// maior que a viewport), sem usar `overflow-hidden` (que CORTA em vez de rolar).
describe("Modal (painel ganha rolagem em telas pequenas — Story de correção isolada)", () => {
  it("o painel tem max-h-[85vh] e overflow-y-auto, e não usa overflow-hidden", () => {
    render(
      <Modal title="Conteúdo alto" open onClose={vi.fn()}>
        <div style={{ height: "900px" }}>conteúdo bem alto</div>
      </Modal>,
    );

    const panel = screen.getByText("Conteúdo alto").closest("div.rounded-2xl");
    expect(panel).not.toBeNull();
    expect(panel!.className).toContain("max-h-[85vh]");
    expect(panel!.className).toContain("overflow-y-auto");
    expect(panel!.className).not.toContain("overflow-hidden");
  });
});
