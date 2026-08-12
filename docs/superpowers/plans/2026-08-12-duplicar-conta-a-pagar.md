# Duplicar conta a pagar — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dar ao dono um botão que abre o cadastro de conta a pagar já preenchido com os dados de uma conta existente, com vencimento no mês seguinte, para ele editar e gravar.

**Architecture:** só frontend. A regra (quais campos a cópia leva e como o vencimento avança) vive numa função pura em `duplicar.ts`; `AttachModal` só avisa que o dono clicou; `PagarPage` costura; `NewBillModal` passa a aceitar valores iniciais e é remontado por `key`. A gravação é o `POST /payables/bills` que já existia.

**Tech Stack:** React 18 + TypeScript + Vite, Tailwind, vitest + @testing-library/react (jsdom), lucide-react.

**Spec:** `docs/superpowers/specs/2026-08-12-duplicar-conta-a-pagar-design.md`

## Global Constraints

- **Nenhuma mudança de backend.** Sem rota nova, sem migration, sem campo novo. Se alguma tarefa parecer pedir backend, pare e reporte — é sinal de que o desenho foi mal lido.
- **Data de calendário nunca passa por `new Date`.** Regra §6.0 do `CLAUDE.md`. `new Date("2026-07-31")` é meia-noite **UTC** e devolve dia 30 em UTC−3. Toda aritmética de `due_date` é sobre a string `"YYYY-MM-DD"` fatiada.
- **Idioma:** texto de UI, comentários e docstrings em **PT-BR**; identificadores de código em inglês, salvo quando o arquivo vizinho já usa PT-BR (`camposDaCopia`, `proximoVencimento` seguem o padrão de `baixa.ts`/`contas.ts`).
- **Rede sempre mockada nos testes** (`vi.mock("../../lib/api", …)`), como o `PagarPage.test.tsx` já faz. Nenhum teste toca `/payables` de verdade.
- **Commits:** Conventional Commits (`feat:`, `test:`, `docs:`). Branch já criada: `feat/duplicar-conta-a-pagar`.
- **Comando de teste de um arquivo:** `cd apps/web && pnpm vitest run <caminho>`.
- **`main` é protegida** — a entrega termina em PR, nunca em push direto.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Tarefa |
|---|---|---|
| `apps/web/src/features/pagar/duplicar.ts` *(novo)* | As duas funções puras: o que a cópia leva e como o vencimento avança | 1 |
| `apps/web/src/features/pagar/duplicar.test.ts` *(novo)* | Testes das funções puras, sem DOM | 1 |
| `apps/web/src/features/pagar/PagarPage.tsx` *(modificar)* | `AttachModal` ganha o botão; `NewBillModal` aceita `inicial`; a página costura os dois | 2 |
| `apps/web/src/features/pagar/PagarPage.test.tsx` *(modificar)* | Os quatro testes de fluxo em jsdom | 2 |
| `CLAUDE.md` *(modificar)* | A entrada obrigatória do §5, passo 4 | 3 |

---

### Task 1: a regra da cópia, em funções puras

**Files:**
- Create: `apps/web/src/features/pagar/duplicar.ts`
- Test: `apps/web/src/features/pagar/duplicar.test.ts`

**Interfaces:**
- Consumes: o tipo `Payable` de `@e1p/shared-types` (já existe; carrega `description`, `supplier`, `amount_cents`, `due_date`, `chart_account_id`, `cost_center_id`, `contract_id`, `payment_code`, `recurrence`).
- Produces, e a Task 2 depende destes nomes exatos:
  - `export interface CamposDaConta` com os campos `description`, `supplier`, `chartAccountId`, `costCenterId`, `value`, `dueDate`, `recurrence`, `recurrenceCount`, `paymentCode`, `contractId` — **todos `string`**. Os nomes são idênticos aos das variáveis de estado que o `NewBillModal` já usa, de propósito: qualquer divergência vira um campo silenciosamente vazio.
  - `export function proximoVencimento(ymd: string): string`
  - `export function camposDaCopia(bill: Payable): CamposDaConta`

- [ ] **Step 1: Escrever o teste que falha**

Criar `apps/web/src/features/pagar/duplicar.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { Payable } from "@e1p/shared-types";
import { camposDaCopia, proximoVencimento } from "./duplicar";

/** Conta de origem rica: todos os campos que a cópia decide levar ou deixar. */
const ORIGEM = {
  id: "b-9",
  tenant_id: "t-1",
  description: "Aluguel Sala gravacao",
  category: "Mkt",
  supplier: "WorkPlace Palhano",
  amount_cents: 20000,
  due_date: "2026-07-31",
  chart_account_id: "ca-1",
  contract_id: "ct-1",
  cost_center_id: "cc-1",
  status: "paid",
  is_overdue: false,
  paid_at: "2026-07-31T00:00:00Z",
  recurrence: "monthly",
  recurrence_count: 12,
  recurrence_group: "grp-1",
  payment_code: "00020126580014BR.GOV.BCB.PIX",
  attachment_url: "",
  created_at: "2026-01-01T00:00:00Z",
} as unknown as Payable;

describe("proximoVencimento — a data avança um mês, com trava de fim de mês", () => {
  it("dia que existe no mês destino é preservado", () => {
    expect(proximoVencimento("2026-07-31")).toBe("2026-08-31");
    expect(proximoVencimento("2026-08-15")).toBe("2026-09-15");
  });

  it("dia que não existe no mês destino cai no último dia", () => {
    expect(proximoVencimento("2026-01-31")).toBe("2026-02-28");
    expect(proximoVencimento("2026-01-30")).toBe("2026-02-28");
    expect(proximoVencimento("2026-03-31")).toBe("2026-04-30");
  });

  it("ano bissexto dá 29 dias a fevereiro", () => {
    expect(proximoVencimento("2028-01-31")).toBe("2028-02-29");
    // 2100 não é bissexto (divisível por 100 e não por 400) — a regra completa, não só `% 4`.
    expect(proximoVencimento("2100-01-31")).toBe("2100-02-28");
    expect(proximoVencimento("2000-01-31")).toBe("2000-02-29");
  });

  it("não estica o dia só porque o mês destino é mais longo", () => {
    expect(proximoVencimento("2026-11-30")).toBe("2026-12-30");
  });

  it("dezembro vira janeiro do ano seguinte", () => {
    expect(proximoVencimento("2026-12-15")).toBe("2027-01-15");
    expect(proximoVencimento("2026-12-31")).toBe("2027-01-31");
  });

  it("aceita um instante ISO completo, usando só a parte da data", () => {
    expect(proximoVencimento("2026-07-31T00:00:00Z")).toBe("2026-08-31");
  });

  it("entrada inválida devolve string vazia, nunca 'NaN-NaN-NaN'", () => {
    // O campo nasce vazio e o botão "Adicionar conta" fica desabilitado — o dono escolhe a data.
    expect(proximoVencimento("")).toBe("");
    expect(proximoVencimento("qualquer coisa")).toBe("");
  });
});

describe("camposDaCopia — o que a cópia leva e o que ela deixa", () => {
  it("leva descrição, fornecedor, categoria, centro de custo e contrato", () => {
    const c = camposDaCopia(ORIGEM);
    expect(c.description).toBe("Aluguel Sala gravacao");
    expect(c.supplier).toBe("WorkPlace Palhano");
    expect(c.chartAccountId).toBe("ca-1");
    expect(c.costCenterId).toBe("cc-1");
    expect(c.contractId).toBe("ct-1");
  });

  it("leva o valor como texto com vírgula, no formato que o formulário consome", () => {
    expect(camposDaCopia(ORIGEM).value).toBe("200,00");
    expect(camposDaCopia({ ...ORIGEM, amount_cents: 1165 } as Payable).value).toBe("11,65");
  });

  it("leva o vencimento já avançado um mês", () => {
    expect(camposDaCopia(ORIGEM).dueDate).toBe("2026-08-31");
  });

  // Decisão do fundador, registrada na §4.2 da spec: a recomendação era NÃO copiar (código de
  // agosto não paga setembro). Ele optou por copiar, porque os fornecedores dele usam chave Pix
  // fixa. O teste existe para ninguém "corrigir" isso de volta lendo só a recomendação.
  it("leva o código Pix/boleto — decisão consciente, não descuido", () => {
    expect(camposDaCopia(ORIGEM).paymentCode).toBe("00020126580014BR.GOV.BCB.PIX");
  });

  // Duplicar É a alternativa manual à recorrência. Copiar "Mensal × 12" faria um gesto de
  // "repetir uma vez" gerar doze contas e doze eventos na Agenda, sem o dono pedir.
  it("NÃO leva a recorrência: nasce sempre em 'Não repete'", () => {
    const c = camposDaCopia(ORIGEM);
    expect(c.recurrence).toBe("none");
    expect(c.recurrenceCount).toBe("12"); // o default do formulário, inerte enquanto recurrence="none"
  });

  it("campos nulos na origem viram string vazia, nunca 'null' na tela", () => {
    const c = camposDaCopia({
      ...ORIGEM,
      chart_account_id: null,
      cost_center_id: null,
      contract_id: null,
    } as Payable);
    expect(c.chartAccountId).toBe("");
    expect(c.costCenterId).toBe("");
    expect(c.contractId).toBe("");
  });
});
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `cd apps/web && pnpm vitest run src/features/pagar/duplicar.test.ts`
Expected: FAIL — `Failed to resolve import "./duplicar"`.

- [ ] **Step 3: Escrever a implementação mínima**

Criar `apps/web/src/features/pagar/duplicar.ts`:

```ts
import type { Payable } from "@e1p/shared-types";

/**
 * **Duplicar uma conta a pagar** — a regra de o que a cópia leva, e como o vencimento avança.
 *
 * Pura, sem React e sem relógio: é a única parte desta funcionalidade com regra de verdade, e
 * mora aqui para ser testável sem DOM (mesmo recorte de `baixa.ts`, ao lado).
 *
 * ⚠️ **Nada aqui pode construir `Date`.** `due_date` é uma data de CALENDÁRIO, e
 * `new Date("2026-07-31")` é meia-noite UTC — em UTC−3 o `getDate()` devolve **30**, e a cópia
 * nasceria com o vencimento um dia antes, em silêncio, só para quem está a oeste de Greenwich.
 * Regra §6.0 do CLAUDE.md, e é aqui que ela morde. A aritmética é sobre inteiros fatiados da
 * string, exatamente como `diaDoDebito` e `lib/datetime.formatDay` já fazem.
 */

/** Os campos do formulário de "Nova conta a pagar", nos mesmos nomes que ele usa no estado. */
export interface CamposDaConta {
  description: string;
  supplier: string;
  chartAccountId: string;
  costCenterId: string;
  /** Valor como texto com vírgula ("200,00") — o formulário faz o parse na hora de gravar. */
  value: string;
  /** "YYYY-MM-DD". Vazio quando a origem não tem data legível. */
  dueDate: string;
  recurrence: string;
  recurrenceCount: string;
  paymentCode: string;
  contractId: string;
}

const DIAS_POR_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function bissexto(ano: number): boolean {
  return (ano % 4 === 0 && ano % 100 !== 0) || ano % 400 === 0;
}

/** Último dia de um mês 1-12. Fevereiro é o único que depende do ano. */
function ultimoDiaDoMes(ano: number, mes: number): number {
  if (mes === 2) return bissexto(ano) ? 29 : 28;
  return DIAS_POR_MES[mes - 1];
}

/**
 * "2026-07-31" → "2026-08-31"; "2026-01-31" → "2026-02-28" (o mês destino não tem 31).
 *
 * Aceita um instante ISO completo e usa só a parte da data. Entrada ilegível devolve `""`, para o
 * campo nascer vazio e o botão de gravar ficar desabilitado — melhor pedir a data do que inventar.
 */
export function proximoVencimento(ymd: string): string {
  const [a, m, d] = ymd.slice(0, 10).split("-").map(Number);
  if (!a || !m || !d || m < 1 || m > 12) return "";
  const ano = m === 12 ? a + 1 : a;
  const mes = m === 12 ? 1 : m + 1;
  const dia = Math.min(d, ultimoDiaDoMes(ano, mes));
  return `${ano}-${String(mes).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
}

/**
 * O que a cópia leva. Deliberadamente **fora**: anexos (o comprovante da conta antiga pendurado
 * numa conta ainda não paga seria evidência de um pagamento colada em outro) e a recorrência
 * (duplicar É a alternativa manual a ela — copiá-la faria um gesto gerar doze contas).
 *
 * O código Pix/boleto **é** copiado por decisão do fundador (§4.2 da spec), com o risco aceito:
 * um código do mês anterior fica na linha nova com cara de válido.
 */
export function camposDaCopia(bill: Payable): CamposDaConta {
  return {
    description: bill.description,
    supplier: bill.supplier,
    chartAccountId: bill.chart_account_id ?? "",
    costCenterId: bill.cost_center_id ?? "",
    contractId: bill.contract_id ?? "",
    paymentCode: bill.payment_code,
    value: (bill.amount_cents / 100).toFixed(2).replace(".", ","),
    dueDate: proximoVencimento(bill.due_date),
    recurrence: "none",
    recurrenceCount: "12",
  };
}
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `cd apps/web && pnpm vitest run src/features/pagar/duplicar.test.ts`
Expected: PASS — 13 testes.

- [ ] **Step 5: Conferir os tipos**

Run: `cd apps/web && pnpm typecheck`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/pagar/duplicar.ts apps/web/src/features/pagar/duplicar.test.ts
git commit -m "feat: a regra da copia de conta a pagar, em funcoes puras

O vencimento avanca um mes com trava de fim de mes, calculado por
fatiamento de string — new Date sobre data de calendario devolveria o dia
anterior em UTC-3 (regra 6.0). Recorrencia nasce em 'Nao repete'."
```

---

### Task 2: o botão, o formulário preenchido e a costura

**Files:**
- Modify: `apps/web/src/features/pagar/PagarPage.tsx` (`PagarPage`, `AttachModal`, `NewBillModal`)
- Test: `apps/web/src/features/pagar/PagarPage.test.tsx` (acrescentar um `describe` no fim)

**Interfaces:**
- Consumes da Task 1: `camposDaCopia(bill: Payable): CamposDaConta` e o tipo `CamposDaConta`.
- Produces: nada que outra tarefa consuma. `AttachModal` passa a exigir a prop `onDuplicar: () => void` (obrigatória, não opcional: existe um único call site, e opcional criaria um ramo sem teste).

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao **fim** de `apps/web/src/features/pagar/PagarPage.test.tsx`:

```ts
/**
 * **Duplicar conta a pagar.**
 *
 * O botão NÃO vive no grid (a coluna de ações já carrega até cinco elementos e a tabela já rola
 * lateralmente em 360px) — vive dentro do modal "Boleto/Pix", que já é alcançável em toda linha
 * não cancelada.
 */
describe("PagarPage — duplicar conta a pagar", () => {
  const CONTA_PAGA = {
    ...CONTA_ABERTA,
    id: "b-9",
    description: "Aluguel Sala gravacao",
    supplier: "WorkPlace Palhano",
    amount_cents: 20000,
    due_date: "2026-07-31",
    status: "paid",
    paid_at: "2026-07-31T00:00:00Z",
    recurrence: "monthly",
    recurrence_count: 12,
    payment_code: "00020126580014BR.GOV.BCB.PIX",
    contract_id: "ct-1",
  };

  const OUTRA_CONTA = {
    ...CONTA_ABERTA,
    id: "b-10",
    description: "Curso Marketing",
    supplier: "Mafer",
    amount_cents: 547611,
    due_date: "2026-07-04",
  };

  function mockBills(bills: unknown[]) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills") return Promise.resolve({ data: bills } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  /** Abre o modal Boleto/Pix da linha `indice` e clica em "Duplicar esta conta". */
  async function duplicar(user: ReturnType<typeof userEvent.setup>, indice = 0) {
    const botoes = await screen.findAllByRole("button", { name: "Boleto/Pix" });
    await user.click(botoes[indice]);
    await user.click(await screen.findByRole("button", { name: "Duplicar esta conta" }));
  }

  it("abre o cadastro preenchido, com o vencimento no mês seguinte e sem recorrência", async () => {
    const user = userEvent.setup();
    mockBills([CONTA_PAGA]);
    renderPage();

    await duplicar(user);

    // O modal de anexos saiu de cena e o de cadastro entrou.
    expect(screen.queryByText("Boleto / Contrato / Pix")).toBeNull();
    expect(screen.getByText("Nova conta a pagar")).toBeInTheDocument();

    expect(screen.getByLabelText("Descrição")).toHaveValue("Aluguel Sala gravacao");
    expect(screen.getByLabelText("Fornecedor")).toHaveValue("WorkPlace Palhano");
    expect(screen.getByLabelText("Valor (R$)")).toHaveValue("200,00");
    // 31/07 → 31/08: o dia existe em agosto e é preservado.
    expect(screen.getByLabelText("Vencimento")).toHaveValue("2026-08-31");
    // A origem é "monthly ×12"; a cópia nasce sem recorrência, senão um clique geraria 12 contas.
    expect(screen.getByLabelText("Recorrência")).toHaveValue("none");
  });

  it("gravar dispara um POST de conta NOVA, sem id, com os campos copiados", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    mockBills([CONTA_PAGA]);
    renderPage();

    await duplicar(user);
    await user.click(screen.getByRole("button", { name: "Adicionar conta" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    const [url, body] = vi.mocked(api.post).mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/payables/bills");
    expect(body).toMatchObject({
      description: "Aluguel Sala gravacao",
      supplier: "WorkPlace Palhano",
      amount_cents: 20000,
      due_date: "2026-08-31",
      recurrence: "none",
      recurrence_count: 1,
      payment_code: "00020126580014BR.GOV.BCB.PIX",
      contract_id: "ct-1",
    });
    // É uma conta NOVA, não um PATCH disfarçado na origem.
    expect(body).not.toHaveProperty("id");
  });

  // ⚠️ O teste que mata o bug de `key`: `useState(inicial)` só lê o prop na MONTAGEM, e o modal
  // fica montado o tempo todo. Sem remontar, a segunda duplicação mostraria a primeira conta —
  // e o defeito passa despercebido, porque a primeira duplicação de cada sessão funciona.
  it("duplicar uma segunda conta mostra a SEGUNDA, não a primeira", async () => {
    const user = userEvent.setup();
    mockBills([CONTA_PAGA, OUTRA_CONTA]);
    renderPage();

    await duplicar(user, 0);
    await user.click(screen.getByRole("button", { name: "Fechar" }));

    await duplicar(user, 1);
    expect(screen.getByLabelText("Descrição")).toHaveValue("Curso Marketing");
    expect(screen.getByLabelText("Valor (R$)")).toHaveValue("5476,11");
    expect(screen.getByLabelText("Vencimento")).toHaveValue("2026-08-04");
  });

  // ⚠️ O segundo ponto de limpeza: sem ele, "Nova conta" abriria o cadastro já preenchido com uma
  // despesa que o dono não pediu — a forma mais direta de gravar uma conta que não existe.
  it("depois de duplicar e fechar, 'Nova conta' abre um formulário EM BRANCO", async () => {
    const user = userEvent.setup();
    mockBills([CONTA_PAGA]);
    renderPage();

    await duplicar(user);
    await user.click(screen.getByRole("button", { name: "Fechar" }));

    await user.click(await screen.findByRole("button", { name: "Nova conta" }));
    expect(screen.getByLabelText("Descrição")).toHaveValue("");
    expect(screen.getByLabelText("Fornecedor")).toHaveValue("");
    expect(screen.getByLabelText("Valor (R$)")).toHaveValue("");
    expect(screen.getByLabelText("Vencimento")).toHaveValue("");
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falham**

Run: `cd apps/web && pnpm vitest run src/features/pagar/PagarPage.test.tsx`
Expected: os quatro testes novos FALHAM — `Unable to find an accessible element with the role "button" and name "Duplicar esta conta"`. Os testes que já existiam continuam passando.

- [ ] **Step 3: `AttachModal` ganha o botão**

Em `apps/web/src/features/pagar/PagarPage.tsx`, na assinatura de `AttachModal`, acrescentar a prop:

```tsx
function AttachModal({
  bill,
  onClose,
  onSaved,
  onDuplicar,
}: {
  bill: Payable;
  onClose: () => void;
  onSaved: () => void;
  /** Avisa que o dono quer repetir esta despesa. O modal não sabe o que isso significa. */
  onDuplicar: () => void;
}) {
```

E, **depois** do botão "Salvar código" (o último elemento dentro do `<div className="space-y-4">`), acrescentar:

```tsx
        {/* Duplicar mora aqui, e não no grid: a coluna de ações da tabela já carrega até cinco
            elementos e rola lateralmente em 360px. Este modal já é alcançável em toda linha não
            cancelada, então a restrição de status vem de graça, pela porta que já existia. */}
        <div className="border-t border-neutral-100 pt-4">
          <button
            onClick={onDuplicar}
            className="w-full rounded-pill border border-neutral-200 py-2.5 font-semibold text-neutral-600 hover:border-primary-300 hover:text-primary-600"
          >
            Duplicar esta conta
          </button>
          <p className="mt-2 text-xs text-neutral-400">
            Abre o cadastro preenchido com os dados desta conta e vencimento no mês seguinte. Os
            anexos não são copiados.
          </p>
        </div>
```

- [ ] **Step 4: `NewBillModal` aceita valores iniciais**

Acrescentar o import no topo do arquivo:

```tsx
import { camposDaCopia, type CamposDaConta } from "./duplicar";
```

Trocar a assinatura e os `useState` de `NewBillModal`:

```tsx
function NewBillModal({
  open,
  onClose,
  onCreated,
  inicial,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  /**
   * Valores de partida quando o formulário nasce de uma duplicação.
   *
   * ⚠️ Lido **só na montagem** — `useState(x)` ignora mudanças de `x` depois disso. Quem monta
   * este componente (`PagarPage`) passa uma `key` derivada da conta duplicada justamente para
   * forçar a remontagem; sem ela, a segunda duplicação mostraria os dados da primeira.
   */
  inicial?: CamposDaConta;
}) {
  const [description, setDescription] = useState(inicial?.description ?? "");
  const [chartAccountId, setChartAccountId] = useState(inicial?.chartAccountId ?? "");
  const [costCenterId, setCostCenterId] = useState(inicial?.costCenterId ?? "");
  const [supplier, setSupplier] = useState(inicial?.supplier ?? "");
  const [value, setValue] = useState(inicial?.value ?? "");
  const [dueDate, setDueDate] = useState(inicial?.dueDate ?? "");
  const [recurrence, setRecurrence] = useState(inicial?.recurrence ?? "none");
  const [recurrenceCount, setRecurrenceCount] = useState(inicial?.recurrenceCount ?? "12");
  const [paymentCode, setPaymentCode] = useState(inicial?.paymentCode ?? "");
  const [contractId, setContractId] = useState(inicial?.contractId ?? "");
```

O resto do componente (o `save()` e o JSX) **não muda**.

- [ ] **Step 5: `PagarPage` costura os dois**

Acrescentar o estado, junto dos outros (`const [edit, setEdit] = …`):

```tsx
  // A conta que está sendo duplicada. `null` = o formulário de "Nova conta" nasce em branco.
  const [duplicando, setDuplicando] = useState<Payable | null>(null);
```

Trocar a ação primária, para que "Nova conta" **sempre** abra em branco:

```tsx
  // ⚠️ `setDuplicando(null)` aqui não é redundante com o `onClose`: sem ele, duplicar → fechar →
  // "Nova conta" abriria o cadastro preenchido com uma despesa que o dono não pediu.
  usePrimaryAction(
    "Nova conta",
    useCallback(() => {
      setDuplicando(null);
      setOpen(true);
    }, []),
  );
```

Trocar a montagem do `NewBillModal`:

```tsx
      <NewBillModal
        // A `key` remonta o formulário quando a conta de origem muda — é o que faz os valores
        // iniciais valerem na segunda duplicação (ver a docstring de `inicial`).
        key={duplicando?.id ?? "nova"}
        open={open}
        inicial={duplicando ? camposDaCopia(duplicando) : undefined}
        onClose={() => {
          setOpen(false);
          setDuplicando(null);
        }}
        onCreated={load}
      />
```

E passar `onDuplicar` ao `AttachModal`:

```tsx
      {attach && (
        <AttachModal
          bill={attach}
          onDuplicar={() => {
            setDuplicando(attach);
            setAttach(null);
            setOpen(true);
          }}
          onClose={() => setAttach(null)}
          onSaved={() => {
            setAttach(null);
            load();
          }}
        />
      )}
```

- [ ] **Step 6: Rodar os testes da tela e confirmar que passam**

Run: `cd apps/web && pnpm vitest run src/features/pagar/PagarPage.test.tsx`
Expected: PASS — os quatro novos e todos os que já existiam.

- [ ] **Step 7: Rodar a suíte inteira do frontend**

Run: `cd apps/web && pnpm test`
Expected: PASS. Se algum teste de outra tela quebrar, é regressão real desta mudança — investigue antes de seguir, não ajuste o teste.

- [ ] **Step 8: Lint e tipos**

Run: `cd apps/web && pnpm lint && pnpm typecheck`
Expected: sem erros e sem warnings (`--max-warnings 0`).

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/features/pagar/PagarPage.tsx apps/web/src/features/pagar/PagarPage.test.tsx
git commit -m "feat: duplicar conta a pagar pelo modal Boleto/Pix

O botao abre o cadastro preenchido em vez de gravar direto, para o dono
ajustar valor e vencimento antes. Fica no modal, nao no grid: a coluna de
acoes ja carrega cinco elementos e rola lateralmente em 360px."
```

---

### Task 3: a entrada no CLAUDE.md e o fechamento

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: o comportamento entregue nas tarefas 1 e 2.
- Produces: nada de código.

O §5, passo 4 do `CLAUDE.md` trata esta entrada com o mesmo peso do teste, e a razão está escrita lá: sem ela, quem ler só o arquivo conclui que a funcionalidade **não existe** — foi assim que o Epic 5 inteiro ficou invisível por um mês. A entrada é escrita a partir do **código que subiu**, não do que o plano pretendia.

- [ ] **Step 1: Reler o que de fato foi entregue**

Run: `git diff origin/main --stat`
Confirme que o diff é só os três arquivos de `apps/web/src/features/pagar/` mais a spec. Se houver mais alguma coisa, a entrada precisa mencioná-la.

- [ ] **Step 2: Escrever a entrada**

Acrescentar em `CLAUDE.md`, logo **depois** da seção `## Financeiro: editar + agenda (reverberar)` (é a vizinha temática: editar, estornar e agora duplicar são os três gestos sobre uma conta que já existe):

```markdown
## Financeiro: duplicar conta a pagar

> Spec: `docs/superpowers/specs/2026-08-12-duplicar-conta-a-pagar-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-12-duplicar-conta-a-pagar.md`

Boa parte das despesas do dono **se repete sem ser recorrente**: aluguel de sala, viagens do
mesmo trecho, ferramentas em dólar (o valor muda todo mês). A recorrência já existia e não
resolve esse caso — ela exige saber de antemão quantas vezes vai repetir e supõe valor fixo.

- [x] **"Duplicar esta conta" abre o cadastro PREENCHIDO, não grava direto.** O gesto termina no
  mesmo `POST /payables/bills` de sempre: **zero backend, zero migration, zero campo novo**.
- [x] **O botão vive dentro do modal "Boleto/Pix", NÃO no grid** (decisão do fundador). A coluna
  de ações já carrega até cinco elementos e a tabela já rola lateralmente em 360px — uma sexta
  ação em toda linha pagaria largura em todas as telas para servir um gesto ocasional. Como o
  modal só é alcançável em linha não cancelada, **a restrição de status vem de graça**: não há
  regra própria a manter.
- [x] **`pagar/duplicar.ts`** — `camposDaCopia` + `proximoVencimento`, puras, testadas sem DOM
  (mesmo recorte de `baixa.ts`). ⚠️ **O vencimento avança um mês por fatiamento de string**, com
  trava de fim de mês (`31/01 → 28/02`, bissexto incluído). `new Date("2026-07-31")` é meia-noite
  **UTC** e devolveria dia 30 em UTC−3 — a cópia nasceria um dia antes, em silêncio e só para
  quem está a oeste de Greenwich (regra §6.0). Quem "simplificar" com `Date` reintroduz isso.
- [x] **A cópia leva** descrição, fornecedor, categoria, centro de custo, valor, contrato e o
  código Pix/boleto. **Não leva** anexos nem a recorrência.
  - **Recorrência nasce em "Não repete", sempre.** Duplicar É a alternativa manual a ela; copiar
    `"Mensal × 12"` faria um gesto de repetir UMA vez gerar doze contas e doze eventos na Agenda.
  - ⚠️ **O código Pix/boleto é copiado por decisão do fundador, com o risco aceito e registrado:**
    um código do mês anterior fica na linha nova com cara de válido, e o ícone "Copiar código"
    entrega um código vencido. A recomendação era não copiar; ele optou por copiar porque os
    fornecedores dele usam chave Pix fixa. **Tem teste fixando o comportamento** — para ninguém
    "corrigir" de volta lendo só a recomendação. Reverter é uma linha em `camposDaCopia`.
  - **Anexos ficam fora** porque copiá-los exigiria duplicação de arquivo no backend e o
    **comprovante** da conta antiga ficaria pendurado numa conta ainda não paga: evidência de um
    pagamento colada em outro.
- ⚠️ **`NewBillModal` é remontado por `key`, e isso não é estilo.** Ele fica montado o tempo todo,
  e `useState(inicial)` só lê o prop na MONTAGEM — sem a `key`, a segunda duplicação mostraria os
  dados da primeira. O defeito passa despercebido em teste manual apressado, porque **a primeira
  duplicação de cada sessão funciona**. Tem teste dedicado.
- ⚠️ **`duplicando` é zerado em DOIS lugares** — no `onClose` do formulário e na ação primária
  "Nova conta". Só o primeiro cobre o caminho normal e deixa vivo o caminho `duplicar → fechar →
  Nova conta`, que abriria o cadastro preenchido com uma despesa que o dono não pediu. Também
  tem teste próprio.
- **Sem dívida de aceite em ~360px**, ao contrário das últimas entregas: nada entrou no grid e o
  botão segue a largura total dos que já estavam no modal.
- **Dívida:** duplicar cobrança em **Contas a Receber** não existe (a simetria é tentadora e o
  módulo é outro); não há duplicação em lote nem template de despesa.
```

- [ ] **Step 3: Rodar os três gates do frontend uma última vez**

Run: `cd apps/web && pnpm lint && pnpm typecheck && pnpm test`
Expected: os três verdes.

⚠️ **Não use `bash scripts/check.sh` para julgar isto** — ele **mascara falha de frontend** com `|| true` no vitest (dívida registrada no `CLAUDE.md`, seção do Epic 8). Rode as três etapas individualmente, como acima.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: registra a duplicacao de conta a pagar no CLAUDE.md"
```

- [ ] **Step 5: Agentes de QA (§5 do CLAUDE.md)**

Rodar `regression-tester`, `bug-hunter` e `dedup-checker` sobre o diff. **Peça o aval do usuário antes de disparar** — nesta sessão os subagentes só são acionados a pedido dele.

- [ ] **Step 6: Abrir o PR**

`main` é protegida (`GH006`): push direto é rejeitado e a entrega precisa de PR com os 4 checks. O push é operação **exclusiva do @devops** (`.claude/rules/agent-authority.md`) — delegue, não execute direto.

---

## Verificação final

Antes de dizer que está pronto, confirme cada um **com a saída do comando na mão**, não de memória:

- [ ] `cd apps/web && pnpm vitest run src/features/pagar/duplicar.test.ts` — verde
- [ ] `cd apps/web && pnpm test` — verde, incluindo as telas que não foram tocadas
- [ ] `cd apps/web && pnpm lint && pnpm typecheck` — sem erro e sem warning
- [ ] `git diff origin/main --stat` — só `duplicar.ts`, `duplicar.test.ts`, `PagarPage.tsx`, `PagarPage.test.tsx`, `CLAUDE.md` e os dois documentos
- [ ] A entrada no `CLAUDE.md` existe e descreve o **código que subiu**
