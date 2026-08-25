import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// Achado do usuário testando em campo (screenshot em Android): a sidebar tem 256px FIXOS
// (`w-64 shrink-0`, sem breakpoint algum) e sempre empurrou o conteúdo — num aparelho de 360px
// sobravam ~100px, títulos viravam "Desp", cartões espremidos, e o checkbox "marcar como paga"
// da tela de comprovante ficava fora da área visível. Esta suíte cobre o comportamento
// responsivo novo: a gaveta nasce fechada abaixo do breakpoint desktop e fecha sozinha ao
// navegar; no desktop ela nasce aberta e permanece.
vi.mock("../lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ data: {} }) },
}));
// `user` precisa ser um dono de verdade (não `null`): a Sidebar filtra os itens por
// `hasModule(user, item.module)` (RBAC), e a Sidebar só é montada DEPOIS do gate de autenticação
// — `user: null` aqui não é um caso real, e faria a sidebar aparecer VAZIA nestes testes
// (que existem para cobrir responsividade, não permissão).
vi.mock("../store/auth", () => ({
  useAuth: () => ({
    logout: vi.fn(),
    user: { role: "owner", allowed_modules: [] },
    tenant: null,
  }),
}));
vi.mock("../store/pageActions", () => ({
  usePageActions: () => ({ action: null }),
}));

import AppShell from "./AppShell";

/** Simula a largura do viewport ANTES do primeiro render — o estado inicial da gaveta lê
 * `window.innerWidth` no `useState(isDesktopWidth)`, então precisa estar certo de antemão. */
function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
}

describe("AppShell — sidebar responsiva (achado de campo: layout quebrado no celular)", () => {
  afterEach(() => {
    setViewportWidth(1024); // não vaza a largura de um teste para o próximo
  });

  it("no celular, a gaveta nasce FECHADA — não mais os 256px fixos espremendo o conteúdo", async () => {
    setViewportWidth(375); // largura comum de Android/iPhone, abaixo do breakpoint

    render(
      <MemoryRouter>
        <AppShell>
          <p>conteúdo da página</p>
        </AppShell>
      </MemoryRouter>,
    );

    await waitFor(() => screen.getByText("conteúdo da página"));
    // "Sair" só existe dentro da <Sidebar> — sua ausência prova que ela não montou.
    expect(screen.queryByText("Sair")).toBeNull();
  });

  it("no desktop, a gaveta nasce ABERTA — preserva o comportamento de sempre", async () => {
    setViewportWidth(1280);

    render(
      <MemoryRouter>
        <AppShell>
          <p>conteúdo da página</p>
        </AppShell>
      </MemoryRouter>,
    );

    await waitFor(() => screen.getByText("Sair"));
  });

  it("no celular, abrir a gaveta e navegar para outra rota a fecha sozinha", async () => {
    setViewportWidth(375);
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <AppShell>
          <p>conteúdo da página</p>
        </AppShell>
      </MemoryRouter>,
    );

    await user.click(screen.getByLabelText("Abrir menu"));
    const agendaLink = await screen.findByRole("link", { name: /agenda/i });
    await user.click(agendaLink);

    // A gaveta cobre a tela inteira no celular: sair sem fechá-la deixaria o usuário olhando
    // para o menu em vez da página que acabou de escolher.
    await waitFor(() => expect(screen.queryByText("Sair")).toBeNull());
  });
});
