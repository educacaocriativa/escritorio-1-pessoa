# Duplicar conta a pagar — design

**Data:** 2026-08-12
**Origem:** pedido do fundador — *"gostaria de criar aqui no contas a pagar um botão para duplicar e
nos levar para a tela de cadastro para que possamos editar e aí sim, gravar"*.

## 1. O problema

A tela de Contas a Pagar do fundador tem dezenas de despesas que **se repetem sem serem
recorrentes**: aluguel de sala de gravação, viagens do mesmo trecho, ferramentas cobradas em dólar
(valor muda todo mês), pagamentos ao mesmo fornecedor com escopo diferente. Hoje, para lançar a
edição do mês seguinte, o dono redigita tudo: descrição, fornecedor, categoria, centro de custo,
valor e contrato.

A **recorrência** já existe (`recurrence` + `recurrence_count`, que geram N contas de uma vez) e
**não resolve este caso**: ela exige saber, no ato do cadastro, quantas vezes a despesa vai se
repetir e supõe que o valor não muda. Duplicar é a alternativa manual — repete a despesa **uma vez,
quando ela de fato aconteceu de novo**, e aceita edição antes de gravar.

## 2. Escopo

**Só frontend.** Nenhuma rota nova, nenhuma migration, nenhum campo novo. A cópia termina num
`POST /payables/bills` idêntico ao que o botão "Nova conta" já dispara — o backend não distingue uma
conta duplicada de uma digitada, e não deve mesmo: no plano de dados ela é uma despesa como
qualquer outra.

Fora de escopo, declarado e não esquecido: duplicar cobrança em Contas a Receber (a simetria é
tentadora e o módulo é outro); duplicação em lote; template de despesa.

## 3. O caminho na tela

```
linha da conta → botão "Boleto/Pix" → modal → botão "Duplicar esta conta"
    → o modal fecha e abre "Nova conta a pagar", já preenchido
    → o dono edita o que quiser → "Adicionar conta"
```

**O grid não muda em nada.** A decisão foi do fundador, contra a proposta inicial de um botão por
linha: a coluna de ações já carrega até cinco elementos (`⧉ código`, `Boleto/Pix`, `Editar`,
`Marcar paga`, `Cancelar`/`Estornar`/`Cancelar agendamento`) e a tabela já rola lateralmente em
360px (`min-w-[48rem]` dentro de `overflow-x-auto`). Uma sexta ação em toda linha pagaria largura
em todas as telas para servir um gesto ocasional.

**O botão aparece sempre que o modal abre** — ou seja, em conta paga, a pagar, atrasada e agendada.
Cancelada não tem "Boleto/Pix" (`p.status !== "canceled"`), então a restrição vem de graça, pela
porta que já existia. Não há regra de status própria a manter, e é isso que torna a colocação
barata.

## 4. O que a cópia leva

| Vem preenchido | Nasce limpo |
|---|---|
| `description`, `supplier` | `recurrence` = `"none"` |
| `amount_cents` (formatado no campo de texto) | Anexos (boleto/contrato/comprovante) |
| `chart_account_id` (categoria do plano de contas) | Status — é conta nova, nasce `open` |
| `cost_center_id` (centro de custo) | `paid_at`, `recurrence_group`, `attachment_url` |
| `contract_id` (eixo Lucratividade/DRE) | — |
| `payment_code` (Pix copia-e-cola / linha do boleto) | — |
| **`due_date` = mesmo dia do mês seguinte** | — |

### 4.1 Recorrência nasce em "Não repete", sempre

Duplicar **é** a alternativa manual à recorrência. Copiar `"Mensal × 12"` faria um gesto de "repetir
esta despesa" gerar **doze** contas de uma vez, com doze eventos na Agenda — muito além do que o
dono pediu, e a desfazer uma por uma. O campo continua editável no formulário: quem quiser
recorrência a escolhe explicitamente.

### 4.2 O código do boleto é copiado — decisão do fundador, com a ressalva registrada

A recomendação original era **não** copiar: o código do boleto de agosto não paga setembro, e
copiado ele fica na linha nova com cara de válido, com o ícone "Copiar código do boleto/Pix"
entregando um código vencido. O fundador optou por copiar (os fornecedores dele usam chave Pix
fixa, e redigitar o código é justamente parte do trabalho que a duplicação existe para evitar).

Fica registrado como **risco aceito**, não como descuido. Se um dia incomodar, a reversão é
uma linha em `camposDaCopia`.

### 4.3 Anexos não são copiados

Copiá-los exigiria duplicação de arquivo no backend (`Attachment` guarda bytes no Postgres ou
`storage_key` no S3) — escopo de backend inteiro para servir um caso raro. E o **comprovante** da
conta antiga ficaria pendurado numa conta que ainda não foi paga: evidência de um pagamento colada
em outro, que é exatamente o tipo de afirmação sem lastro que o Epic 8 existe para não produzir.

## 5. O vencimento, e por que ele é a única regra de verdade aqui

`due_date` da cópia = **mesmo dia do mês seguinte**, com trava de fim de mês:

| Original | Cópia | Por quê |
|---|---|---|
| `2026-07-31` | `2026-08-31` | dia existe no mês destino |
| `2026-01-31` | `2026-02-28` | fevereiro não tem 31 — cai no último dia |
| `2028-01-31` | `2028-02-29` | ano bissexto |
| `2026-11-30` | `2026-12-30` | não vira 31 só porque dezembro tem 31 |
| `2026-12-15` | `2027-01-15` | virada de ano |

⚠️ **O cálculo fatia a string `"YYYY-MM-DD"` e nunca constrói `Date`.** É a regra §6.0 do
CLAUDE.md, e este é precisamente o lugar onde ela morde: `new Date("2026-07-31")` é interpretado
como **meia-noite UTC**, então em UTC−3 `getDate()` devolve **30**, e a cópia nasceria com o
vencimento um dia antes — em silêncio, e só para quem está a oeste de Greenwich. O mesmo motivo
pelo qual `diaDoDebito` e `lib/datetime.formatDay` já fatiam string em vez de converter.

A aritmética é sobre inteiros: `(ano, mês, dia)` → `mês + 1` (com `ano + 1` quando estoura) →
`min(dia, últimoDiaDoMês(ano, mês))`. O último dia do mês vem de uma tabela com a regra bissexta
explícita, não de `new Date(ano, mês, 0)`.

## 6. As peças

### 6.1 `apps/web/src/features/pagar/duplicar.ts` (novo)

Duas funções **puras**, sem React e sem relógio:

- `proximoVencimento(ymd: string): string` — a regra da §5.
- `camposDaCopia(bill: Payable): CamposDaConta` — a tabela da §4, devolvendo já no formato que o
  formulário consome: o valor sai como texto com vírgula (`(cents / 100).toFixed(2).replace(".",
  ",")`), exatamente a mesma conversão que `EditBillModal` já faz.

Fica **fora do componente** porque é a única parte com regra de verdade, e assim é testável sem
DOM. É o mesmo recorte de `pagar/baixa.ts`, que já existe ao lado.

### 6.2 `AttachModal` — ganha `onDuplicar`

Prop opcional. Quando presente, renderiza um botão secundário abaixo de "Salvar código", largura
total, no padrão visual que o modal já usa. Rótulo: **"Duplicar esta conta"** — nomeia o objeto,
porque dentro de um modal chamado "Boleto / Contrato / Pix" um "Duplicar" solto poderia ser lido
como duplicar o *anexo*.

O modal não sabe o que "duplicar" significa; ele só avisa. A costura é da página.

### 6.3 `NewBillModal` — passa a aceitar valores iniciais

Prop `inicial?: CamposDaConta`. **O detalhe que decide se a feature funciona:** o modal fica
montado o tempo todo (`<NewBillModal open={open} …>`), e `useState(inicial)` **não** re-inicializa
quando o prop muda — o valor inicial de `useState` só vale na montagem. Sem tratar isso, o
formulário abriria vazio na primeira duplicação e com os dados da duplicação **anterior** na
segunda.

A saída é `key`: a página passa `key={duplicando?.id ?? "nova"}`, e o React remonta o componente
quando a conta de origem muda. É o mecanismo idiomático para "este formulário é outro formulário
agora", e evita o `useEffect` de sincronização de props para estado — que teria de ser escrito com
cuidado para não sobrescrever o que o usuário acabou de digitar.

⚠️ Uma consequência de `key` que precisa ficar escrita: remontar **descarta** o que estivesse
digitado. É o comportamento desejado (duplicar outra conta troca o formulário inteiro), mas quem
mexer aqui deve saber que é deliberado.

### 6.4 `PagarPage` — a costura

Um estado `duplicando: Payable | null`. `AttachModal` recebe
`onDuplicar={() => { setDuplicando(attach); setAttach(null); setOpen(true); }}`; `NewBillModal`
recebe `inicial` e a `key`.

⚠️ **`duplicando` tem de ser zerado em DOIS lugares, não um.** No `onClose` do formulário, e
também na ação primária "Nova conta" (`usePrimaryAction`, que hoje só faz `setOpen(true)`). Zerar
só no fechamento cobre o caminho normal e deixa vivo o caminho em que o dono duplica, fecha e
depois clica em "Nova conta" — que abriria o formulário **preenchido com a conta duplicada**, sem
ele ter pedido nada. Um formulário de conta nova que nasce preenchido é a forma mais direta de
gravar uma despesa que não existe.

## 7. Testes

**`duplicar.test.ts`** (unitário, sem DOM):
- as cinco linhas da tabela da §5, incluindo bissexto e virada de ano;
- recorrência sempre `"none"`, mesmo quando a origem é `"monthly"`;
- `payment_code` e `contract_id` **copiados** (a decisão da §4.2 vira teste, senão alguém a
  "conserta" de volta lendo só a recomendação original);
- valor formatado com vírgula.

**`PagarPage.test.tsx`** (jsdom, arquivo já existe):
- abrir Boleto/Pix → "Duplicar esta conta" → o modal de anexos fecha e o de nova conta abre com
  descrição, fornecedor, valor e vencimento preenchidos, e recorrência em "Não repete";
- gravar dispara `POST /payables/bills` com o corpo esperado — **e sem `id`**: a cópia é uma conta
  nova, não um `PATCH` na origem;
- duplicar uma conta, fechar sem gravar, e duplicar **outra** → o formulário mostra a segunda, não
  a primeira (é o teste que mata o bug de `key` da §6.3; sem ele o defeito passa despercebido,
  porque a primeira duplicação de cada sessão funciona);
- duplicar, fechar sem gravar, e clicar em **"Nova conta"** → o formulário nasce **em branco** (o
  segundo ponto de limpeza da §6.4; sem ele a tela oferece uma conta nova já preenchida com dados
  que o dono não pediu).

## 8. 360px

Nada entra no grid, então a largura da tabela não muda. O botão novo vive dentro de um modal que já
é usado em celular e segue a largura total dos botões que já estão lá — não há coluna nova, não há
`flex-wrap` a validar. **Não há dívida de aceite visual aberta por esta mudança**, ao contrário das
últimas quatro entregas.

## 9. Riscos

| Risco | Mitigação |
|---|---|
| Código do boleto copiado parece válido e está vencido | Decisão consciente do fundador (§4.2), com teste fixando o comportamento e reversão de uma linha |
| `useState` não re-inicializa e o formulário mostra a duplicação anterior | `key` (§6.3) + o terceiro teste da §7, escrito exatamente para este defeito |
| `new Date` voltar ao cálculo do vencimento por "simplificação" | Cálculo por fatiamento de string, com o motivo escrito no docstring da função e caso de teste de fim de mês |

## 10. Entrada no CLAUDE.md

Último passo obrigatório (§5, passo 4): registrar em `CLAUDE.md` que Contas a Pagar ganhou
duplicação, onde o botão mora, o que a cópia leva e o que ela deliberadamente não leva.
