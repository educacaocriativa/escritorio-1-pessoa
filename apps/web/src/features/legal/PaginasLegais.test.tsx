import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// `useAuth` mockado como DESLOGADO de propósito (mesmo padrão de `App.test.tsx`): o que estes
// testes provam é justamente que os dois documentos legais abrem SEM sessão. Se um dia alguém
// mover essas rotas para dentro do `ProtectedLayout`, o redirecionamento para `/login` quebra
// esta suíte — que é o alarme que queremos, porque publicar o app OAuth do Google depende de a
// Política de Privacidade abrir para quem não tem conta nenhuma.
vi.mock("../../store/auth", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({ isAuthenticated: false, user: null }),
}));
vi.mock("../../store/useIdleTimeout", () => ({
  useIdleTimeout: () => ({ showWarning: false, stayConnected: vi.fn() }),
}));

import App from "../../app/App";

/** Texto da página com espaços normalizados — o JSX quebra frases em várias linhas. */
function textoDaPagina() {
  return (document.body.textContent ?? "").replace(/\s+/g, " ");
}

function abrir(rota: string) {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <App />
    </MemoryRouter>,
  );
}

describe("Páginas legais são públicas", () => {
  it.each([
    ["/privacidade", "Política de Privacidade"],
    ["/termos", "Termos de Serviço"],
  ])("%s abre sem sessão", (rota, titulo) => {
    abrir(rota);
    expect(screen.getByRole("heading", { level: 1, name: titulo })).toBeTruthy();
  });

  it.each(["/privacidade", "/termos"])(
    "%s identifica o responsável com razão social, CNPJ e contato",
    (rota) => {
      abrir(rota);
      const texto = textoDaPagina();
      expect(texto).toContain("FLAVIO KATO LTDA");
      expect(texto).toContain("65.623.582/0001-08");
      expect(texto).toContain("flaviokato76@gmail.com");
    },
  );

  it("cada documento leva ao outro", () => {
    abrir("/privacidade");
    expect(
      screen.getAllByRole("link", { name: "Termos de Serviço" }).length,
    ).toBeGreaterThan(0);
  });

  it("a tela de login leva aos dois documentos", () => {
    abrir("/login");
    expect(screen.getByRole("link", { name: "Política de Privacidade" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Termos de Serviço" })).toBeTruthy();
  });
});

// ── Cláusula de Uso Limitado do Google ────────────────────────────────────────────────────
//
// Não é texto de enfeite: a Google API Services User Data Policy exige que um app que usa
// escopos de usuário (aqui, `calendar.events` + `userinfo.email`) declare o compromisso de Uso
// Limitado na política de privacidade, e a revisão do Google procura essa frase. Apagá-la ao
// "melhorar a redação" reprovaria a publicação sem quebrar nada visível — por isso a asserção é
// pelo texto LITERAL, e não por um `toContain("Uso Limitado")` que passaria com a frase mutilada.
describe("Política de Privacidade — cláusula de Uso Limitado do Google", () => {
  it("declara o compromisso na íntegra", () => {
    abrir("/privacidade");
    expect(textoDaPagina()).toContain(
      "O uso e a transferência, pelo e1p, de informações recebidas das APIs do Google " +
        "obedecerão à Política de Dados do Usuário dos Serviços de API do Google, incluindo " +
        "os requisitos de Uso Limitado.",
    );
  });

  it("aponta para a política do Google", () => {
    abrir("/privacidade");
    const link = screen.getByRole("link", {
      name: "Política de Dados do Usuário dos Serviços de API do Google",
    });
    expect(link.getAttribute("href")).toBe(
      "https://developers.google.com/terms/api-services-user-data-policy",
    );
  });

  it("lista os escopos que o app realmente pede, e só eles", () => {
    abrir("/privacidade");
    const texto = textoDaPagina();
    expect(texto).toContain("calendar.events");
    expect(texto).toContain("userinfo.email");
    // O compromisso de escopo mínimo, que é o que o revisor do Google confere contra a tela de
    // consentimento. Some junto com a frase se alguém generalizar o texto.
    expect(texto).toContain(
      "Não lemos seus e-mails, arquivos, contatos ou qualquer outro dado da sua conta Google.",
    );
  });
});

// ── Afirmações que a auditoria de 03/09/2026 derrubou ─────────────────────────────────────
//
// As três frases abaixo estiveram publicadas e eram falsas. Nenhuma delas quebrava nada
// visível: o site continuava de pé, os testes verdes, e só uma conferência contra a produção
// mostrava a diferença. É exatamente a classe de erro que precisa de consumidor mecânico —
// uma frase forte e falsa num documento legal é pior que uma frase fraca e verdadeira.
//
//  1. "cópia fora do servidor de produção" (§8) e "30 dias na cópia externa" (§9): a EC2 não
//     tem rclone instalado nem BACKUP_S3_BUCKET preenchido. O offsite nunca existiu na AWS;
//     o texto vinha do `.env.prod.example`, que descreve a Hostinger, descomissionada.
//  2. "você pode exportar seus dados a qualquer momento" (Termos §8, e a mesma promessa no
//     §12): não há endpoint de exportação — só `juridico/export.py::to_docx`, que exporta UM
//     documento. A frase enfraquecia o direito de portabilidade do §10 da Política.
//  3. Asaas e a WhatsApp Business Platform listados como prestadores em operação:
//     `PAYMENT_GATEWAY_PROVIDER` e `WHATSAPP_TOKEN` estão vazios em produção.
//
// Se alguma voltar, o texto precisa de código atrás dela — não do contrário.
describe("Os documentos não voltam a prometer o que o sistema não faz", () => {
  it("não anuncia backup fora do servidor de produção", () => {
    abrir("/privacidade");
    const texto = textoDaPagina();
    expect(texto).not.toContain("cópia fora do servidor");
    expect(texto).not.toContain("cópia externa");
    // E diz o que de fato acontece, incluindo o limite.
    expect(texto).toContain("no próprio servidor de produção");
  });

  it("não promete exportação de dados que não existe", () => {
    abrir("/termos");
    const texto = textoDaPagina();
    expect(texto).not.toContain("exportar seus dados a qualquer momento");
    expect(texto).not.toContain("para exportar seus dados");
  });

  it("separa o prestador que opera hoje do que só entra se o assinante ativar", () => {
    abrir("/privacidade");
    const texto = textoDaPagina();
    expect(texto).toContain("Ainda não em uso");
    // Asaas e a plataforma oficial da Meta continuam citadas — mas do lado desligado.
    const desligados = texto.slice(texto.indexOf("Ainda não em uso"));
    expect(desligados).toContain("Asaas");
    expect(desligados).toContain("WhatsApp Business Platform");
  });
});
