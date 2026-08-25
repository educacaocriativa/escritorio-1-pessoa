import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { assentar } from "../test/assentar";
import Attachments from "./Attachments";

// issue #207 — `setItems(data)`: payload cru no setter, SEM operador nenhum. Este NÃO é uma tela,
// é um bloco embutido em várias (boleto, contrato...): sem ErrorBoundary no app, o `items.map` de
// um não-array não deixa o bloco vazio — leva junto a tela que o hospeda.
vi.mock("../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

const SLOTS = [{ key: "comprovante", label: "Comprovante" }];

function renderBloco() {
  return render(<Attachments ownerType="payable" ownerId="p-1" slots={SLOTS} />);
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("Attachments — lista de anexos fora de forma não derruba quem hospeda (#207)", () => {
  // ⚠️ Objeto e número saem da lista por medição: o render é guardado por `items.length > 0`, e
  // `.length` deles é `undefined` — `undefined > 0` é falso e o `.map` nunca roda. Mutante
  // equivalente para essas duas formas. As duas abaixo passam pelo portão.
  it.each([
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → o bloco de upload continua de pé", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    renderBloco();
    await assentar();

    expect(screen.getByRole("button", { name: /Comprovante/ })).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("contra-teste: anexo de verdade continua listado", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "a-1", filename: "nota.pdf", label: "comprovante", size: 2048 }],
    } as never);
    renderBloco();
    await assentar();

    expect(screen.getByText("nota.pdf")).toBeInTheDocument();
    expect(screen.getByText("2 KB")).toBeInTheDocument();
  });
});
