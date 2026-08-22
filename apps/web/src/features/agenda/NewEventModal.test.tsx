import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { paredeDoTenant } from "../../test/paredeDoTenant";
import NewEventModal from "./NewEventModal";

// Onda 2, Task 5: extração do NewEventModal de AgendaPage.tsx para arquivo próprio, para que a
// ficha 360° do contato (Task 6) reuse o mesmo modal em vez de reimplementar o aviso de conflito.
// Rede sempre mockada (IV2): nenhum teste bate em /agenda real.
// O fuso do TENANT é trocável por teste: o `vitest.config.ts` fixa o fuso da MÁQUINA em
// America/Sao_Paulo, e é justamente a diferença entre os dois que este arquivo precisa exercitar.
//
// ⚠️ Os campos de horário são lidos por `paredeDoTenant`, NUNCA por `toHaveValue("…T09:00")`
// (issue #185). O valor de um `<input type="datetime-local">` é naive e sai nas partes locais da
// MÁQUINA: a string literal amarrava estes testes a America/Sao_Paulo sem dizer isso em lugar
// nenhum — três deles reprovavam com uma HORA errada assim que a suíte rodasse em outro fuso, que
// é o que o pool `threads` do Stryker produz. E `.tsx` está FORA do `vitest.mutation.config.ts`,
// então o job de mutação nunca os executou nem para reprovar. A leitura por instante → fuso do
// tenant dá o mesmo resultado em São Paulo, em UTC e em Tóquio.
let fusoDoTenant = "America/Sao_Paulo";
vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  getGoogleStatus: vi.fn(() => Promise.resolve({ connected: false })),
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Título"), "Atendimento cliente");
  fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-08-01T09:00" } });
  fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-08-01T10:00" } });
  await user.click(screen.getByRole("button", { name: "Criar evento" }));
}

beforeEach(() => {
  vi.mocked(api.post).mockReset();
  fusoDoTenant = "America/Sao_Paulo";
});

describe("NewEventModal (Onda 2, Task 5)", () => {
  it("envia client_id quando recebe um", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: { conflicts: [] } } as never);

    render(
      <NewEventModal
        open
        initialDate={null}
        onClose={() => {}}
        onCreated={() => {}}
        clientId="contato-123"
      />,
    );

    await fillAndSubmit(user);

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/agenda/events",
      expect.objectContaining({ client_id: "contato-123" }),
    );
  });

  it("não envia client_id quando não recebe (evento solto, como na Agenda)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: { conflicts: [] } } as never);

    render(<NewEventModal open initialDate={null} onClose={() => {}} onCreated={() => {}} />);

    await fillAndSubmit(user);

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/agenda/events",
      expect.objectContaining({ client_id: null }),
    );
  });

  it("mostra o aviso de conflito sem fechar o modal", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({
      data: { conflicts: [{ id: "ev-outro", title: "Reunião existente" }] },
    } as never);
    const onClose = vi.fn();

    render(<NewEventModal open initialDate={null} onClose={onClose} onCreated={() => {}} />);

    await fillAndSubmit(user);

    expect(await screen.findByText(/Conflito de horário com: Reunião existente/)).toBeInTheDocument();
    // O modal continua aberto: onClose NÃO é chamado quando há conflito (o dono decide).
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Novo evento" })).toBeInTheDocument();
  });

  it("pré-preenche 09:00–10:00 ao abrir num dia, sem hora escolhida", () => {
    render(
      <NewEventModal
        open
        initialDate={new Date(2026, 9, 10)}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    );

    // 09:00–10:00 é a faixa default no relógio do TENANT — quem não escolheu hora nenhuma. O
    // fuso da máquina não participa da afirmação, então ela não pode ser escrita como a string
    // que a máquina escreveria.
    const inicio = screen.getByLabelText("Início");
    expect(paredeDoTenant(inicio, fusoDoTenant)).toBe("10/10/2026 09:00");
    expect(paredeDoTenant(screen.getByLabelText("Fim"), fusoDoTenant)).toBe("10/10/2026 10:00");

    // A FORMA do valor é afirmada à parte, e o recorte dela foi MEDIDO (issue #185). O jsdom
    // aplica a sanitização do HTML no `datetime-local`, então boa parte das mutações de formato
    // do `paraInputLocal` é EQUIVALENTE — ele mesmo as desfaz antes de qualquer asserção:
    // `"…T09:00:00"` e `"… 09:00"` (separador em branco) voltam os dois como `"…T09:00"`, e
    // nenhuma leitura de `el.value` pode matá-las. O que a sanitização NÃO desfaz é segundo
    // diferente de zero: `"…T09:00:30"` sobrevive como `"…T09:00:30.000"`, e aí só esta linha
    // pega — `paredeDoTenant` formata hora e minuto e devolveria "09:00" na mesma.
    expect((inicio as HTMLInputElement).value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  });

  it("pré-preenche a hora escolhida no seletor, e a seguinte no fim", () => {
    render(
      <NewEventModal
        open
        initialDate={new Date(2026, 9, 10)}
        initialHour={14}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    );

    // Mesma régua do teste acima: 14:00–15:00 é o relógio do TENANT, não o da máquina.
    expect(paredeDoTenant(screen.getByLabelText("Início"), fusoDoTenant)).toBe("10/10/2026 14:00");
    expect(paredeDoTenant(screen.getByLabelText("Fim"), fusoDoTenant)).toBe("10/10/2026 15:00");
  });

  it("a hora escolhida é a hora do TENANT, mesmo com o navegador em outro fuso", () => {
    // O seletor decide as faixas no fuso do tenant; o `<input type="datetime-local">` fala no fuso
    // do NAVEGADOR. Entregar "14:00" como string ingênua fazia `new Date(...)` reinterpretá-la na
    // máquina de quem abriu a tela — o dono viajando marcava 15:00 achando que marcava 14:00.
    //
    // Este é o ÚNICO teste do arquivo que existe para provar fuso, e por isso é o único a mexer em
    // `fusoDoTenant`: com tenant e máquina no mesmo fuso, a ida (`instanteNoFuso`) e a volta
    // (`new Date` do campo) se cancelam por construção e a conversão ausente sobreviveria — a
    // família do `toContain("flex-wrap")` do CLAUDE.md §5.1. Tóquio (UTC+9) discorda do runner
    // (UTC−3) em 12h: os dois caminhos divergem até sobre que DIA é.
    fusoDoTenant = "Asia/Tokyo";

    render(
      <NewEventModal
        open
        initialDate={new Date(2026, 9, 10)}
        initialHour={14}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    );

    const inicio = screen.getByLabelText("Início") as HTMLInputElement;
    // 14:00 em Tóquio, lido de volta no fuso do tenant — a afirmação que o nome do teste faz.
    // A string crua do campo seria "2026-10-10T02:00" num runner em UTC−3 e "T05:00" em UTC:
    // afirmá-la seria afirmar sobre a máquina, que é justamente o que este teste NÃO quer dizer.
    expect(paredeDoTenant(inicio, fusoDoTenant)).toBe("10/10/2026 14:00");
    // E o INSTANTE, que é o que vai para o `save()` — literal, sem passar por função nenhuma da
    // produção, e igual em qualquer máquina.
    expect(new Date(inicio.value).toISOString()).toBe("2026-10-10T05:00:00.000Z");
  });
});
