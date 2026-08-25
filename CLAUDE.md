# e1p — "Empresa de 1 Pessoa" · Memória do Projeto

> **Este arquivo é a memória viva do projeto.** É carregado automaticamente em toda sessão do Claude Code.
> Leia-o inteiro antes de qualquer tarefa. Mantenha-o atualizado quando algo estrutural mudar.

## 1. O que é
SaaS **multi-tenant white-label** (`e1p.com`) para profissionais autônomos (advogados, médicos, consultores).
Cada usuário é uma "empresa de 1 pessoa" com subdomínio próprio (`joaosilva.e1p.com`).
Diferencial: **IA (Claude) como funcionário invisível** atravessando todos os módulos.
Modelo de negócio: **split de pagamento** — plataforma retém **40% (produtos) / 30% (serviços) / 20% (recorrência)**.

Spec mestre completa: [`docs/MODULES.md`](docs/MODULES.md). Origem: `/Volumes/Extreme SSD/2026_e1p/Configuração do software.docx`.

## 2. Stack (decidida — ver `docs/decisions/0001-stack-e-infra.md`)
- **Backend:** FastAPI (Python 3.13), SQLAlchemy 2 + Alembic, PostgreSQL 16.
- **Frontend:** React 18 + Vite + TypeScript + Tailwind. Design system "Portal" (ver `packages/design-tokens`).
- **Monorepo:** pnpm workspaces (JS) + app Python isolado. Tipos compartilhados em `packages/shared-types`.
- **Mobile (futuro):** Expo / React Native, reaproveitando API + `packages/`.
- **IA:** Anthropic SDK. **Não há modelo global** — cada tarefa tem o seu em `core/ai.MODELO_POR_TAREFA`, e toda chamada é contabilizada (ver §Contabilidade de IA).
- **Infra AWS:** container enxuto (EC2 Graviton + Docker) → ECS Fargate. RDS Postgres, S3+CloudFront, SSM, SQS. Ver `docs/AWS-DEPLOYMENT.md`.

## 3. Regras de ouro (NUNCA violar)
1. **Isolamento de tenant é sagrado.** Todo dado de negócio carrega `tenant_id`. Acesso a dados SEMPRE passa pela camada de tenancy (RLS no Postgres). Nunca escreva query que possa cruzar tenants. Ver `apps/api/app/core/tenancy.py`.
   - ⚠️ **A app DEVE conectar como papel NÃO-superusuário** (`e1p_app`), senão a RLS é IGNORADA (superusuários fazem bypass, mesmo com FORCE). Configurado em `infra/docker/initdb/01-rls-enforce.sql`. **Na AWS/RDS o mesmo vale**: rode migrations e a app com um papel non-superuser dono das tabelas (ver `docs/AWS-DEPLOYMENT.md`). Validado por teste e2e no Postgres real (João não vê dados da Maria).
   - ⚠️ **O GUC do tenant é setado em escopo de SESSÃO** (`set_config(..., false)`) em `db/session.py`, não de transação. Com escopo de transação (`true`), `db.refresh()` pós-commit roda sem tenant e a RLS esconde a própria linha (erro "Could not refresh instance"). O `tenant_session` reseta o GUC no `finally` para não vazar entre requests do pool. (Bug que só aparece com RLS real — SQLite não pega.)
2. **Anonimizador antes da IA.** Dados sensíveis (nomes, CPF, contas) são substituídos por variáveis ANTES de ir para a API do Claude e reinseridos localmente depois. Crítico para o módulo Jurídico (segredo de justiça). Ver `apps/api/app/core/anonymizer.py`.
3. **Rastro da IA.** Toda ação executada pela IA grava log "Ação executada pela IA" (autor + timestamp).
4. **Custo importa.** Estamos otimizando para AWS barato. Preferir soluções serverless-baratas / Graviton/ARM / cache. Não introduzir serviço pago sem justificar.
5. **Não quebrar o que já funciona.** Toda mudança roda os agentes de QA (ver seção 5) e a suíte de testes antes de considerar concluída.

## 4. Estrutura do repositório
```
apps/api/          FastAPI — app/core (auth, tenancy, anonymizer, ai), app/modules/<modulo>, app/db
apps/web/          React+Vite — app (shell/layout), features/<modulo>, components, lib
packages/
  shared-types/    Contrato de API em TS (web + mobile)
  design-tokens/   Cores/spacing/tipografia do design "Portal"
infra/             docker-compose (dev), Dockerfiles, terraform (AWS)
docs/              ARCHITECTURE, MODULES, AWS-DEPLOYMENT, DATA-MODEL, decisions/ (ADRs)
.claude/agents/    Agentes de QA (regressão, bugs, duplicação)
scripts/           Utilitários (check, seed, etc.)
```

## 5. Fluxo de qualidade (Req. 3 — obrigatório a cada mudança)
Ao criar/alterar qualquer funcionalidade:
1. Escreva/atualize testes (`apps/api/tests`, `apps/web` vitest, e2e playwright).
2. Rode `bash scripts/check.sh` (lint + types + testes) — deve passar. Antes de fechar a tarefa,
   rode o alvo único **`bash scripts/gates.sh`**, que encadeia as três suítes pesadas **em série**
   (`check.sh` → `pytest -m rls_e2e` → `pnpm e2e`). **Nunca rode duas delas ao mesmo tempo:** sob
   concorrência elas se contaminam e a falha fica indistinguível de regressão real — §5.5.
3. Rode os agentes de QA conforme a tarefa:
   - **regression-tester** — garante que o novo não quebrou o antigo.
   - **bug-hunter** — caça bugs/edge cases no código novo.
   - **dedup-checker** — encontra duplicação e código que já existe (DRY).
4. **Escreva a entrada NESTE arquivo** — o que passou a existir, a regra que fica para quem mexer
   nisso depois, e a dívida que sobrou. Escrita a partir do **código que subiu**, não do que a story
   pretendia. Dívida que esta mudança FECHOU sai daqui: dívida resolvida e ainda escrita manda o
   próximo leitor resolver de novo o que já está resolvido.
5. Só considere a tarefa concluída quando os 3 agentes passarem **E** a entrada existir.

> **Por que o passo 4 tem o mesmo peso do teste.** Documentar como último passo é documentar o que
> vai ser cortado — a sessão acaba, o CI fica verde, o fundador diz "sobe", e a entrada nunca é
> escrita. Não dói na hora: a funcionalidade funciona. Dói depois, e sempre no mesmo lugar — quem lê
> só este arquivo conclui que a funcionalidade **não existe**. Foi exatamente assim que o **Epic 5
> inteiro** (9 stories, em produção desde julho) ficou invisível aqui por um mês.
>
> Por isso toda story carrega, como **último AC numerado**, a entrada no CLAUDE.md — mesma régua do
> teste: um AC que ninguém pula. Quem valida: `story-draft-checklist` §7 (no draft, pelo @sm/@po) e
> `story-dod-checklist` item 7 (antes de "Ready for Review", pelo @dev). Refactor puro não some com
> o AC: satisfaz com uma linha explícita dizendo que nada mudou para o próximo leitor, e por quê.

### 5.1 A régua de layout em 360px (`apps/web/e2e/`, desde 2026-08-10)

**Layout só se prova MEDINDO.** `expect(linha.className).toContain("flex-wrap")` passou duas sessões
com a `FilaPagamentosPage` quebrada em produção: o `overflow-x` estava certo, o `flex-wrap` estava
certo, e a tela estava errada. **Nenhum teste de `apps/web/e2e/` pode aferir classe CSS** — só
`scrollWidth`, `getBoundingClientRect()`, `toBeInViewport()` e o texto efetivamente visível.

- **Como roda:** `pnpm --filter @e1p/web e2e`. Sobe **só o Vite** (porta **5273** — a 5173 colide
  com outro projeto nas máquinas de dev) e intercepta a API com `page.route` (`e2e/support/api.ts`).
  Sem backend, sem Docker, sem banco: foi por achar que medir custava caro que **seis telas** subiram
  sem medição e **três PRs de correção em campo** foram pagos (#56, #58, #89).
- **A régua** é `e2e/support/medidas.ts`: `medirPagina`, `alvosPequenos` (mínimo tocável **44px**),
  `camposBaixos` (o mesmo mínimo, mas só ALTURA e só no que se DIGITA — ver "Campo de digitação"
  abaixo) e `textoForaDaTela` (o texto que só existe se o dono rolar de lado — o defeito que a Onda
  2b-ii achou na primeira medição, `R$ 3.` no lugar de `R$ 3.000,00`).
- **As fixtures são de PIOR CASO PLAUSÍVEL** (nome longo de banco, valor de 6 dígitos, título de
  grupo comprido), nas formas reais de `packages/shared-types`. Dado curto sempre cabe: medir com ele
  é medir uma tela que não existe.
- **Modal medido = `testId` na CAIXA** (#123, desde 2026-08-18). O recorte da varredura entra pela
  prop `testId` do `components/Modal.tsx`, e ela é aplicada na **caixa** — cabeçalho e barra de ação
  inclusive. Recorte no `children` deixa os dois FORA da conta **por construção**: foi assim que
  `textoForaDaTela` devolveu **lista vazia** com o "Fechar" em **x=698** numa tela de 360 (#119).
  Medidos hoje (**10 modais em 6 arquivos**): `EscolherHorario` (`ficha-marcar-360`),
  `AccountModal` (`modal-conta-360`), o detalhe de evento da Agenda (`agenda-evento-360`),
  "Declarar saldo"/"Lançar movimento" (`contas-modais-360`), "Movimentar: {item.name}" do Estoque
  (`estoque-movimentar-360`), "Vender: {product.name}" dos Produtos (`produtos-vender-360`) e
  "Transferir"/"Editar movimento"/"Ignorar movimento" (`contas-movimento-360`).
- **CAMPO DE DIGITAÇÃO: 44px vêm de `.campos-tocaveis`, não de `className` em cada campo** (#215,
  desde 2026-08-22). A regra vive em `apps/web/src/styles/index.css` e vale para `<input>` (menos
  `checkbox`/`radio`/`file`/`color`/`range`), `<select>` e `<textarea>` DENTRO de um contêiner que
  declare a classe. Quem já a declara: a **caixa do `components/Modal.tsx`** (logo, todo modal do
  app), o cartão do `auth/LoginPage.tsx`, os **dois modais escritos à mão** do
  `funis/FunnelBuilderPage.tsx` e o formulário do `juridico/JuridicoWizardPage.tsx`. Alcance
  auditável em uma linha: `grep -rn "campos-tocaveis" apps/web/src/`.
  - **Por que não `min-h-11` no `Field`.** O `Field` são **84 usos em 14 telas**, mas ao lado de
    quase todo `<Field>` há um `<select>` escrito à mão com a MESMA classe (`px-3 py-2 text-sm`) e
    a mesma altura errada, e existem **3 cópias locais** do componente (`LoginPage.tsx:203`,
    `FunnelBuilderPage.tsx:736`, `JuridicoWizardPage.tsx:178`) que um conserto no componente não
    alcança. Consertar só o `Field` pagaria 84 campos e deixaria ~35 em pé **com a aparência de
    dívida paga** — que é a forma de defeito que a issue existia para evitar.
  - **Por que OPT-IN e não global.** Medido em 22/08/2026 no catálogo de `e2e/support/rotas.ts`:
    fora dos formulários há mais **~90** campos abaixo de 44px, e eles moram nos CONSTRUTORES —
    `/marketing/m1` (30), `/sites/s1` (15), `/marketing/novo` (12), `/orcamentos/novo` (7),
    `/contratos/novo` (4) —, editores densos de `px-2 py-1.5 text-xs` com **27 a 34px**. Engordá-los
    junto mudaria cinco telas que nenhuma régua mede por ALTURA, sem ninguém ter olhado o resultado;
    e uma allowlist para excluí-los seria allowlist sem razão. Dívida aberta, com número.
  - **Consequência a lembrar:** `<Field>` usado FORA de um `Modal` volta aos 38px. Quem o fizer
    declara `campos-tocaveis` no contêiner do formulário — e acrescenta o caso à régua.
  - **A régua** é `apps/web/e2e/campo-modal-360.spec.ts`: abre o modal em **16 telas** e mede
    `camposBaixos` com o recorte no overlay. Antes do conserto: **79 campos abaixo de 44px** (38px
    o `<input>` do `Field`, 37–39px os `<select>`, 40px os `date`/`datetime-local`). Cada caso
    declara **quantos** campos tem: modal que não renderizou campo nenhum devolveria lista vazia e
    passaria por conserto.
- ⚠️ **`scrollWidth` NÃO vê o defeito do título — a BORDA vê.** Sem `min-w-0`, o `<h2>` é item de flex
  com `min-width: auto`: ele **cresce** em vez de transbordar. Com o conserto do #119 revertido e
  medido, `scrollWidth === clientWidth` seguia **verde** enquanto a borda direita do título ia a
  **894px** e o "Fechar" a **946px** numa viewport de 360. Mede-se `boundingBox` do título contra a
  borda da CAIXA; `scrollWidth` fica como segunda metade, nunca como a única.
- ⚠️ **A 5273 colide entre WORKTREES do próprio e1p, e isso já mediu o branch errado.** Com
  `reuseExistingServer: !CI`, um Vite de OUTRO checkout na 5273 fazia o Playwright **reusar** aquele
  servidor e medir o código do outro branch em silêncio: em 18/08/2026, **35 dos 41** testes
  vermelhos com `getByTestId` "não encontrado" para um `data-testid` escrito no arquivo — e o modo
  de falha oposto (**verde** contra código alheio) seria indistinguível de aprovação. Agora
  `reuseExistingServer` é **`false` sempre**: porta ocupada vira erro alto em vez de medição falsa.
  Para rodar duas worktrees ao mesmo tempo: `E2E_PORT=5373 pnpm --filter @e1p/web e2e`. ⚠️ **A
  porta própria resolve a colisão de PORTA, não a de MÁQUINA** (#162): duas suítes pesadas rodando
  de fato ao mesmo tempo se contaminam e devolvem `locator not found` indistinguível de regressão
  real — ver §5.5.
- ⚠️ **O controle positivo é parte do teste, não cortesia — e ele MUDA com o título** (#130).
  Modal de título **digitado pelo dono**: remover `min-w-0 break-words` do `Modal.tsx` tem de deixar
  o spec **vermelho**, restaurar (por CÓPIA do arquivo, nunca `git checkout`) tem de devolver o
  verde. Medido em 18/08: "Movimentar" pôs o "Fechar" em **x+w=837,1** e o título em **785,1**
  contra uma caixa que acaba em **344,5**; "Vender", **806,2** e **798,4**. Modal de título
  **constante** NÃO fica vermelho com essa mutação — medido nos três da `ContasSaldosPage`, os
  quatro testes seguiram verdes —, e ali o controle é outro: **isca plantada no cabeçalho** (e na
  barra `sticky`, quando houver), exigida na lista de cortes.
- **A régua achou três defeitos reais na `ContasSaldosPage` ao ser instalada** (#130), e os três já
  estão consertados: (a) o resumo da transferência põe os dois nomes de conta em `<strong>` — sem
  `break-words` vazavam **153,8px** e **118,9px** da caixa; (b) a `raw_description` do extrato chega
  **colada** ("PIXENVIADOCPF12345678900…") e vazava **326px** da caixa do "Editar movimento";
  (c) o rótulo `sr-only` do valor é `position: absolute` e, sem ancestral posicionado, **não era
  recortado** pelo deslizador `overflow-x-auto` da tabela — a PÁGINA rolava de lado até **879px**
  numa viewport de 360, por um rótulo que ninguém vê. Conserto: `relative` no deslizador.
- **Dívida:** a medição de modal cobre **6 dos 19** arquivos que usam `Modal` — **10 dos 35
  modais**. Os de título **digitado pelo dono** estão todos medidos; os **25 que faltam** têm
  título fixo e risco menor: `PlatformUsers` (4), `PagarPage` (3), `CobrancasPage` (3), `CrmPage`
  (2), `InvestimentosPage` (2), `ProdutosPage` (2 dos 3), `EstoquePage` (1 de 2), `SitesPage`,
  `EscolhaDaBaixa`, `PlanoContasPage`, `FinanceiroPage`, `CentrosCustoPage`, `CockpitPage`,
  `NewEventModal` e `IdleWarningModal`.
  ⚠️ **O denominador "18 arquivos" de #123/#130 estava errado, e o erro é reprodutível:**
  `components/IdleWarningModal.tsx` importa `./Modal` por caminho **relativo** e escapa de um
  `grep components/Modal`. São **19**. O numerador de 35 modais sempre o incluiu — ou seja, os dois
  números nunca fecharam entre si. Conte `<Modal` para o total, nunca só o import.
  Segue de pé a dívida da `ComprovantePage` (#130): o `ALTURA_DA_BARRA` do `baixa.ts` tem seis
  mutantes sobreviventes que **encolhem** a barra, nenhum unit test fecha (o número é medida do
  DOM) e aquela tela não está entre as medidas.
- ⚠️ **O CI não tinha NENHUM job de frontend até esta data** — o `vitest` nunca rodou nele, e nenhuma
  medição de tela era exigida em PR. O job `frontend` (typecheck + vitest + playwright) fecha isso.
- ⚠️ **O job roda Node 24, e a versão NÃO é detalhe de infraestrutura.** A raiz declara
  `"engines": {"node": ">=22"}`; o job nasceu pinado em **20** e o sintoma não foi erro de engine —
  foi `src/lib/shareInbox.test.ts` **vermelho só no CI e verde em toda máquina de dev**. Aquele
  teste depende de `structuredClone` preservar `File`, e esse comportamento **muda entre versões do
  Node** (é a mesma lacuna que o comentário no topo dele descreve para o jsdom). **Dívida:** o teste
  continua sensível à versão do Node, e o CI hoje exercita só a versão dos desenvolvedores — não o
  piso `>=22` que o repositório promete suportar.
- ✅ **O job `frontend` BARRA o merge — a dívida de 2026-08-10 está fechada (issue #122).** Conjunto
  obrigatório de `main`, **verificado em 2026-08-18**: `test-in-prod-image`, `cross-tenant-rls`,
  `secret-scan`, `sast-semgrep` e **`frontend`**. A régua mede **e barra**. Ela já estava na
  configuração antes desta data — o que faltava era alguém conseguir LER a configuração, não mudá-la.
  **Como reler sem ser admin** (o dono é o único admin, e reabrir isso à mão custou uma issue):
  `GET /branches/main/protection` responde **404 tanto para "branch não protegida" quanto para "seu
  token não é admin"**, e `repository.branchProtectionRules` do GraphQL devolve `totalCount: 0` pelo
  mesmo motivo — **nenhum dos dois é resposta**, os dois são o silêncio da falta de permissão. Quem
  tem só `push` lê pelo `refUpdateRule`, que é a projeção não-admin da mesma regra:
  ```bash
  gh api graphql -f query='query { repository(owner:"educacaocriativa", name:"escritorio-1-pessoa")
    { ref(qualifiedName:"refs/heads/main") { refUpdateRule { requiredStatusCheckContexts } } } }'
  ```
  Confirmação cruzada: `/branches/main` traz `"protected": true`, e `/rules/branches/main` volta `[]`
  — ou seja, a proteção é **branch protection clássica**, não ruleset; procurar em Rules não acha.

### 5.2 A régua do fuso nos testes (issues #120 e #129, fechadas em 2026-08-18; #136 em 2026-08-19)

**Um teste sobre fuso do tenant que roda com o fuso do tenant IGUAL ao da máquina não testa fuso
nenhum.** `apps/web/vitest.config.ts` fixa `env: { TZ: "America/Sao_Paulo" }` para a suíte inteira.
Enquanto o mock devolver `useFuso: () => "America/Sao_Paulo"` — ou o teste não mockar nada e cair no
fallback `FUSO_PADRAO`, que é o mesmo valor —, ler o instante pelo fuso do **tenant** e lê-lo pelas
partes locais do `Date` produzem o mesmo resultado **por construção**. É a família do
`toContain("flex-wrap")` do §5.1: asserção estruturalmente incapaz de falhar.

Medido na PR #119: **5 de 5 mutações no coração do `features/agenda/grade.ts` sobreviveram a 11
testes verdes** — inclusive trocar `today(fuso, …)` por `localYmd(new Date(…))`. A mutação sobreviveu
ao teste literalmente chamado *"agrupa pelo dia do TENANT, não pelo do navegador"*. **A produção
estava certa; o que faltava era um teste capaz de dizer isso.**

- **O padrão** é `let fusoDoTenant = "America/Sao_Paulo"` no topo, `vi.mock(".../store/auth", () => ({
  useFuso: () => fusoDoTenant }))`, reset no `beforeEach` e `fusoDoTenant = FUSO_DISTANTE` só nos
  testes que existem para provar fuso. `FUSO_DISTANTE = "Asia/Tokyo"` (UTC+9, sem horário de verão):
  12h à frente do runner, então os dois caminhos discordam até sobre que **dia** é. Referências:
  `features/agenda/grade.test.ts` e `features/agenda/NewEventModal.test.tsx`.
- ⚠️ **Nem toda asserção com data deve trocar de fuso, e a exceção precisa estar ESCRITA.** As provas
  de que uma **data de calendário NÃO converte** (`formatDay` em `all_day`/`due_date`) só funcionam
  com um fuso **negativo**: é o UTC−3 que puxa a meia-noite UTC para o dia anterior e denuncia um
  `formatDateShort` indevido. Em Tóquio, `00:00Z` vira 09:00 do mesmo dia e a mutação **sobrevive** —
  "consertar" esses testes para um fuso distante os ENFRAQUECE. Os casos estão comentados no lugar
  (`BlocoDaAgenda.test.tsx`, `CrmPage.test.tsx`).
- ⚠️ **Marca gravada não se compara com a função que a gravou.** `EntradaDoDia.test.tsx` afirmava
  `localStorage.setItem(CHAVE, today(FUSO))` e o componente lia `today(fuso)`: o teste comparava o
  código consigo mesmo e passava com qualquer fuso. Agora a marca é uma **string literal**
  (`"2026-08-17"`) com o relógio congelado num instante em que Tóquio, São Paulo e UTC discordam.
- **A correção só vale verificada POR MUTAÇÃO.** Para cada asserção consertada, troque a leitura de
  produção para o fuso do navegador (`today(fuso)` → `localYmd(new Date())`, ou
  `formatX(iso, fuso)` → `formatX(iso, Intl.DateTimeFormat().resolvedOptions().timeZone)`) e confirme
  que o teste **morre**. Sem isso a correção é cosmética. Restaure por **cópia do arquivo**, nunca
  por `git checkout` num arquivo com trabalho não commitado.
- ✅ **A mesma classe FORA de quem mocka `useFuso` — fechada pela issue #129.** `grep useFuso` não
  achava `pagar/ComprovantePage`, `pagar/PagarPage` e `cobrancas/CobrancasPage`: eles montavam
  "hoje" na mão, com `d.getFullYear()/getMonth()/getDate()`. **A regra que fica é a do recorte:** um
  teste que monta "hoje" com as partes locais de um `Date` está afirmando sobre o **navegador**,
  mesmo quando o `expect` fala do tenant — então o grep que caça esta classe é
  `getFullYear|getMonth\(\)|getDate\(\)|toISOString\(\)\.slice\(0, ?10\)`, não `useFuso`.
  `ComprovantePage` migrou para Tóquio + relógio congelado (3 asserções, 2 mutações mortas cada);
  `PagarPage` ficou no fuso do runner **com a razão escrita** (o campo vem de
  `dataPadrao={pagando.due_date}` — nenhum relógio participa) e ganhou só o relógio congelado, que
  é o que dá dentes ao `not.toBe(hoje)`.
- ✅ **Os dois achados da #129 viraram a issue #136 e estão PAGOS (2026-08-19).** Eram:
  (1) `CobrancasPage` passava `dataPadrao={hojeISO()}` — o dia do NAVEGADOR — e não importava nada
  de `store/auth`; (2) na bandeja de `ComprovantePage`, o default do campo vinha de
  `localToday(fuso)` (**tenant**) e o `avisoDeDataFutura`/`tetoDaDataDeBaixa` comparavam com
  `hojeISO()` (**navegador**), então com o tenant em Tóquio a tela abria acusando de futuro o valor
  que ela mesma acabara de preencher. O alcance real era **15 call sites em 6 arquivos**, não as
  "5 telas" do enunciado: `contas.ts` também lia o relógio por dentro de uma função pura.
- ✅ **`hojeISO()` não existe mais.** Nenhum alias, nenhum `@deprecated`: todos os seus call sites
  eram default ou validação de campo de data em tela de dinheiro — a classe que o PR #78 moveu para
  o fuso do tenant. Uma segunda porta com esse nome é o convite a reintroduzir o defeito pelo
  autocomplete. O comentário que dizia *"local (e não UTC) de propósito"* foi **substituído** (não
  apagado) por um bloco em `contas.ts` explicando por que a frase ficou falsa: ela foi escrita antes
  do #78 e opunha as duas únicas opções que existiam então — navegador e UTC —, sem considerar a
  terceira, que hoje é a régua. Quem precisar de "hoje" numa tela: `today(useFuso())`.
- ⚠️ **A regra que fica, e ela é maior que o fuso:** *default preenchido por um relógio e validado
  por outro é defeito mesmo quando os dois relógios coincidem — a coincidência é ambiente, não
  garantia.* O conserto do defeito 2 **não foi escolher qual relógio**: foi não haver dois.
  `useEscolhaDaBaixa` resolve `today(useFuso())` **uma vez**, e o default, o `aviso` e o `max` bebem
  todos dali; quem quer o campo em "hoje" passa a sentinela `HOJE_DO_TENANT` em vez de uma string
  montada na tela. Não é convenção — é impossível divergir, porque não existe um segundo lugar de
  onde divergir.
- ⚠️ **Função pura não busca o "hoje" por dentro — recebe.** `impedimentoDaTransferencia` era
  anunciada como PURA e chamava `hojeISO()` escondida atrás da assinatura; agora recebe `hojeYmd`
  como 5º parâmetro, mesmo precedente de `filtroPadrao(hojeYmd)` em `pagar/filtros.ts`. É o que
  torna o teste **capaz de afirmar sobre fuso**: enquanto o relógio mora dentro, um fuso distante
  não tem o que matar.
- ⚠️ **`useState(() => today(fuso))` é mutante EQUIVALENTE onde há efeito de reset.** Medido na
  #136: mutar os inicializadores de `AccountModal`, `DeclararSaldoModal`, `LancarMovimentoModal` e
  `TransferirModal` para o relógio do navegador **não mata teste nenhum** — o `useEffect` de
  `[open]`/`[account]` sobrescreve o valor antes de qualquer paint. Quem for medir mutação nesses
  arquivos deve mirar a **linha do efeito** (`setPostedAt(today(fuso))`), não o inicializador; nos
  quatro casos a mutação do efeito mata. Não é motivo para apagar os inicializadores.
- **Onde o `new Date()` vivo FICA, e por quê:** `agenda/AgendaPage.test.tsx` monta o evento de
  fixture a partir do relógio só para ele cair no mês que a tela abre — nenhum `expect` compara esse
  valor com o que a tela calculou, e a prova de agrupamento por dia do tenant mora em `grade.test.ts`.
  **Com a razão escrita no arquivo** — sem ela, o próximo leitor que rodar o grep o "conserta" e
  enfraquece o que já estava certo.
  ⚠️ **`financeiro/contas.test.ts` SAIU desta lista** (#136). A justificativa antiga — *"compara
  duas strings numa função pura que resolve 'hoje' sozinha; sem dois relógios, um fuso distante não
  tem o que matar"* — era verdade **enquanto o hoje era interno**, e deixou de ser quando virou
  parâmetro. Hoje o bloco roda com o relógio congelado e bordas literais do calendário do tenant.
- ✅ **A dívida da `crm/ClientDetailPage` está PAGA (issue #145, 2026-08-19).** Ela era a única das
  seis telas tocadas pela #136 sem arquivo de teste nenhum — e não é tela de leitura: dispara
  `POST /receivables/charges/{id}/settle-externally` com `bank_account_id` e `received_on`, a mesma
  ação de dinheiro da `CobrancasPage`. Agora são **32 testes** em `ClientDetailPage.test.tsx`
  cobrindo doze blocos de comportamento, e **30 de 30 mutações morreram** — nenhum sobrevivente,
  todas com `tsc` limpo (mutação que não compila mata o teste por erro de módulo, não pela
  asserção, e não conta). As duas que valem registro, porque eram invisíveis enquanto a tela não
  tinha teste: `dataPadrao={HOJE_DO_TENANT}` → `localYmd(new Date())` morre com
  `expected '2026-08-16' to be '2026-08-17'` (tenant em Tóquio, relógio congelado em
  `2026-08-17T02:30:00Z`), e `received_on: corpo.paid_on` → `paid_on:` morre no payload do POST.
- ⚠️ **Um instante congelado que separa só DOIS relógios deixa o terceiro sem medição — escolha
  o que isola o do TENANT, nunca o que isola o do navegador** (#145). São **três** relógios nesta
  casa, não dois: tenant, navegador e **UTC** (o terceiro é histórico real — é o
  `toISOString().slice(0, 10)` que o #78 tirou das telas de dinheiro). Medido nos dois instantes:

  | Instante | tenant (Asia/Tokyo) | UTC | navegador (America/Sao_Paulo) | quem fica sozinho |
  |---|---|---|---|---|
  | `2026-08-17T02:30:00Z` | 2026-08-17 | 2026-08-17 | 2026-08-16 | o **navegador** — cego para UTC |
  | `2026-08-17T16:00:00Z` | 2026-08-18 | 2026-08-17 | 2026-08-17 | o **tenant** — mata os dois |

  Com o de 02:30Z (herdado da `CobrancasPage`), mutar `dataPadrao={HOJE_DO_TENANT}` para
  `new Date().toISOString().slice(0, 10)` **SOBREVIVEU** aos 32 testes de `ClientDetailPage`: o
  `expect` do dia comparava 17/08 com 17/08. Com o de 16:00Z as duas regressões possíveis morrem na
  MESMA linha, com a mesma mensagem (`expected '2026-08-17' to be '2026-08-18'`).
  ⚠️ **Dois-contra-um é o máximo alcançável — não tente "melhorar".** Tóquio só passa do dia de UTC
  a partir das 15:00Z e São Paulo só fica atrás do dia de UTC antes das 03:00Z; as condições são
  mutuamente exclusivas. Varredura dos 48 instantes de meia em meia hora de um dia: **0** separam
  os três em três dias, **18** isolam o do tenant. `CobrancasPage.test.tsx` e
  `ComprovantePage.test.tsx` ainda usam o de 02:30Z e têm o mesmo ponto cego — **dívida aberta**,
  não medida aqui.
- ⚠️ **Destino de rota com texto FIXO não mede navegação — ele tem de ecoar o parâmetro** (#145).
  Medido: com `<Route path="/funis/:id" element={<p>Tela do funil fun-1</p>} />`, trocar
  `navigate(/funis/${j.funnel_id})` por `${j.id}` **sobreviveu** aos 32 testes — o destino
  renderiza igual para qualquer id. Com o destino lendo `useParams()`, a mesma mutação morre. É a
  família do `toContain("flex-wrap")` do §5.1 aplicada a rota: a asserção existia e não tinha como
  falhar. Vale para os cinco `navigate()` desta tela, cujos prefixos (`/contratos`, `/orcamentos`,
  `/juridico`, `/funis`) são escritos à mão e parecidos entre si.
- ⚠️ **Uma linha pode precisar dos DOIS fusos — um por ramo — e o `dt()` desta tela é o caso.**
  `const dt = (s, tz) => (s.length === 10 ? formatDay(s) : formatDate(s, tz))`: mutá-la para
  `formatDate` sempre só morre no fuso **negativo** do runner (`due_date` `"2026-09-16"` vira 15/09
  em UTC−3; em Tóquio vira o mesmo dia 16 e o mutante **sobrevive**), e mutá-la para `formatDay`
  sempre só morre em **Tóquio** (`created_at` `"2026-08-20T23:00:00Z"` é 21/08 lá e 20/08 aqui).
  Escolher um fuso só para o arquivo inteiro deixaria metade da linha sem medição — é a régua "nem
  toda asserção com data deve trocar de fuso" aplicada dentro de uma expressão só.

- ✅ **`toHaveValue("2026-10-10T09:00")` num `datetime-local` é asserção sobre a MÁQUINA — paga
  pela issue #185 (2026-08-21).** O HTML define o valor desse input como "naive": as partes locais
  de quem abriu a tela, sem fuso. Cinco testes `.tsx` afirmavam essa string literal enquanto o nome
  deles falava do tenant, e eram **invisíveis ao job de mutação** — `vitest.mutation.config.ts`
  exclui `.tsx`, então o Stryker nunca os executou nem para reprovar. Não quebravam: o
  `env: { TZ }` do `vitest.config.ts` chega a tempo sob o pool `forks`. Quebravam sob `threads`, que
  é o que o `@stryker-mutator/vitest-runner` força — a mesma armadilha do #169, um andar acima.
  **Medido varrendo os 74 arquivos da suíte** (não os 21 "sensíveis a fuso": o recorte por grep
  depende do grep, a suíte inteira não): com o pin de fuso do config neutralizado, **6 falhas em 3
  arquivos** sob UTC. Agora **0** nos `.tsx` sob UTC, `America/Sao_Paulo`, `Asia/Tokyo` e
  `America/New_York`.
  **A regra que fica:** campo de hora se lê pelo INSTANTE, nunca pela string —
  `src/test/paredeDoTenant.ts` faz `new Date(el.value)` (desfaz exatamente o que o navegador
  escreveu) e formata no fuso do tenant. O mesmo resultado em qualquer máquina, e a afirmação passa
  a ser sobre o relógio de que o teste fala.
  ⚠️ **Ida e volta não substituem a prova de fuso.** Com tenant e máquina no mesmo fuso, elas se
  cancelam por construção: mutar `instanteNoFuso(...)` para uma string ingênua **sobrevive** aos
  quatro testes de fuso-do-runner e só morre no de Tóquio (`expected '11/10/2026 02:00' to be
  '10/10/2026 14:00'`). Um arquivo precisa dos dois tipos de teste, e é por isso que os testes de
  costura (`BlocoDaAgenda`) continuam no fuso do runner **com a razão escrita**.
  ⚠️ **O jsdom sanitiza o `datetime-local`, e isso cria mutante EQUIVALENTE de formato.** Medido:
  `"…T09:00:00"` e `"2026-10-10 09:00"` (separador em branco) voltam os DOIS como `"…T09:00"` —
  nenhuma leitura de `el.value` pode matá-las, nem a antiga nem a nova. Quem for triar sobreviventes
  de `paraInputLocal` não perca tempo aí. O que a sanitização **não** desfaz é segundo diferente de
  zero (`"…T09:00:30"` → `"…T09:00:30.000"`), e só uma asserção de FORMA o pega: `paredeDoTenant`
  formata hora e minuto e devolveria "09:00" na mesma. Por isso o `toMatch(/^…T\d{2}:\d{2}$/)` fica.
  ⚠️ **Dívida aberta:** `grade.test.ts` tem **duas** dependências do fuso do navegador, não uma. A
  do `eventYmd` (linha 468) é o gabarito — legítima, declarada no nome e no comentário, e o relógio
  que a serve é UM só (o `env` do config + a guarda do #172); mexer nela criaria o segundo relógio
  que esta seção existe para proibir. A **segunda não estava declarada e não aparecia na varredura
  em UTC**: `"eventsOfDay filtra pelo dia e ORDENA por horário de início"` usa um evento às
  `18:00Z`, que em `Asia/Tokyo` cai no dia SEGUINTE e some do filtro. Varrer só em UTC não fecha a
  classe — UTC e UTC−3 concordam sobre o dia de `18:00Z`, Tóquio não.

### 5.3 O teste de mutação (`apps/web/stryker.config.mjs`, desde 2026-08-18)

**A suíte verde não prova que os testes seguram alguma coisa.** Na PR #119 o QA achou NOVE
defeitos com 693 testes verdes, 32 medições de 360px e `tsc`/`eslint` limpos. Quem os achou foi
**mutação**: desfazer uma linha da produção e ver se algum teste morre. Este arquivo já registrava
"provado por mutação" em cinco lugares (o `>` vs `>=` do `posted_at` que sobreviveu a 58 testes
verdes, o `begin_nested()` do ledger de IA, o `_proximo_marco` da Vima, as cores origem × tag do
Kanban, os 5 de 5 do `grade.ts`) — sempre à mão, sempre dependendo de alguém lembrar. Deixou de
depender (issue #121).

- **Como roda:** `pnpm --filter @e1p/web mutation` (tudo) ou `… mutation --mutate <arquivo>` (um
  módulo). No CI: `.github/workflows/mutation.yml`, **noturno (`schedule`) e `workflow_dispatch`,
  NUNCA por PR** — meia hora de espera por PR vira "sobe assim mesmo" na segunda semana, e um check
  que se aprende a ignorar é pior que nenhum. O relatório HTML sai como artefato `mutation-report`.
- **O escopo é DESCOBERTO, não listado:** todo `src/**/*.ts` com um irmão `<nome>.test.ts` do lado
  — **26 módulos hoje**, ~3.470 linhas. Mesma escolha do filtro por marker `rls_e2e` no `ci.yml`:
  o módulo seguinte entra sozinho. `.tsx` está **fora** (mutação em React é lenta e ruidosa).
  ↳ Isto **já aconteceu, na mesma tarde**: o merge da `main` (PR #125) trouxe
  `features/pagar/filtros.ts` com teste irmão, e o escopo passou de 25 para 26 sem ninguém editar
  a config. É o comportamento desejado — mas note a contrapartida: **a tabela de baseline abaixo
  não se atualiza sozinha**. Módulo novo entra na medição e fica fora do registro até alguém
  medir. Ao ver um módulo no relatório que não está na tabela, meça e acrescente.
- ⚠️ **A corrida exclui os testes `.test.tsx`** (`vitest.mutation.config.ts`). É a diferença entre
  "o teste DEDICADO prende a lógica" e "algum teste de componente passou por ali de raspão" — e
  vale 5,5x em tempo (74s → 13,5s no ciclo base). O erro que isso introduz tem direção conhecida:
  a régua pode pedir teste **a mais**, nunca a menos.
- **O limiar de reprovação é 80** (`thresholds.break: 80`, desde 2026-08-21). Nasceu `null` de
  propósito — limiar antes da primeira medição é número sem evidência — e virou número quando
  houve medição, mesmo caminho de `secret-scan`/`sast-semgrep`/`frontend`: observável primeiro,
  bloqueante depois. Ele compara com o **score GLOBAL** (a linha "All files", que inclui os
  mutantes sem cobertura), nunca com o de um arquivo: `app/navigation.ts` mede 55,65% e **não**
  derruba o job sozinho. A aritmética dos 80 está comentada no `stryker.config.mjs`; o resumo é
  que 1 ponto ≈ 17,8 mutantes e a folga de ~3,5 pt absorve um módulo novo entrando pelo escopo
  descoberto sem que nenhum teste existente tenha piorado.

**Baseline no CI — 83,52%** (2026-08-21, run `32478357936`, `main` em `e422278`, runner de 2 vCPU,
**12min56s**). 1.779 mutantes em **27 módulos**: 1.479 mortos, 1 timeout, 269 sobreviventes, 23 sem
cobertura, 0 erros. É desta corrida que saiu o limiar acima, e é a **primeira que o job noturno
completou**: as três anteriores (19, 20 e 21/08) abortavam no dry run por fuso — o runner do GitHub
roda em UTC e o `env: { TZ }` do `vitest.config.ts` não pega no pool `threads` que o Stryker força
(issue #169; conserto no `env:` do job em `.github/workflows/mutation.yml` + guarda fail-closed em
`src/test-setup.ts`).

↳ O 27º módulo é **`features/busca/resultado.ts`** (18 mutantes, 72,22%, 5 sobreviventes), que
entrou pelo escopo descoberto depois de 18/08 e por isso **não está na tabela abaixo** — é
exatamente a contrapartida avisada acima. A tabela que segue continua sendo a medição local de
2026-08-18 (12 vCPU, 26 módulos), preservada pelo par antes/depois da triagem da issue #121.

**Baseline MEDIDO** (2026-08-18, Node 24, 12 vCPU, `--concurrency` default; ~21 min em quatro
lotes para os 1.605 mutantes; **os 25 módulos de então foram medidos, nenhum ficou de fora** — o
26º, `filtros.ts`, chegou depois pelo merge e foi medido à parte, na mesma data). "Antes" é a
primeira corrida; "depois" é a mesma medição após a triagem desta issue. Global: **79,25% →
82,73%**.

| Módulo | Mutantes | Antes | Depois | Sobrev. | Sem cob. |
|---|---:|---:|---:|---:|---:|
| `lib/theme.ts` | 13 | 84,62 | **100,00** | 0 | 0 |
| `crm/origem.ts` | 8 | 100,00 | 100,00 | 0 | 0 |
| `financeiro/costCenters.ts` | 10 | 100,00 | 100,00 | 0 | 0 |
| `financeiro/dre.ts` | 13 | 100,00 | 100,00 | 0 | 0 |
| `financeiro/lucratividade.ts` | 21 | 100,00 | 100,00 | 0 | 0 |
| `financeiro/dreMatrix.ts` | 48 | 97,92 | 97,92 | 1 | 0 |
| `agenda/grade.ts` | 177 | 73,45 | **95,45** | 8 | 0 |
| `pagar/duplicar.ts` | 68 | 91,18 | 91,18 | 6 | 0 |
| `financeiro/ledger.ts` | 19 | 78,95 | **89,47** | 2 | 0 |
| `financeiro/contas.ts` | 320 | 87,50 | 87,19 | 39 | 2 |
| `financeiro/periodRange.ts` | 67 | 80,60 | **86,57** | 9 | 0 |
| `financeiro/contratoDre.ts` | 20 | 85,00 | 85,00 | 3 | 0 |
| `financeiro/dreMatrixEntries.ts` | 13 | 69,23 | **84,62** | 2 | 0 |
| `financeiro/investimentos.ts` | 58 | 84,48 | 84,48 | 9 | 0 |
| `lib/idleTimer.ts` | 37 | 83,78 | 83,78 | 6 | 0 |
| `financeiro/conferencia.ts` | 174 | 82,18 | 82,76 | 29 | 1 |
| `cobrancas/rota.ts` | 36 | 80,56 | 80,56 | 4 | 3 |
| `lib/uploadPublicImage.ts` | 10 | 80,00 | 80,00 | 1 | 1 |
| `financeiro/diagnostico.ts` | 84 | 78,57 | 78,57 | 14 | 4 |
| `financeiro/projecao.ts` | 101 | 74,26 | 76,24 | 23 | 1 |
| `lib/datetime.ts` | 66 | 75,76 | 75,76 | 8 | 8 |
| `financeiro/planoContas.ts` | 19 | 73,68 | 73,68 | 5 | 0 |
| `pagar/baixa.ts` | 82 | 60,98 | 65,79 | 25 | 1 |
| `lib/shareInbox.ts` | 26 | 61,54 | 61,54 | 9 | 1 |
| `app/navigation.ts` | 115 | 55,65 | **55,65** | 51 | 0 |
| `pagar/filtros.ts` ¹ | 77 | 77,92 | 77,92 | 17 | 0 |

**O que a primeira medição achou, e o que virou teste.** Nenhum destes era visível com a suíte
verde:

- **`grade.ts` tinha 28 mutantes SEM COBERTURA** — `addDays`, `startOfWeek`, `sameDay`,
  `hojeDoTenant`, `gradeDoMes`, `eventYmd`, `eventsOfDay` e `paramsDaGrade` não tinham nenhum teste
  dedicado. A ironia: o docstring do módulo diz que essa aritmética foi extraída **exatamente** para
  os dois calendários não divergirem. A regra estava escrita; o teste, não. Trocar `+ n` por `- n`
  em `addDays` não quebrava nada.
- **`runwayLabel(days: 0)` passava com os DOIS programas.** `toContain("0 dias")` é verdade tanto na
  frase de alarme ("Caixa no limite (0 dias)") quanto no caminho de baixo, onde `parts` vazio cai no
  `|| "0 dias"`. Família do `toContain("flex-wrap")` da §5.1, num número de caixa.
- **O empate de data invertia o extrato.** `a.date > b.date` → `>=` REVERTE lançamentos do mesmo dia
  em `ledger.ts` e `dreMatrixEntries.ts`. Todos os testes usavam datas distintas — e um dia com dois
  pagamentos é o caso comum, não a borda.
- **Julho é um mês cego para `this_quarter`.** `Math.floor((m - 1) / 3)` → `(m + 1) / 3` dá o MESMO
  trimestre em julho. Em março dá um trimestre inteiro no futuro. Julho era o único mês testado.
- **As âncoras do `HEX_RE` não eram validadas.** Sem o `$`, `"#112233ff"` (RGBA de 8 dígitos, o que
  um seletor de cor de verdade devolve) entraria no `generateScale` como se fosse RGB.
- **`avisoContasPagasAnteriores` com `count: 0`** só era testado com as datas também nulas — quem
  derrubava era o `!oldest_paid_on`, nunca a guarda de contagem.
- **`last_month` fora de janeiro nunca executava.**

**Os dois `// Stryker disable`, e por que cada um.** Não são atalho: a razão está escrita ao lado no
código.

1. `grade.ts` — o `-1` de `corte` é **mutante equivalente** (o exemplo que a própria #121 cita).
   `corte` só aparece em `if (inicio <= corte)`, e `inicio` começa em `HORA_ABERTURA * 60` = 480:
   −1, 0 e +1 produzem a mesma grade. Não há teste possível — são o mesmo programa.
2. `baixa.ts` — `ALTURA_DA_BARRA` é uma **medida do DOM**, e as duas asserções que existem são de
   um lado só (`< 320` e `pb >= altura`): pegam a barra crescendo, não encolhendo. Unit test aqui
   só copiaria a soma para o outro lado do `expect`.

**Dívida (medida, não estimada):**
¹ Entrou no escopo pelo merge do PR #125 (2026-08-18), depois da corrida das quatro lotes; medido
isoladamente na mesma data, sem triagem — os 17 sobreviventes dele estão no total abaixo.

- ⚠️ **271 sobreviventes e 22 sem cobertura continuam de pé** (254 da primeira corrida + 17 do
  `filtros.ts`), e a triagem acima cobriu a ponta de
  maior sinal, não o conjunto. Os três piores por score são `app/navigation.ts` (55,65% — **51
  sobreviventes, o maior débito único do frontend**), `lib/shareInbox.ts` (61,54%) e `pagar/baixa.ts`
  (65,79%). Dos 333 sobreviventes originais, **153 eram `StringLiteral`** — rótulos e constantes de
  contrato com o backend, que unit test nenhum confere; separar esse ruído do sinal (via
  `mutator.excludedMutations`) é pré-requisito para qualquer limiar honesto.
- ⚠️ **A barra da `ComprovantePage` não é medida em `e2e/`.** É o que fecharia o disable do
  `ALTURA_DA_BARRA` de verdade — hoje o número não é verificado por nada.
- ⚠️ **`contas.ts` tem mutantes que oscilam entre `Timeout` e `Survived`** conforme a carga da
  máquina (4 timeouts na primeira corrida, 1 na segunda). Timeout conta como morto no score, então
  o número desse módulo balança ~0,3 ponto entre corridas. Ler variação pequena como regressão é
  o primeiro jeito de o job noturno perder credibilidade.
- ⚠️ **O limiar ainda não existe.** Com o baseline acima medido, o próximo passo é um `break` por
  módulo em `stryker.config.mjs` — depois de um período de observação, e nunca acima do que a
  tabela mostra.

### 5.4 A régua de ALCANÇABILIDADE de controle (`e2e/alcance-360.spec.ts`, issue #144, 2026-08-19)

**A régua do #135 é cega para a metade oposta do problema, e é cega por construção — não por
fresta.** `main` é `overflow-x-hidden` (`AppShell.tsx:64`): um botão que não cabe **não empurra o
documento**, ele é **RECORTADO**. `document.documentElement.scrollWidth` continua devolvendo 360,
verdinho, com o botão inalcançável. As duas classes se parecem no sintoma e são opostas no
mecanismo:

| | #135 (`rotas-360.spec.ts`) | #58 / #144 (`alcance-360.spec.ts`) |
|---|---|---|
| O que acontece | o elemento **escapa** do recorte e empurra o documento | o elemento é **recortado** e fica preso atrás dele |
| Como se detecta | `scrollWidth` do documento > 360 | posição do controle vs. a borda alcançável |
| Sintoma | a página rola de lado | o botão não existe para o dedo |

Foi assim que o #144 se escondeu: a varredura de 18 rotas do PR #141 visitou `/funis/f1`, a `marca`
provou que a tela renderizou, a largura deu **360** — e o «Salvar» começava em **x=514** numa tela
de 360px, **inteiramente** fora. Num celular não havia como salvar um funil.

- **A régua** é `controlesInalcancaveis` em `e2e/support/medidas.ts`. Ela pergunta, de cada
  `button`/`a[href]`/campo **visível**: a borda direita passa da borda alcançável (a menor entre a
  viewport e a de **todo** ancestral que recorta) **e** não há ancestral que **role** na horizontal
  para trazê-lo de volta?
- ⚠️ **O critério NÃO é "termina depois de 360" — e a diferença não é acadêmica.** Medido nestas
  rotas, "termina depois de 360" acusa **13 controles que estão certos**: os **12** botões de valor
  da DRE de 12 meses (dentro de um `overflow-x-auto` que rola — o deslizador existir e funcionar) e
  o «Gerar com IA» do carrossel (dentro do painel de edição com `overflow: auto`, a **20px** da
  borda). Régua com 13 falsos positivos é descartada na primeira semana, e leva junto os defeitos
  de verdade que ela carrega. **Prova por mutação:** tirar a cláusula do deslizador deixa **5
  testes vermelhos** — 4 rotas (`/financeiro/dre`, `/marketing/m1`, `/marketing/novo`,
  `/orcamentos/novo`) e o controle negativo.
- **UMA coleta, dois filtros.** `alvosPequenos` (44px) e `controlesInalcancaveis` são duas
  perguntas sobre o **mesmo** conjunto de elementos, e passam pelo mesmo `medirControles` — o
  seletor de controle e a função `visivel` existem uma vez só. Duas cópias divergiriam no primeiro
  dia em que alguém corrigisse apenas uma.
- **O catálogo de rotas mudou de casa:** `e2e/support/rotas.ts` (fixtures de pior caso + `marca` +
  mocks), percorrido pelas **duas** réguas. Duas cópias garantiriam que uma medisse uma tela que a
  outra não mede.
- ⚠️ **Os DOIS controles no fim do spec são o que impede o arquivo de virar enfeite**, e nenhum é
  cortesia. O **positivo** planta um botão recortado pelo `main` e exige que a régua o veja
  (mutação "régua cega" → morre); o **negativo** planta um botão igualmente fora da tela **dentro
  do deslizador da DRE**, prova pelo número que ele está além dos 360px, e exige que a régua **NÃO**
  o acuse. Sem o primeiro ninguém sabe se ela enxerga; sem o segundo, se ela sabe parar.
- **A ÚNICA exclusão, com a razão e o número:** `EXCECOES_DE_ALCANCE = [".react-flow"]`. A lona do
  construtor de funis é movida por `transform` (pan/zoom no dedo): não há `overflow-x` nenhum para
  a régua encontrar, e ela é **maior que qualquer tela por construção** (a fixture tem um nó em
  x=900). Medido: sem a exceção, `/funis/f1` acusa **2** falsos positivos — a aresta
  `g [Edge from n1 to n2]` (direita **531**) e a `div` do nó (**493,5 → 568,5**) — que nenhum
  conserto de layout resolve. Os **controles de tela** do construtor (cabeçalho, paleta, painel)
  ficam FORA de `.react-flow` e continuam medidos: é lá que morava o #144.

**Os defeitos que ela achou sozinha** — a issue reclamava de `/funis`; três dos cinco a régua
descobriu por conta própria, e todos estão consertados neste PR (medidos em 360×740, fixtures de
pior caso):

| Rota | Controle | x → x | |
|---|---|---|---|
| `/funis/novo` e `/funis/:id` | «Automação» | 389,2 → 506 | **inteiramente fora** |
| `/funis/novo` e `/funis/:id` | «Salvar» | 514 → 604 | **inteiramente fora** |
| `/funis/novo` e `/funis/:id` | «Apresentação» | 250,6 → 381,2 | parcial |
| `/financeiro/centros-custo` | «Editar» | 637,4 → 687 | **inteiramente fora** (novo) |
| `/financeiro/centros-custo` | «Arquivar» | 699 → 763,3 | **inteiramente fora** (novo) |
| `/sites/:id` | «Salvar» | 310 → 400 | parcial (novo) |
| `/sites/:id` | `<a>` do bloco "botão" | 65 → 691,3 | parcial (novo) |
| `/orcamentos/novo` | «Salvar» | 286,4 → 376,4 | parcial (novo) |

Em `/financeiro/centros-custo` os dois estavam **inteiramente** fora: **não dava para editar nem
arquivar um centro de custo num celular de 360px**. O `<a>` do bloco "botão" vale também na
**página pública** (`PageBlocks.tsx` é o mesmo componente), onde ele é a única conversão que existe:
rótulo longo sem espaço media **626px** de largura.

**Cobertura: 30 das 47 rotas não-públicas de `App.tsx`** — **43 no `ProtectedLayout`** (com shell:
sidebar + topbar) **+ 4 no `ProtectedBareLayout`** (sem shell). **17 de fora**, e as duas caixas
falham por motivos diferentes:

**14 do `ProtectedLayout`.** `/`, `/config`, `/crm`, `/financeiro/conferencia` **quebram com o mock
default `[]`** (endpoint que devolve objeto) e precisam de fixture própria — medido: as quatro
renderizam **em branco** (`pageerror` real: `reading 'some'`/`'trim'`/`'filter'`/`'map'`), e a
`marca` as reprovaria, que é o comportamento certo. `/agenda`, `/crm/clients/:id`,
`/conversas/:chatId`, `/financeiro/contratos/:id/dre`, `/orcamentos/:id`, `/contratos/:id`,
`/juridico/novo`, `/juridico/:id` (as duas últimas exigem `?skill=`) e `/admin` (exige
`is_platform_admin`) pedem fixture ou sessão própria. `*` (ComingSoon) não tem controle.

**3 do `ProtectedBareLayout`** (eram as 4 da categoria INTEIRA até o #178): `/dna/nucleo`,
`/compartilhar`, `/comprovante/:id`. **Nenhuma das três está no catálogo** — não por triagem, por
omissão do denominador. E não são periferia: o comentário do próprio `App.tsx` diz que
`/dna/nucleo` é **"desenhado para 360px"**, e `/comprovante/:id` é **tela de dinheiro** que já
carrega dívida de medição registrada no §5.1 (*"Segue de pé a dívida da `ComprovantePage` … aquela
tela não está entre as medidas"*) — o `ALTURA_DA_BARRA` do `baixa.ts` tem seis mutantes
sobreviventes justamente porque o número é medida do DOM e ninguém mede aquela tela. **Não foram
medidas nesta issue de propósito** (o pedido era o número honesto, não mais cobertura): se
alguma tiver defeito, vira issue própria com o número medido.

⚠️ **`/vima` saiu dessa lista no #178, e o que ela tinha escondido era defeito de verdade.** É a
PORTA DO DIA (`EntradaDoDia` manda a raiz autenticada para lá enquanto o briefing de hoje não foi
lido — a primeira tela do dono no aparelho de 360px, de manhã) e era a **única das seis telas que
montam `GanchoDaVima`** sem régua nenhuma. Uma entrada em `e2e/support/rotas.ts` com o payload de
pior caso na forma real do `BriefingOut` reprovou **na primeira medição**: `documentElement
.scrollWidth` **649px** numa viewport de 360. Causa: `linhas[].texto` e a narração repetem nomes
**digitados pelo dono** (fornecedor, título do prazo, nome da conversa — `vima/absences.py`), e um
token sem espaço não tem onde quebrar; sem shell **não há `main.overflow-x-hidden`** para recortar,
então o que não cabe vaza e a página inteira rola. Conserto: `break-words` nos dois lugares —
medidos **um a um**, a narração sozinha vale **649px** e a lista sozinha **525px**.

⚠️ **Nesta rota as duas réguas NÃO são independentes, e a razão é estrutural.** Sem shell não há
ancestral que recorte: o que estoura empurra o documento, e `medirControles` **absolve** todo
controle quando a página rola (`deslizador = "document"`). Logo, hoje, quem tem dente aqui é a
régua do #135; a do #144 só acusa se alguém introduzir um recorte. Medido no #178: `overflow-hidden`
no contêner + «Ir para o painel» em largura fixa de 600px → `alcance-360` acusa **272px além da
borda** e `rotas-360` continua devolvendo **360**. É exatamente por isso que a entrada vale nas
DUAS listas: a segunda é a guarda do dia em que essa tela ganhar um cartão com recorte.

⚠️ **COMO RECONTAR — a régua que impede o próximo erro deste parágrafo, que já aconteceu DUAS
vezes seguidas.** Conte `<Route path=` nas **DUAS** caixas de layout (`ProtectedLayout` **e**
`ProtectedBareLayout`), e conte também a forma **multilinha**, no espírito do *"Conte `<Modal` para
o total, nunca só o import"* acima:

```bash
grep -c '<Route path=' apps/web/src/app/App.tsx   # 50 — só a forma de UMA linha
grep -cE '^\s*path="' apps/web/src/app/App.tsx    # 1  — a rota `/` quebrada em 8 linhas
# 50 + 1 = 51 rotas com path; menos as 4 públicas (/login, /orcamento/:slug,
# /contrato/:slug, /p/:slug) = 47 não-públicas.
```

Os dois modos de errar, os dois medidos em 2026-08-19 ao escrever esta seção: **(a)** contar só o
`ProtectedLayout` e perder as 4 sem shell — 43 em vez de 47; **(b)** contar só `<Route path=` de
uma linha e perder a rota **`/`**, que é escrita em 8 linhas por causa do embrulho
`<EntradaDoDia>` — 42 em vez de 43. É a mesma família do *"18 arquivos que eram 19"* do §5.1
(`IdleWarningModal` escapando do `grep components/Modal` por importar por caminho relativo): o
elemento que **se escreve diferente** some da conta, o numerador e o denominador param de fechar
entre si, e ninguém percebe porque o número parece alto.

**Achado fora do escopo, não consertado:** `/financeiro/centros-custo` corta **texto** em 13
lugares — o nome do centro sobra **215,5px** e a tabela "Resultado por centro de custo" sobra de
**306,5px** a **699,5px** (cabeçalhos e todas as células). É a classe de `textoForaDaTela`, não a de
alcançabilidade, e não há régua verde para ela nesta rota. Medido também que `break-words` no rótulo
do nome **não muda o número** (o `span` é item de flex com `min-width: auto`, então nunca chega a
quebrar) — mudança que nenhuma régua vê é peso morto, e por isso ela não entrou.

**A TERCEIRA régua de `/financeiro/centros-custo` (#181, 2026-08-21) — e o que ela ensina sobre as
duas anteriores.** A mesma tela já tinha passado em duas réguas e continuava com **3 alvos abaixo
do mínimo tocável de 44px**, medidos com `alvosPequenos` no documento inteiro em 360×740:

| Elemento | Antes | Depois |
|---|---|---|
| `input[type=checkbox]` «Mostrar arquivados» (área do `<label>`) | 13×13 (rótulo de **20px**) | rótulo de **44px** |
| `button` «Editar» do cartão | 49,6 × **16** | 57,6 × **44** |
| `button` «Arquivar» do cartão | 64,3 × **16** | 72,3 × **44** |

Os dois botões são **exatamente os que o #144/PR #156 tornou alcançáveis**: alcançáveis, e de 16px.
É a lição cara desta rota — **verde em `alcance-360` e em `centros-custo-360` não diz nada sobre
tamanho de alvo**, porque as três perguntam coisas diferentes (o dedo CHEGA? a TINTA cabe? o alvo
tem TAMANHO de dedo?). Consertado com o precedente de `ContasSaldosPage.tsx`: `min-h-[44px]` nas
duas ações e na **linha inteira** do rótulo do checkbox — nunca engordando o `<input>`, que
viraria um quadrado do tamanho de um botão. Travado por `apps/web/e2e/toque-360.spec.ts`, com
varredura de `alvosPequenos` no documento inteiro (não só nos três alvos conhecidos).

- ~~**Dívida:** o modal de cadastro/edição desta rota tem **2** alvos abaixo de 44 — o `<input>` do
  `Field` (**38px**) e o `<select>` de tipo (**39px**).~~ **PAGA no #215** (2026-08-22), e a
  contagem de 2 era piso: eram **79 campos em 16 telas**. Ver "Campo de digitação" abaixo.
- **Dívida (estreitada no #215):** a varredura filtrava TODO `input` por construção — `alvosPequenos`
  mede o ELEMENTO, e a caixinha do checkbox tem 20×20 por convenção do repo. O custo estava escrito
  no spec ("um campo de TEXTO de 38px passaria por aqui") **e foi cobrado**: os 2 alvos acima eram
  exatamente isso. `Alvo` passou a carregar `tipo` e o filtro hoje recorta só `checkbox`/`radio`.
  O que continua sendo mutante equivalente: tirar o `h-5 w-5` do `<input>` (volta a 13×13) e o
  `px-1` dos botões — a régua exige ÁREA de toque, não quadrado desenhado.


### 5.5 As suítes pesadas não se sobrepõem (issue #162, 2026-08-20)

**`pytest -q`, `pytest -m rls_e2e` e `pnpm e2e` NÃO rodam ao mesmo tempo — e uma falha obtida sob
concorrência NÃO conta como sinal.** Nem como sinal de que há bug, nem como sinal de que não há.
Ela não é evidência de nada: é para ser jogada fora e refeita em série.

**O mecanismo, e por que ele custa caro.** O sintoma honesto seria "timeout por carga". Não é o que
aparece. As três suítes disputam CPU, disco e Docker; o que sai na tela é `AssertionError` no
backend e `locator not found` no Playwright — exatamente o que uma regressão de VERDADE diria. Não
há nada na mensagem que separe "seu diff quebrou isto" de "a máquina estava cheia". Quem roda as
três em paralelo para economizar relógio tem dois destinos, e os dois são caros: investigar um bug
que não existe, ou — pior — catalogar como "aquele flake" uma quebra que era real.

O **único** sinal secundário é o **tempo**, e ninguém o lê no meio de uma investigação: quando o
teste está vermelho, a atenção vai para a asserção, não para o rodapé com a duração. Números
**citados da issue #162** (medidos lá, não remedidos aqui): sob concorrência a `pytest -q` foi de
**21min para 48min** e o Playwright de **1,9min para 9,2min**. Observado em **duas sessões
independentes** durante o #146 (PR #158) — `test_financial_intelligence_profitability_rls.py`
(FAILED sob concorrência, `3 passed in 28.32s` isolado), `agenda-evento-360.spec.ts` ×2 (FAILED,
`4 passed (43.2s)` isolado) e `test_ai_usage_rls.py` (FAILED, `1 passed in 6.55s` isolado). O
terceiro veio de uma **reconferência separada**, com o diff já verificado: a classe reincide e não
depende de qual branch está na árvore.

**Não é classe nova — é a mesma, um nível acima.** O #147 (PR #148) já a fechou **dentro** do
Playwright pondo `workers: 1` como padrão: *"o paralelo inventa falhas"* — 14 vermelhos espalhados
por specs sem relação contra os 2 que a mesma mutação produz serialmente (ver o cabeçalho de
`apps/web/playwright.config.ts`). O `mutation.yml` fecha a mesma coisa com `concurrency:` (*"a
segunda mediria contenção de CPU, não qualidade de teste — e é assim que timeout vira falso
positivo"*). E o `apps/web/vitest.config.ts` já carrega a terceira instância: `testTimeout: 15000`
existe porque `PlatformUsers.test.tsx` e `ContractBuilderPage.test.tsx` estouravam os 5000ms
default *"só sob a suíte completa em paralelo — isolados, ambos passam"*. Três lugares, a mesma
física. O que faltava era a proteção **ENTRE** as suítes.

- **O alvo único é `bash scripts/gates.sh`** (issue #162). Encadeia as três **em série**, na ordem
  do `ci.yml` (mais barata primeiro): `scripts/check.sh` → `pytest -m rls_e2e` → `pnpm e2e`. Falha
  rápido (`set -euo pipefail`): etapa vermelha aborta o encadeamento e as caras nem começam.
  **Imprime o tempo de cada etapa** — é a forma de pôr na tela o sinal fraco que ninguém lê.
- **Preflight que não se pula:** sem `pnpm` ou sem Docker respondendo, o script reprova ANTES da
  etapa 1, em vez de descobrir isso 20 minutos depois. E a etapa de RLS carrega a **mesma guarda
  anti-skip-silencioso do `ci.yml`** (lê o `--junitxml` e exige ≥ 1 teste REALMENTE executado):
  `rls_e2e` que se pula sozinho fica verde sem ter exercido RLS nenhuma.
- ⚠️ **`gates.sh` não é um lock.** Ele torna o modo certo o mais fácil; não impede que alguém abra
  outro terminal — ou outra worktree do mesmo repo — e rode `pnpm e2e` por cima. A contenção
  continua sendo responsabilidade de quem digita. O lock de arquivo foi considerado e **não** foi
  feito (issue #162, opção 2).
- **Em worktrees paralelas:** `E2E_PORT=5373 bash scripts/gates.sh`. A 5273 colide entre checkouts
  do próprio e1p (#123, §5.1); com `reuseExistingServer: false`, porta ocupada vira erro alto em
  vez de medição do branch alheio.
- **O teste de mutação (`pnpm --filter @e1p/web mutation`, ~21min) é a QUARTA suíte pesada** e
  **não** entra no `gates.sh`: é diagnóstico periódico da qualidade da suíte, não portaria de
  mudança (§5.3, e o cabeçalho de `mutation.yml`). Se você o rodar à mão, ele conta para esta regra
  igual às outras três — não o sobreponha a elas.
- ⚠️ **Quem for cronometrar as suítes não está exercitando fuso.** `TZ=UTC` **não troca o fuso no
  Windows**: a variável chega ao Python, mas o fuso local não muda (`apps/api/tests/test_search_deep.py`
  documenta). Por isso `gates.sh` **não mexe em `TZ`** — um `TZ=...` na frente destas suítes daria a
  impressão de estar exercitando fuso sem exercitar nada. A régua do fuso é a do §5.2 (mock do fuso
  do **tenant**), nunca a variável de ambiente da máquina.

**O que fazer quando a falha aparece.** Antes de abrir o editor: pergunte se havia outra suíte
rodando. Se havia, o resultado é **descartado** — não é "flake", não é "bug", não é nada. Rode
`bash scripts/gates.sh` com a máquina só para você e leia o que sair de lá. Só esse resultado entra
numa investigação, num comentário de PR ou numa Completion Note.


### 5.6 A régua da BORDA DO CARD (`e2e/card-largo-360.spec.ts`, issue #182, 2026-08-21)

**A terceira pergunta sobre a mesma tela, e as duas primeiras são cegas para ela — cada uma por um
motivo diferente.** Com título de pior caso (74 chars sem espaço), em 360×740:

| | #135 (`rotas-360`) | #58/#144 (`alcance-360`) | **#182 (`card-largo-360`)** |
|---|---|---|---|
| O que mede | `scrollWidth` do documento | `boundingBox` de CONTROLE vs. a borda alcançável | **borda direita do que foi DESENHADO** (`x + width`, ou `x + scrollWidth` quando o elemento não recorta a si mesmo) |
| Por que é cega para o #182 | `main` é `overflow-x-hidden`: o card é recortado, não empurra o documento — **360 nas cinco rotas** | a CAIXA do `<button w-full>` mede 312px e cabe; o que vaza é a TINTA, e `getBoundingClientRect` não vê tinta | — |

**As cinco rotas medidas, e o que cada uma devolvia antes do conserto** (`textoForaDaTela`, escopo
`main`; `documentElement.scrollWidth` = **360** em todas as cinco):

| Rota | Sobra além da borda | Controle levado junto |
|---|---|---|
| `/funis` | **+316px** (nome do funil, e a linha "N componentes" junto) | — |
| `/juridico` (documentos) | **+213,5px** | lixeira `absolute right-3` em **x 583,5 → 597,5, INTEIRAMENTE FORA** |
| `/juridico` (skills) | **+187,5px** (rótulo e tipo de saída) | card de skill parcialmente fora (24 → 563,5) |
| `/sites` | **+264px** (título da página) | — |
| `/produtos` | **+264px** (nome) e **+315,8px** (etiqueta "Inativo" empurrada para x=624) | — |
| `/financeiro/investimentos` | **+264px** (nome da conta e rótulo do índice) | — |

**Os dois mecanismos, e o conserto de cada um:**

1. **Trilha de grade `auto`.** `grid gap-2 sm:grid-cols-2` sem contagem de colunas no breakpoint
   base tem UMA coluna implícita de tamanho `auto`, e trilha `auto` cresce com o min-content. Só
   `/juridico` estava assim, e é a única em que a CAIXA do card crescia — levando junto o que está
   `absolute` dentro dela. Conserto: `grid-cols-1`, que o Tailwind escreve `repeat(1, minmax(0,
   1fr))`; é o `minmax(0, …)` que segura.
2. **Item de flex com `min-width: auto`.** Ele não encolhe abaixo do próprio min-content, e o
   min-content de uma palavra sem espaço é a palavra inteira. Conserto: **`min-w-0` no item de
   flex + `break-words` no bloco de texto, nessa ordem** — `break-words` sozinho quebra a palavra
   DENTRO da caixa, e a caixa é que estava larga demais (é o mesmo "não muda o número" já medido
   no §5.4). Onde o texto é bloco dentro de bloco (`/sites`), `break-words` sozinho basta.

- ⚠️ **A `marca` desta régua é o TÍTULO DO CARD, nunca o da página.** As cinco rotas estavam
  catalogadas em `support/rotas.ts` como `// vazio`: a régua visitava, não havia card nenhum, e
  "nada fora da borda" era o resultado — verde por não ter desenhado nada. É por isso que o defeito
  atravessou o #135, o #144 e o #160. Cada caso do spec tem um teste irmão que reprova com payload
  `[]` (a marca do card some, a da página fica), e `/funis` e `/juridico` saíram do estado vazio no
  catálogo TAMBÉM, com `marca: LONGO`. **Prova por mutação:** esvaziar `FUNIS_LONGOS` deixa as
  **três** réguas vermelhas na marca ("element(s) not found"), nunca verdes.
- ⚠️ **`produtos-vender-360` já usava um nome de 74 chars, e mesmo assim não via** — ele aponta
  `textoForaDaTela` para dentro do modal de venda (`'[data-testid="modal-vender-produto"]'`), e o
  card da lista nunca esteve no escopo. Fixture de pior caso não mede nada sozinha: quem mede é o
  escopo.
- ⚠️ **Escopo `main`, de propósito.** `textoForaDaTela` mede contra a borda do ancestral que
  RECORTA, e um deslizador horizontal legítimo (a DRE de 12 meses, o Kanban) tem conteúdo fora dessa
  borda por construção. Nenhuma das cinco rotas daqui tem deslizador.
- **O controle positivo** planta um `<p white-space: nowrap>` no `main`, prova pelo número que a
  CAIXA cabe (`right <= 360`) e que a página não rola (360) — o disfarce exato da classe — e exige
  que a régua veja a tinta. Mutação "régua cega" (`sobra > 0.5` → `sobra > 1e9`): morre.
- **Mutante equivalente, medido e dispensado:** `break-words` na descrição da skill não muda número
  nenhum, porque `line-clamp-3` já é `overflow: hidden` e ela RECORTA em vez de vazar. Não entrou —
  mudança que nenhuma régua vê é peso morto (§5.4).

**Achado fora do escopo, não consertado:** em `/marketing`, `textoForaDaTela` acusa **+808,4px** num
`div` dentro do `CarouselThumb`. Não é defeito do produto: o thumb desenha a arte em 1080px e a
encolhe com `transform: scale()` dentro de um `overflow: hidden` (`CarouselSlideView.tsx:182-185`), e
`scrollWidth` é medido ANTES do `transform`. É um falso positivo da régua na mesma família da
exceção `.react-flow` do §5.4, e por isso `/marketing` **não** entrou no catálogo do
`card-largo-360`. O card de `/marketing` em si está correto (`truncate` + `min-w-0` + `grid-cols-2`)
— medido, zero sobra.

## 6. Estado atual / roadmap
- [x] Fundação do monorepo, docs, agentes de QA, CI local.
- [x] Core do backend: tenancy (RLS) + anonimizador + camada de IA + auditoria.
- [x] Shell do frontend (sidebar/topbar/layout do design "Portal") + Cockpit (esqueleto).
- [x] **Módulo auth + tenant** (register/login/me, JWT, RBAC, RLS na migration 0001). 24 testes.
- [x] **Módulo Agenda** (eventos, detecção de conflitos, CRUD, transições de status, paginação; migration 0002). 43 testes no total.
- [x] **Módulo CRM & Kanban** (clientes, estágios dinâmicos, board, mover card, segmentação; barramento de eventos `core/events`; migration 0003). 61 testes no total.
- [x] **Cockpit** (agregador read-only de Agenda + CRM: contagem do dia, críticos pendentes, funil/conversão; financeiro como placeholder). 70 testes no total. **→ Fase 1 COMPLETA.**
- [x] **Frontend ligado à API** (login só-acesso, telas Agenda/CRM/Cockpit funcionais, botões criam de verdade). Cor `#5D44F8` + sidebar no formato "Portal" + logout.
- [x] **Super Admin (Master)** — dashboard de plataforma: criar/listar/suspender/excluir contas; `is_platform_admin` (migration 0004); seed via env; delete atômico com purga dinâmica de tabelas de negócio. 77 testes.
  - [x] **Área de usuários (hierarquia, "ver/editar/excluir todos os usuários")** — `GET /admin/users` devolve a **hierarquia**: cada escritório (Admin/dono = `role=owner`) → **funcionários** (`role=sub_user`) → **clientes** (compradores, agregados de `Enrollment` por e-mail/nome com contagem de compras). Contas internas da plataforma (Master) são omitidas. O Master **cadastra funcionário** (`POST /admin/accounts/{tenant_id}/users` — name/email/senha + `allowed_modules`; vazio = acesso a tudo), **edita** (`PATCH /admin/users/{id}` — nome/ativo/módulos) e **exclui** (`DELETE /admin/users/{id}`) qualquer usuário; o **dono** (owner) só sai com a conta inteira (`delete_account`); o Master nunca é editável/excluível por aqui. Sem migration (reusa `users`/`tenants`/`enrollments`). Front **reorganizado p/ menos poluição** (`features/admin/AdminDashboard.tsx` + `PlatformUsers.tsx`): configurações (split/ganhos) numa **caixa recolhível** (`Collapsible`), **busca** + **um cartão por escritório recolhido por padrão** que expande ao clicar (Admin + funcionários add/suspender/excluir + clientes read-only + excluir conta). Tabela flat antiga removida (não duplica mais). Validado e2e no Postgres.
  - [x] **Convite de usuário (cadastro completo + senha por e-mail/WhatsApp + troca no 1º acesso)** — **TODO novo usuário** (funcionário E dono de conta) exige **nome completo, CPF (`document`), endereço, e-mail e WhatsApp (`phone`)** + canal `delivery` (email|whatsapp); a plataforma **gera senha temporária**, marca `must_reset_password=True` e a **envia** (`core/email.py` stub + `core/whatsapp.py`; em dev viram log). Funcionário: `POST /admin/accounts/{tenant_id}/users` → `StaffInviteOut`. Conta/dono: `POST /admin/accounts` agora é por **convite** → `AccountInviteOut` (não pede mais senha na tela). Ambos trazem `temp_password` (mostrada uma vez ao Master) + `delivery_status`. **1º acesso:** login com a temporária → `must_reset_password` no token/`/me` → o front (`ProtectedLayout` → `FirstAccessPage`) bloqueia o app até `POST /auth/change-password {new_password}` (limpa o flag). Migration 0029 (users: document/address/phone/must_reset_password). `config.smtp_host` (vazio=log). 252 testes. Validado e2e (convite de conta/funcionário → login temp → troca → temp 401 / nova 200).
  - [x] **/admin redesenhado em ABAS** (`AdminDashboard.tsx`): **Escritórios** (cartões recolhíveis: Admin + funcionários add/suspender/excluir + excluir conta; clientes saíram daqui, vira só contador), **Clientes** (`PlatformCustomers.tsx` — `GET /admin/customers` lista plana de todos os compradores com escritório de origem; **cards com avatar colorido por iniciais**, e-mail, escritório e nº de compras, com busca) e **Configurações** (split/ganhos). **Dívida:** cliente comprador ainda NÃO é `User` de login (vive em Enrollment); Admin (dono) sem tela PRÓPRIA de equipe (só o Master cadastra hoje); provedores REAIS de e-mail (SMTP/SES) e WhatsApp Cloud API; convite por link em vez de senha visível ao Master.
- [x] **Recuperação de senha** — `/auth/forgot-password` + `/auth/reset-password` (token sha256 + expiração 1h, single-use); botão na tela de login; migration 0005. 81 testes. **Pendente: provedor de e-mail** — em dev o token volta na resposta (`dev_reset_token`); em produção precisa SMTP/WhatsApp p/ entregar o link.
- [x] **Agenda detalhada (estilo Google Agenda)** — evento com local, convidados, link de reunião (Meet/Zoom), dia-inteiro, descrição (migration 0006). **Kanban com drag-and-drop** (HTML5 nativo, move otimista). 83 testes.
- [x] **Agenda calendário** (visões Mês/Semana/Dia, navegação, clicar no dia cria evento). **Sidebar fixa** (sticky + min-w-0; Kanban rola sem mover o menu). **Etapas criar/arquivar** no Kanban (arquivar remaneja clientes; migration 0007). **Notificação WhatsApp ao mover card** (barramento `crm.client.moved` → `notifications`, stub `core/whatsapp`). 85 testes.
- [ ] **Integração WhatsApp Cloud API** — PENDENTE: hoje as notificações ficam `logged` (sem entrega). Precisa `WHATSAPP_TOKEN`+`WHATSAPP_PHONE_ID` (Meta) e um **campo de telefone do owner** (não existe ainda — recipient usa o e-mail como placeholder). O envio ao mover card NÃO é mais síncrono no request (Story 4.3): `on_client_moved` só enfileira uma `Notification` `pending`; o worker (`app.worker`) entrega depois, fora da request.
- [ ] **Integração Google (Meet/Calendar)** — PENDENTE: gerar Meet automaticamente exige OAuth Google (Google Cloud project + Calendar API). Hoje: campo manual + botão que abre meet.google.com/new. É o módulo 6 (API Hub) da spec — fazer quando o usuário fornecer credenciais Google.
## Fase 2 — dinheiro entra/sai (em andamento)
- [x] **Carteira & Split** — transações com split 40/30/20 (produto/serviço/recorrente), saldos (disponível/a receber/sacado), settle (libera cartão), payout (saque, com lock FOR UPDATE), painel de ganhos da plataforma p/ o Master (`platform_earnings` global). Dinheiro em centavos BigInteger. Cockpit mostra faturamento líquido real. Migration 0008. 99 testes.
  - **Dívida:** estorno (`refunded`) ainda sem caminho de execução nem reversão do `platform_earnings`. Payout real precisa integração bancária + KYC (hoje só marca withdrawn). Antecipação de recebíveis não implementada.
- [x] **Contas a Receber** — cobranças (boleto/Pix/link com código stub), baixa (`/pay` simula webhook) → cria Transaction na Carteira com split (atômico, com lock FOR UPDATE contra baixa dupla), vencimento injetado na Agenda (cobranca_receber), resumo de inadimplência (a vencer/vencido/recebido). Migration 0010. 107 testes.
  - **Dívida:** gateway real (Asaas/Mercado Pago) p/ gerar boleto/Pix de verdade + webhook real; régua de cobrança (lembretes automáticos) + juros/multa; estorno; ~~`is_overdue`/summary usam dia em UTC~~ — **corrigido em 2026-08-05** (ver §6.0 "o sistema inteiro passou a viver no fuso do tenant").
- [x] **Cockpit: painel de inadimplência + Cobrar com IA** — o dashboard (acima da agenda) lista clientes em atraso; botão por cliente dispara `/receivables/charges/{id}/collect`: a IA (Claude, com `[NOME]` como placeholder p/ não vazar PII; fallback template se não houver chave) escreve uma cobrança amigável e registra uma Notification de WhatsApp (rastro de IA). 110 testes.
- [x] **Contas a Pagar** — despesas (categoria, fornecedor, recorrência), vencimento na Agenda (cobranca_pagar), marcar paga (com lock), resumo (a pagar/semana/mês/pago), categorias. Cockpit "Custos do Mês" agora é real. Migration 0011. 118 testes.
  - **Dívida:** OCR de boleto (IA lê PDF e preenche fornecedor/valor/vencimento) — não implementado; auto-geração de contas recorrentes (precisa scheduler); anexo de comprovante.
- [x] **Agenda clicável + detalhe do evento** — todo evento abre um modal central; para `cobranca_receber` mostra os dados da cobrança + **histórico de mensagens** ao cliente + **Cobrar com IA** e **mensagem manual**; para `cobranca_pagar` mostra os dados da conta. Notification ganhou `client_id` (migration 0012) p/ o histórico por cliente. 122 testes.
- [x] **Produtos & Checkout** (estrutura Super Membros: Produtos / Cupons / Alunos) — produtos (físico/digital/membros), cupons (% ou fixo, único por tenant), venda aplica cupom + cria Transaction na Carteira com split de produto + matricula o Aluno (atômico); link de checkout (stub). Migration 0013. 130 testes. **→ FASE 2 COMPLETA.**
  - **Dívida:** checkout público real (página + gateway), entrega automática (infoproduto: link/arquivo; físico: baixa de estoque + tarefa de envio), área de membros real.
## Fase 3 — documentos & fechamento de venda (em andamento)
- [x] **Central de Orçamentos** — itens/quantidades/desconto com totais, status (rascunho→enviado→aprovado/recusado), enviar (notifica cliente), **efeito dominó** (aprovar gera a cobrança em Contas a Receber, ATÔMICO via `receivables.build_charge` + lock + guarda de total>0), descrição de escopo por IA. Migration 0014. 140 testes.
  - Refactor: `receivables.build_charge` (sem commit) reutilizável; `create_charge` virou wrapper.
- [x] **Construtor de proposta (estilo Super Membros)** — editor em abas **Serviços / Dados / Imagens / Cronograma / Contrato / Aparência** com prévia ao vivo, e **link público** que o cliente abre SEM login (senha opcional) e **aceita** → dispara o dominó. Migration 0015. 147 testes.
  - Link público: `quotes` tem RLS; ao salvar copiamos um SNAPSHOT só-de-exibição p/ `published_proposals` (tabela GLOBAL sem RLS) por `slug`. Rota pública lê via `get_db`; o aceite abre `tenant_session(snap.tenant_id)` (injetado por `get_tenant_session_factory`, sobrescrito nos testes) e chama `approve_quote`. QA de segurança: sem vazamento cross-tenant, senha fail-closed antes de aprovar, idempotente (FOR UPDATE). Slug `token_urlsafe(12)`; `<img src>` com guarda de esquema.
  - **Dívida:** upload real de imagem/logo (hoje por URL — precisa storage S3); PDF do orçamento; status "visualizado"; rate-limit em `/public/proposals/*`; aceite público hoje funciona em rascunho (decidir se exige "enviado"); derivar snapshot do schema `PublicProposal`.
- [x] **Construtor de Contratos + Assinatura & KYC** — contratos por **cláusulas reordenáveis (drag-and-drop)** com variáveis `[CLIENTE]/[VALOR]/[OBJETO]/[DATA]/[EMPRESA]` (auto-preenche CLIENTE/DATA/EMPRESA), **templates** padrão por tenant (Prestação de serviços, NDA), status rascunho→enviado→assinado/cancelado, e **link público de assinatura** sem login: cliente informa nome+CPF/CNPJ (KYC) + aceite → registra assinatura (nome, documento, **IP**, data) e marca assinado (idempotente, FOR UPDATE). Migration 0016. 156 testes. Mesmo padrão público das propostas (snapshot global `published_contracts` sem RLS); o **documento do KYC NÃO vai no snapshot público**.
  - **Dívida:** PDF assinado + hash/carimbo de tempo; verificação real de documento (KYC forte).
- [x] **Efeito dominó COMPLETO (Aprovação Inteligente)** — aprovar/aceitar um orçamento com a aba "Contrato" ativada gera, no MESMO commit, a **cobrança** (Contas a Receber) E o **contrato** (rascunho, ligado por `quote_id`, cláusulas vindas de itens/valor/pagamento/contract_text). `contracts.build_contract_from_quote` (sem commit) chamado por `quotes.approve_quote` (import lazy, sem ciclo). 158 testes. **→ FASE 3 COMPLETA.**
  - Validado e2e: cliente aceita no link público → cobrança + contrato nascem juntos.
- [x] **Área do Cliente / Ficha 360°** — `/crm/clients/:id`: editar dados do cliente (nome/contato/tags/obs), resumo financeiro (a vencer/vencido/recebido), e abas **Cobranças** (receber, **trocar vencimento** → move o evento da agenda junto, **protestar** vencidas), **Contratos** e **Orçamentos** do cliente (links pras fichas). Backend: filtros `?client_id=` em `/receivables/charges`, `/contracts`, `/quotes`; `POST /charges/{id}/reschedule` (atualiza `due_date` + AgendaEvent); `POST /charges/{id}/protest` (campo `protested_at`, só vencida+aberta, idempotente). Migration 0017. 166 testes. **→ FASE 3 COMPLETA.**
  - **Dívida:** "Documentos" como conceito próprio (hoje a aba mostra Contratos); histórico de conversas/agendamentos na ficha; protesto real via cartório/serviço.

## Fase 4 — Marketing & Conteúdo (em andamento)
- [x] **Gerador de Carrossel (Redes Sociais)** — `/marketing`: gera slides + **legenda + hashtags** com IA a partir de um tema (`core/ai` + fallback estruturado), 3–10 slides; **estilo EDITORIAL** (capa/editorial/accent/cta, 4:5) baseado na skill real do usuário `docs/skills/carrosseis-instagram.md` [[e1p-carrossel-skill]]: header (Powered by e1p / @handle / mês ano ®) + rodapé com numeração, título CAIXA ALTA com palavra em destaque, fotos opcionais (URL), fundo sólido/foto+overlay. **Templates personalizáveis** (Editorial/Moderno/Minimalista/Gradiente/Jurídico/Vibrante) + cores/fonte livres. **Export PNG no navegador (html2canvas)** — replica o HTML→PNG da skill (que usava Playwright), por slide ou "baixar todos", 1080×1350. Migrations 0018-0019. 173 testes.
  - **Dívida:** Unsplash (fotos automáticas) e Apify/Reddit (trends) precisam das chaves PRIVADAS do usuário — plugar depois; brand kit salvo por tenant; publicação/agendamento no Instagram; export ZIP/PDF; gestor de tráfego (Meta Ads) e métricas. (Token do Apify que veio no zip foi REDIGIDO ao salvar a skill no repo.)
- [x] **Construtor de Funil de Vendas** — `/funis`: canvas **React Flow** drag-and-drop com paleta de **88 componentes em 5 categorias** (Gatilhos/Lógica/Ações/Comunicação/Tráfego, coloridas), nós conectáveis (handles), arestas animadas, minimap/controles, **modo apresentação** (esconde UI), **export PNG** (html2canvas) e salvar/excluir. Backend `Funnel` (RLS) guarda nós+arestas no formato React Flow; `GET /funnels/components` serve o catálogo. Migration 0020. 180 testes. Fiel ao markdown [[e1p-funil-vendas]].
  - UX (commit `4cfb0f1`): painel "Configurações Rápidas" (editar rótulo/descrição, ID/chave, remover nó), clicar para adicionar, "Compartilhar" (copia link), toasts.
  - Visual (commit a seguir): nós **coloridos** com 2 formas — **páginas quadradas com mockup** (25 componentes-página: vendas/captura/checkout/obrigado/...) e **nós redondos com ícone** por categoria (63). Catálogo do backend marca `shape: page|node` (PAGE_KEYS). Páginas têm **"Modelo de página"** (Vendas/Captura/Obrigado/Checkout/Download/Webinar/Conteúdo) no editor.
  - **Conteúdo nos nós** (commit a seguir): clicar num nó abre editor de conteúdo por tipo — **e-mail** (assunto+corpo), **WhatsApp/SMS** (mensagem), genérico (texto) — com **gerar por IA** (`POST /funnels/ai-compose {kind,prompt}` → core/ai + fallback). Conteúdo salvo em `node.data.config`; nó com conteúdo mostra um ponto verde. 182 testes.
  - **Executar nó (ações REAIS internas)** (commit a seguir): `POST /funnels/run-node {action, client_id, params}` dispara a ação de verdade — `create_client` (Lead/Adicionado ao CRM → cria contato), `add_tag`, `create_quote` (Emissão de Proposta → orçamento real), `create_charge` (Emissão de Boleto/Gerou Pix → cobrança real, com split ao pagar), `send_email`/`send_message` (registra Notification + WhatsApp stub). Catálogo marca `action` por componente; front mostra "▶ Executar ação" com modal de campos + seleção de cliente. Reusa serviços validados; teto de valor R$100M (422); isolamento por RLS (db.get do client de outro tenant → None → 422). QA adversarial: SEGURO. 188 testes.
  - [x] **Motor de automação (executa o funil inteiro a partir de um gatilho)** — `funnels/engine.py`: **estado por contato** (`FunnelRun`, RLS: status running/waiting/done/failed/cancelled, `current_node_id`, `resume_at`, `steps` log) + **runtime do grafo** (`_drive` anda pelos edges executando a AÇÃO REAL de cada nó via o `run_node` já validado) + **espera** (nó `esperar` pausa até `resume_at`; delay configurável min/horas/dias) + **agendador** (`POST /funnels/runs/tick` retoma esperas vencidas — idempotente, chamável por cron OU pela tela; sem worker em background ainda, ver core/events.py) + **condicional** (`se-ou`: ramo Sim/Não por condição simples — tem-tag / pagou / sempre, via `sourceHandle` 'sim'/'nao' ou ordem). Gatilho = **inscrição** (`POST /funnels/{id}/enroll {client_id, start_node_id?}`; entrada = nó sem aresta chegando). Guarda anti-ciclo (100 passos); falha de ação → run `failed` com a mensagem, sem derrubar a request; `create_client` com contato já inscrito → pulado. Endpoints: enroll, `GET /funnels/{id}/runs`, `GET/POST /funnels/runs[...]` (list/tick/get/cancel). Params da ação vêm do `node.data.config` (valor/método/tag/delay/condição — configuráveis no painel "Configurações Rápidas" do builder). **Front:** botão "Automação" abre drawer (inscrever contato + lista de jornadas com status + "processar esperas agora" + linha do tempo dos passos). **Integração:** Ficha 360° do CRM mostra "Jornadas no funil" do contato. Migration 0028. 242 testes. Validado e2e no Postgres (enroll→espera→tick→done + isolamento RLS).
  - **Dívida:** envio REAL (provedor de e-mail, WhatsApp Cloud API, gateway) — hoje as ações usam os serviços internos + stubs; ~~cron/worker durável para o tick~~ **FEITO (Story 4.3):** worker durável (`app.worker`, serviço `worker` nos docker-compose) dispara o tick periodicamente e processa a fila de notificações (`notifications` com `status=pending`) fora do request; pendente agora é só o auto-enroll por evento (lead criado/tag aplicada via core/events) em vez de inscrição manual; fan-out (um contato seguir múltiplos ramos); condições mais ricas; link público do funil; templates prontos.
- [x] **Controle de Estoque** (módulo 4 da spec) — `/estoque`: itens com quantidade/custo/mínimo/unidade, **ledger de movimentações** (entrada/saída com motivo: compra/ajuste/perda/venda), **alertas de estoque baixo** (quantidade ≤ mínimo), resumo (itens/valor total/baixos), e **baixa automática na venda** (StockItem ligado a um Produto via `product_id` → `consume_for_product` chamado por `products.sell` na MESMA transação, com FOR UPDATE). Ajustes não deixam quantidade negativa (409). Migration 0021. 194 testes.
  - **Dívida:** IA lê anotação/áudio p/ dar baixa de extras (spec); kits/composição; relatório de giro/curva ABC; baixa por serviço (não só produto).
- [x] **Configurações + Brand Kit** — `/config`: perfil da empresa (nome/CNPJ/contato/site/sobre) + **Brand Kit** (logo, cores primária/secundária/destaque/texto/fundo, fonte) com prévia ao vivo. Backend `TenantProfile` (RLS, 1 por tenant, criado sob demanda com defaults do `legal_name`/`document`); `GET/PATCH /settings/profile`. Migration 0022. 198 testes. **Reuso:** proposta nova herda logo+cores do Brand Kit; carrossel novo herda cor primária/destaque/fonte (mantendo o fundo editorial).
  - **Dívida:** upload real do logo (hoje URL); aplicar brand kit também em contratos/PDF; config de integrações (chaves) nesta tela.
- [x] **Sites / Páginas** — `/sites`: construtor de landing pages por **blocos** (título/texto/imagem/botão/formulário/vídeo/divisor), **modelos** (vendas/captura/obrigado/checkout/download/webinar/conteúdo) com template inicial, herda o **Brand Kit** (cores/fonte/logo). Editor com prévia ao vivo + reordenar blocos; **publicar** gera o snapshot público. **Página pública** sem login em `/p/:slug` (mesmo padrão de propostas: `Page` RLS + `published_pages` global; `public_view` só após publicar). **Formulário de captura → cria LEAD no CRM** (source=landing) via `tenant_session`. Migration 0023. 204 testes.
  - **Dívida:** rate-limit/anti-spam no formulário público; mais blocos (depoimentos, FAQ, preço); subdomínio/domínio próprio; ligar a página ao nó-página do funil (referência mútua); A/B; analytics.
## Fase 5 — Assistente Jurídico (em andamento)
- [x] **Assistente Jurídico** (módulo do `~/lex-intelligentia-app` migrado para dentro do e1p) — `/juridico`: catálogo de **21 skills jurídicas** em 5 categorias (essenciais/magistratura/pesquisa/automação/criação). O usuário escolhe a skill → preenche um **wizard dinâmico** (formulário vindo do `wizard_config` JSON) → opcionalmente **anexa peças** (PDF/Word/imagem/txt, texto extraído por `core/extract.py` — reusa pdfplumber/python-docx/pytesseract) → a **IA redige o documento** usando o `SKILL.md` da skill como prompt-sistema + **protocolo anti-alucinação** (jurisprudência classificada em 3 níveis, nunca inventa números). **Regra de Ouro nº 2:** todo o texto (respostas + anexos) é **anonimizado** (`core/anonymizer`) ANTES de ir ao Claude e desanonimizado localmente na volta — segredo de justiça. A resposta é separada em **corpo + seção METADADOS** (frameworks, jurisprudências citadas, avisos de revisão). Documento gerado (`LegalDocument`, RLS) com tokens, status, e **vínculo opcional ao cliente do CRM** (`client_id`). Download em **.docx** (`export.py`, markdown-leve→Word, unicode nativo). Sem `ANTHROPIC_API_KEY` a geração falha graciosamente (status=failed, 201). **Integração:** Ficha 360° do cliente (`/crm/clients/:id`) mostra a seção "Documentos jurídicos" vinculados. Resources (`modules/juridico/resources/`): 21 `wizard_configs/*.json` + 21 `skills/**/SKILL.md`. Migration 0027. 232 testes.
  - **Dívida:** gerar **relatório** separado (.docx) como no lex original; persistir/baixar os anexos enviados (hoje só o texto extraído é usado, arquivo é descartado); editar/regenerar documento; versionamento; export PDF; OCR exige tesseract instalado no container (já em requirements, validar no build de produção); skills com `references/` extras não são carregadas (só o SKILL.md raiz).

## Anexos (upload de arquivos)
- [x] **Módulo de Anexos** — `/attachments` (RLS): upload REAL de arquivos (PDF/JPEG/PNG, ≤10MB) ligados a uma entidade por `owner_type`+`owner_id` (ex.: payable, charge) e `label` (boleto/contrato/outro). Bytes no Postgres (`LargeBinary`) — simples e isolado por tenant; migrar p/ S3 é dívida. POST multipart (UploadFile), GET lista por owner, GET `/{id}/download` (Response com content-type + Content-Disposition; baixado via axios blob no front por causa do Bearer), DELETE. Migration 0025. Componente React reutilizável `components/Attachments.tsx` (upload/listar/ver/remover). 212 testes.
  - **Contas a Pagar:** modal "Boleto/Pix" agora sobe **Boleto** e **Contrato** (arquivo, não URL) + mantém o código Pix/boleto (texto). Campo `payment_code` é texto; o antigo `attachment_url` (URL) saiu da UI (coluna mantida, sem uso).
  - **Contas a Receber:** ação "Contrato" por cobrança → anexa **Contrato** (e Boleto) da cobrança.
  - **Dívida:** preview inline (hoje abre em nova aba); antivírus/scan; limite por tenant.

## Anexos: storage durável S3-compatível (Story 3.5)
- [x] **Storage S3-compatível dos Anexos** — os bytes podem sair do Postgres para um object storage S3 (`app/core/storage.py`, wrapper fino sobre `boto3` com `endpoint_url` configurável: AWS S3 real OU MinIO/B2/Wasabi barato, sem trocar código). **Dual-write/dual-read com fallback gracioso:** se `S3_BUCKET` está vazio (dev/CI/staging sem bucket), tudo continua no Postgres exatamente como antes (mesmo padrão fail-safe de WhatsApp/SMTP). Se configurado, anexo novo sobe pro bucket (`storage_key` setado, `data=None`); a leitura resolve a origem por linha, então anexo legado (pré-migração) continua baixando. Isolamento de tenant também no path da chave (`tenants/{tenant_id}/attachments/{id}/{filename}` via `build_key`), em complemento à RLS do metadado. Contrato HTTP dos 4 endpoints de `/attachments` e o componente `Attachments.tsx` **inalterados** (só persistência mudou). Migration 0039 (só estrutural: `storage_key` + `data` nullable — não toca em rede no boot). Backfill idempotente `python -m app.scripts.migrate_attachments_to_s3` (documentado em `docs/HOSTINGER-DEPLOY.md`, roda numa janela após configurar as envs). Faseável/não-bloqueante para o deploy.
  - **Dívida:** remover a coluna `data` (limpeza só depois do backfill 100% em produção); validação real contra um bucket S3/MinIO de verdade é manual (sem testcontainers p/ S3 no CI, mesma lacuna do RLS/Postgres).

### O comentário do template LIGOU o storage S3 em produção (AWS, 2026-08-20)

**A frase que dizia "storage S3 desligado" era exatamente o que o ligava.** `env_file` do Docker
Compose **não** remove comentário na mesma linha do valor — tudo depois do `=` vira o valor. O
`.env.prod.example` trazia `S3_BUCKET=   # vazio = storage S3 desligado (fallback Postgres)`, e o
`.env.prod` da AWS foi preenchido copiando o template como ele estava. Dentro do container:

| Variável | Valor real | Efeito |
|---|---|---|
| `S3_BUCKET` | `"# vazio = storage S3 desligado (fallback Postgres)"` | **não-vazio** → `is_configured()` devolve `True` |
| `S3_ENDPOINT_URL` | `"# vazio = endpoint padrão da AWS; defina p/ MinIO/B2/Wasabi"` | boto3 → `ValueError: Invalid endpoint` |

Resultado: **500 em TODO upload de anexo** — comprovante pelo celular, boleto e contrato de
Pagar/Cobranças, e a mídia recebida no WhatsApp, que **falha CALADA**
(`whatsapp_inbox/service.py` captura `Exception` amplo e registra a mensagem sem o anexo). Leitura
de anexo antigo seguia funcionando — linha legada tem `storage_key` nulo e lê do Postgres —, e foi
isso que fez o defeito parecer isolado no comprovante.

- ⚠️ **A degradação graciosa da Story 3.5 estava CORRETA e foi derrotada pela configuração.** O
  fallback nunca chegou a rodar: `is_configured()` lê só `s3_bucket`, e um bucket "preenchido" com
  a própria frase que anuncia o desligamento satisfaz a condição. **Uma feature fail-safe só é
  fail-safe até o env mentir sobre estar vazio.**
- [x] **`Settings._descarta_comentario_do_template`** (`app/config.py`) — valor de env que começa com
  `#` nos campos `S3_*` é **ausência de configuração**, e volta ao DEFAULT do campo (não a `""`:
  para `s3_region` o desligado é `"auto"`, e zerá-la entregaria região vazia ao boto3).
  - ⚠️ **Só o grupo S3, e a restrição é a decisão.** Segredo e senha podem legitimamente começar com
    `#`; descartá-los trocaria este defeito por um pior — a app subindo em produção sem a
    credencial que o operador configurou. Campo S3 novo entra em `_CAMPOS_S3`.
  - **O descarte LOGA em WARNING, e isso tem teste próprio.** Degradar para o Postgres em silêncio
    é como o defeito sobreviveu a um deploy inteiro sem ninguém notar; quem QUERIA o S3 ligado
    precisa achar a linha no log.
- [x] **`.env.prod.example`** — os comentários das duas linhas foram para **linha própria**, com o
  aviso do mecanismo escrito ali. Eram as **únicas duas** linhas do template inteiro com
  comentário inline (`grep -nE "^[A-Z_][A-Z0-9_]*=.*#"` dá zero agora).
- **A correção em produção não precisa de deploy de código:** zerar as duas linhas do
  `/opt/e1p/infra/.env.prod` e `docker compose up -d` **sem nomear serviço** (`api` e `worker` leem
  o mesmo `env_file`; `restart` **não** relê o arquivo, só o `up` relê).
- **Zerar é seguro:** o `put_object` sempre falhou ANTES do `commit`, então nenhuma linha de
  `attachments` ficou com `storage_key` apontando para um bucket — não há byte órfão.

⚠️ **A Hostinger nunca teve o defeito, e o motivo importa:** o `.env.prod` dela tem **33 linhas** (contra as ~100
do template) e **nenhum `S3_BUCKET` nem `S3_ENDPOINT_URL`** — a única linha com "s3" é
`BACKUP_S3_BUCKET`, que é o bucket do `rclone` do dump e nem é lida pelo `Settings`. Sem as
variáveis, `s3_bucket` cai no default do pydantic e o storage fica desligado. Aquele arquivo foi
escrito à MÃO; o da AWS foi montado a partir do `.env.prod.example`, e é só nisso que diferem. *"Lá
funciona"* não contradiz o diagnóstico — é a previsão dele. **Regra que fica: o `.env.prod` é
escrito à mão em cada servidor e NUNCA foi versionado, então dois ambientes com o mesmo commit
podem divergir em qualquer variável.** Ao investigar diferença entre ambientes, compare o env
antes de procurar no código — aqui o `git log` do caminho inteiro (`receipts.py`,
`attachments/`, `core/storage.py`) mostrava zero mudanças desde o PR #71, de 04/08.

- **Dívida:** nada impede a **próxima** variável não-S3 de cair na mesma armadilha — a guarda é
  deliberadamente estreita, e o que protege o resto é só o template estar limpo hoje. Um teste que
  varra `.env.prod.example` atrás de `^[A-Z_]+=.*#` fecharia a classe; não entrou aqui para não
  misturar regra nova com a correção do incidente.
- **Dívida:** `whatsapp_inbox` engole a falha de anexo em `except Exception` — durante a janela do
  defeito, mídia recebida foi perdida sem sinal nenhum ao dono. Fora do escopo desta correção.

## Anexos: comprovante pelo share sheet do celular
- [x] **Compartilhar comprovante do app do banco → Contas a Pagar** — o comprovante entra pelo
  compartilhamento nativo do celular, sem salvar arquivo antes. **Bandeja de staging** sem tabela
  nova: `Attachment` com `owner_type="receipt_inbox"`, `owner_id=<user_id>`; vincular é só trocar
  `owner_type`/`owner_id` para `payable` (os bytes não se movem — a `storage.build_key` não
  carrega o dono). A bandeja é **por usuário só por convenção nas rotas de `receipts`**
  (`get_staged` exige `owner_id == user_id`) **e isolada por tenant via RLS** — não é uma garantia
  do sistema como um todo: as rotas GENÉRICAS de `/attachments` (`GET /attachments?owner_type=
  receipt_inbox&owner_id=<id>`, `GET /attachments/{id}/download`, `DELETE /attachments/{id}`) não
  conhecem esse convênio, então outro usuário do MESMO tenant consegue listar/baixar/descartar o
  comprovante em staging de um colega (ver dívida abaixo). Rotas em `/payables/receipts` (upload,
  bandeja, `candidates`, `link`, `new-bill`, descarte). `link` anexa e dá baixa **num commit só**,
  o que exigiu extrair `apply_paid` e `build_payable` (versões sem commit) de
  `mark_paid`/`create_payable` — mesmo padrão do `receivables.build_charge`; a suíte
  `tests/test_payables.py` ficou verde sem precisar editar. **Android:** PWA instalável com
  `share_target` no `manifest.webmanifest`; o `public/sw.js` é um service worker que **não faz
  cache de nada** (só intercepta o POST do share target) — de propósito, para não introduzir a
  classe de bug "deploy novo, app velho em cache". ⚠️ `nginx.conf` ganhou `location = /sw.js` com
  `no-cache`: o regex de estáticos daria `immutable` 30d ao service worker (a mesma `location`
  também isola o `types {}` do manifest num escopo próprio — um `types {}` no nível `server`
  substituiria, em vez de estender, o `mime.types` herdado, quebrando o Content-Type de TODO o
  resto do app). **iOS:** app Atalhos + `device_tokens` (migration 0057, tabela GLOBAL sem RLS —
  mesma situação de `users`), com escopo travado em `POST /payables/receipts` — um token vazado
  só consegue depositar arquivo na bandeja do dono, nunca ler. Isolamento vem de filtro explícito
  por `user_id` do JWT (allowlist documentada em `apps/api/tests/test_tenancy_guard.py`; a tabela
  guarda só o **hash sha256** do token cru + metadado, nunca o token em si — não é criptografia,
  é hash; não é o padrão de tenant-por-token de `whatsapp_inbox`). Slot `comprovante` adicionado
  ao modal (antes o comprovante ia no campo "Contrato"). **Deslogado:** `ProtectedLayout` guarda a
  rota de origem (`state={{ from: location }}`) ao redirecionar para `/login`, e `LoginRoute`
  retoma essa origem no sucesso em vez de sempre ir para `/` — genérico para qualquer rota
  protegida, não só `/compartilhar`/`/comprovante/:id` (sem isso a chave do comprovante, que só
  existe na URL, era destruída pelo `replace` e o arquivo ficava perdido no IndexedDB).
  - **Dívida:** Contas a Receber e anexos genéricos fora de escopo; WhatsApp como porta de entrada
    fica desenhado mas não construído (o `whatsapp_inbox` já cria `Attachment` — falta apontar o
    `owner_type` para a bandeja) e depende das credenciais da Meta; sem OCR/sugestão automática da
    conta; publicação do atalho do iOS é manual, uma vez só (limitação da plataforma, não dá para
    gerar por código); ícones do PWA (192/512) são placeholder — quadrado na cor da marca com
    "e1p" em fonte padrão do PIL, maskable-safe mas para trocar por um logo real. **O isolamento
    por usuário da bandeja depende de `/attachments` ser endurecido**: hoje um tenant-mate
    consegue alcançar o comprovante em staging de outro usuário pelas rotas genéricas (ver acima);
    quem for endurecer `/attachments` (checar dono, não só tenant) precisa saber que a receipts
    inbox depende disso.
  - **Validação manual obrigatória:** `docs/CHECKLIST-COMPROVANTE-MOBILE.md` — só o share sheet
    do Android e o Atalho do iOS seguem genuinamente manuais (exigem aparelho real). O isolamento
    cross-tenant do `link` **já está automatizado** em `apps/api/tests/test_receipts_rls.py`
    (`pytest.mark.rls_e2e`, testcontainers, roda `alembic upgrade head` como o papel não-superusuário
    `e1p_app` contra um Postgres real — o mesmo teste exercita de fato a migration 0057) e no job
    `cross-tenant-rls` do CI.
  - **[CORRIGIDO pós-deploy, achado testando em Android real] `AppShell` nunca teve breakpoint
    responsivo nenhum** — sidebar de 256px fixos (`w-64 shrink-0`, sem `md:`/`sm:`) espremia
    QUALQUER tela do app num aparelho de ~360px; nesta feature isso deixou o checkbox "marcar
    como paga" fora da área visível e uma conta real foi marcada paga sem o usuário conseguir
    ver/desmarcar. Fix: abaixo de `md` a sidebar nasce fechada e abre sobreposta (`fixed` +
    backdrop, fecha ao navegar); `/compartilhar` e `/comprovante/:id` passaram a rodar em
    `ProtectedBareLayout` (mesma proteção via `useAuthGate` compartilhado, sem sidebar/topbar).
    **Só o shell + as 2 telas do comprovante foram auditados — nenhuma outra tela do app foi
    verificada quanto ao mesmo padrão.** (PR #56)
  - **[CORRIGIDO 2026-08-10] A sidebar ganhou breakpoint no #56; a TOPBAR não.** Ela era uma linha
    flex única em que **todo filho tinha `flex-shrink: 1` sem `min-width`**: a ação primária
    espremia os vizinhos e, quando não havia mais o que espremer, a linha estourava a viewport.
    Efeitos medidos em 360px, em `/financeiro/investimentos`: página com `scrollWidth` **375px**
    (rola 15px de lado), botão **"Abrir menu" com 16px de largura** — o único acesso à navegação
    no celular, num alvo que o polegar não acerta — e o campo de busca reduzido a 52px, sem
    placeholder legível. **O que decide é o COMPRIMENTO DO RÓTULO da ação primária**, não o
    `ChevronDown` (largura mínima da linha: 216px sem ação · 326px com "Nova conta" · 375px com
    "Nova conta de investimento").
    - Agora: `flex-wrap` no `header` e `order-last w-full sm:w-auto` na ação, que **desce para uma
      linha própria** abaixo de `sm` em vez de espremer — reflui, não corta (a lição do PR #58 no
      eixo em que esta barra falhava). `shrink-0` + 44px no botão de menu, nos ícones e no avatar.
      A busca (que **não tem handler nenhum** — é decoração) fica `hidden md:block` e devolve 152px
      à linha.
    - **Rótulo de ação novo e comprido não quebra mais a barra**; se quebrar,
      `apps/web/e2e/shell-360.spec.ts` pega. `/vima` e `/dna/nucleo` vivem em
      `ProtectedBareLayout` e nunca tiveram este problema.
    - **Dívida:** o campo de busca continua sem handler — escondê-lo abaixo de `md` não o liga.
      Ligar ou remover é decisão de produto.
  - **[CORRIGIDO pós-deploy, 2ª rodada de teste em campo]** Mesmo com o shell responsivo, o
    checkbox "marcar como paga" vivia num bloco SEPARADO do botão Anexar — quem selecionava a
    conta e tocava Anexar sem rolar nunca via o checkbox, e a baixa saía com o padrão (marcado)
    sem confirmação visível. Fix: checkbox + resumo da conta escolhida (nome, valor) movidos pra
    DENTRO da mesma barra fixa do Anexar — fisicamente inseparáveis da ação que os torna
    efetivos. Achado no mesmo incidente: a tabela de `PagarPage` usava `overflow-hidden` (corta)
    em vez de `overflow-x-auto` (rola, mesmo padrão de `DrePage`/`LucratividadePage`) — em tela
    estreita a coluna Status e os botões de ação (Editar/Marcar paga/**Estornar**) ficavam
    invisíveis, sem jeito de conferir ou desfazer uma baixa incorreta. (PR #58)
  - **[CORRIGIDO] `docs/HOSTINGER-DEPLOY.md` §5 estava errado** — mandava `docker-compose.prod.yml`
    sem `--env-file`, mas a VPS real (`e1p.doroeventos.com.br`) roda `docker-compose.traefik.yml`
    e EXIGE `--env-file .env.prod`, senão falha por `POSTGRES_ROOT_PASSWORD` ausente. Custou
    confusão em 2 deploys seguidos até a forma certa ser encontrada em
    `docs/RUNBOOK-BACKUP-RESTORE.md`. Corrigido e já verificado na prática (PR #57 + deploys
    seguintes rodaram §5 sem ajuste). **`main` ganhou proteção de branch nesta janela** (4 checks
    obrigatórios) — push direto agora é REJEITADO (`GH006`), toda mudança precisa de PR.

## Financeiro: boleto gera arquivo + pagamento automático (sem marcar à mão)
- [x] **Boleto gera o arquivo (PDF) e anexa** — criar cobrança com `method=boleto` (escolhido no próprio formulário de Nova cobrança) gera um **PDF de boleto** (`core/boleto.py`, fpdf2) com beneficiário/pagador/valor/**vencimento**/linha digitável, e o anexa à cobrança (`Attachment` label=boleto). Aparece na Agenda no dia do vencimento e nos anexos do evento. Cada ocorrência recorrente gera seu próprio boleto.
- [x] **Pagamento reconhecido AUTOMATICAMENTE (sem botão "marcar pago")** — removidos os botões "Marcar paga" de Cobranças e Ficha 360°. Pagamento entra por `POST /receivables/webhook` (gateway: Pix/cartão/boleto compensado), público, protegido por `GATEWAY_WEBHOOK_SECRET` (vazio em dev = aberto p/ teste; definido em prod = só o gateway confirma). A baixa credita a Carteira (split) e libera p/ **saque** no Financeiro. O dono só saca o que o sistema reconhece como pago.
  - Dev/teste: link discreto "simular pgto" nas cobranças chama o webhook (some quando o segredo for definido em prod). Endpoint `/pay` mantido só para testes internos.
  - **Dívida:** gateway real (Asaas/Mercado Pago) — gerar boleto/Pix com registro e receber o webhook de verdade; boleto atual é layout-stub sem registro bancário.

## Financeiro: recorrência + nome do cliente na agenda
- [x] **Recorrência gera ocorrências** — Contas a Pagar e a Receber: ao marcar recorrência (semanal/mensal/anual) define-se **quantas vezes repete** (`recurrence_count`, 1–60). O backend GERA uma conta/cobrança por período (`core/recurrence.advance` com clamp de dia no mês), cada uma com **seu vencimento, seu evento na Agenda e seu boleto** — assim cada repetição recebe o boleto certo. Ocorrências ligadas por `recurrence_group`. Charges ganharam `recurrence`/`count`/`group` (antes só payables tinha o tipo, sem gerar). Migration 0026.
- [x] **Nome do cliente no card da Agenda** — `EventOut.client_name` resolvido no `list/get` (cobrança→cliente, conta a pagar→fornecedor); o chip da agenda mostra o nome quando houver, senão o título.

## Financeiro: editar + agenda (reverberar)
- [x] **Editar cobrança e conta a pagar** (botão "Editar" por linha, só em aberto): `PATCH /receivables/charges/{id}` (descrição/valor/vencimento) e `PATCH /payables/bills/{id}` (descrição/categoria/fornecedor/valor/vencimento/recorrência + boleto/Pix). **Reverbera na Agenda**: ao mudar o vencimento o evento MOVE junto; valor e título do evento também sincronizam. Pago/cancelado não edita (409).
- [x] **Detalhe do evento na Agenda** mostra a descrição completa + **anexos (boleto/contrato)** via o componente `Attachments` (owner = charge/payable do `external_ref`); para conta a pagar mostra também o código Pix/boleto.
- [x] **Estornar conta paga (só Contas a Pagar)** (botão "Estornar" por linha, só em "Pago"): `POST /payables/bills/{id}/reverse` volta o status para `open`/`paid_at=None`, reabrindo a edição completa (dados + anexos) e devolvendo o evento da Agenda de "concluído" para pendente. Confirmação via `confirm()` do navegador. Contas a Pagar nunca move dinheiro (não passa pela Carteira), então o estorno é uma troca de status simples e segura.
  - **Decisão de escopo:** a mesma capacidade foi implementada e revisada para Contas a Receber, mas **descartada antes do merge**: pagar → estornar → pagar de novo (o fluxo principal do estorno) duplicaria o `PlatformEarning` da venda no painel do Master (GMV/taxas globais), porque esse ledger não guarda vínculo de volta à `Transaction`/`Charge` de origem — reverter e repagar 3x uma cobrança de R$100 reportaria R$400 de GMV. Corrigir isso direito exige uma migration ligando `platform_earnings` à transação de origem; decisão do usuário foi não introduzir esse efeito colateral agora. Se o estorno de cobranças for retomado, resolver esse vínculo é pré-requisito (ver `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md`).

## Financeiro: duplicar conta a pagar

> Spec: `docs/superpowers/specs/2026-08-12-duplicar-conta-a-pagar-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-12-duplicar-conta-a-pagar.md`

Boa parte das despesas do dono **se repete sem ser recorrente**: aluguel de sala, viagens do mesmo
trecho, ferramentas em dólar (o valor muda todo mês). A recorrência já existia e não resolve esse
caso — ela exige saber de antemão quantas vezes vai repetir e supõe valor fixo.

- [x] **"Duplicar esta conta" abre o cadastro PREENCHIDO, não grava direto.** O gesto termina no
  mesmo `POST /payables/bills` de sempre: **zero backend, zero migration, zero campo novo**.
- [x] **O botão vive dentro do modal "Boleto/Pix", NÃO no grid** (decisão do fundador). A coluna de
  ações já carrega até cinco elementos e a tabela já rola lateralmente em 360px — uma sexta ação em
  toda linha pagaria largura em todas as telas para servir um gesto ocasional. Como o modal só é
  alcançável em linha não cancelada, **a restrição de status vem de graça**: não há regra própria a
  manter.
- [x] **`pagar/duplicar.ts`** — `camposDaCopia` + `proximoVencimento`, puras, 13 testes sem DOM
  (mesmo recorte de `baixa.ts`). ⚠️ **O vencimento avança um mês por fatiamento de string**, com
  trava de fim de mês (`31/01 → 28/02`, bissexto incluído, `2100` não é bissexto).
  `new Date("2026-07-31")` é meia-noite **UTC** e devolveria dia 30 em UTC−3 — a cópia nasceria um
  dia antes, em silêncio e só para quem está a oeste de Greenwich (regra §6.0). Quem "simplificar"
  com `Date` reintroduz isso. Data ilegível devolve `""`, e o botão de gravar fica desabilitado:
  pedir a data é melhor que inventá-la.
- [x] **A cópia leva** descrição, fornecedor, categoria, centro de custo, valor, contrato e o código
  Pix/boleto. **Não leva** anexos nem a recorrência.
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
- ⚠️ **`NewBillModal` é remontado por `key`, e isso não é estilo.** Ele fica montado o tempo todo, e
  `useState(inicial)` só lê o prop na MONTAGEM — sem a `key`, a segunda duplicação mostraria os
  dados da primeira. O defeito passa despercebido em teste manual apressado, porque **a primeira
  duplicação de cada sessão funciona**. Tem teste dedicado.
- ⚠️ **`duplicando` é zerado em DOIS lugares** — no `onClose` do formulário e na ação primária
  "Nova conta". Só o primeiro cobre o caminho normal e deixa vivo o caminho `duplicar → fechar →
  Nova conta`, que abriria o cadastro preenchido com uma despesa que o dono não pediu. Também tem
  teste próprio.
- **Sem dívida de aceite em ~360px**, ao contrário das últimas entregas: nada entrou no grid e o
  botão segue a largura total dos que já estavam no modal.
- **Dívida:** duplicar cobrança em **Contas a Receber** não existe (a simetria é tentadora e o
  módulo é outro); não há duplicação em lote nem template de despesa.
- ~~⚠️ **Achados PRÉ-EXISTENTES em `main`, fora do escopo desta mudança e NÃO corrigidos aqui:**
  `pnpm typecheck` e `pnpm lint` já falhavam antes deste diff.~~ **FECHADOS em 2026-08-12**, num PR
  separado só disso — e **só UM dos dois era defeito do repositório.** Ver a seção logo abaixo.

## Financeiro: o recorte da lista de Contas a Pagar (2026-08-18)

> Spec: `docs/superpowers/specs/2026-08-18-contas-a-pagar-recorte-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-18-contas-a-pagar-recorte.md`

A tela era uma lista única, sem filtro, ordenada por vencimento **crescente** — a conta mais antiga
já paga ocupava a primeira linha. E, como recorrência aqui é **materializada** (`create_payable`
grava N linhas reais ligadas por `recurrence_group`), a lista crescia sozinha sem o dono lançar
nada.

- [x] ⚠️ **O defeito mais grave não era a rolagem: era o truncamento silencioso.**
  `list_payables` tinha `limit=200` fixo e o router **não expunha** `limit`/`offset`. Com a
  ordenação crescente, a rota devolvia as **200 mais antigas** — passando de 200 contas, o que
  sumia da tela era o **futuro, ainda por pagar**. Sem aviso, sem contagem, sem sintoma. O teste
  `test_teto_de_200_nao_engole_o_futuro` reprova o código antigo e é a régua da entrega.
- [x] **`GET /payables/bills` devolve `{items, total}`**, não lista nua, e aceita `status`
  (**repetível**), `from`, `to`, `q`, `cost_center_id`, `chart_account_id`, `order`, `limit`,
  `offset`. O `total` é o do recorte inteiro: é ele que sustenta o **"Mostrando 50 de 213"**, que
  aparece SEMPRE e não só quando trunca. O pecado antigo não era ter teto — era o teto não se
  anunciar.
- [x] **A tela abre em "o que eu devo"**: `status ∈ (open, scheduled)`, **sem piso de data** e com
  teto no fim do mês seguinte. ⚠️ **O "sem piso" é deliberado.** Atrasado vence no passado; um
  `from` na visão padrão esconderia exatamente a conta mais urgente que existe. Travado por
  `test_from_ausente_nao_engole_atrasado_antigo` e pelo teste de front do recorte padrão.
- [x] **A ordenação segue a intenção do filtro:** em aberto/agendada `asc`; pago/cancelado `desc`
  (histórico se lê do mais recente para trás). A direção é decidida no front (`filtros.ts`) e vai
  explícita na query — o backend obedece e valida, não adivinha.
- ⚠️ **`list_payables` e `count_payables` compartilham `_filtros()`. Não duplique o `where`.**
  Divergindo, a tela anuncia um `total` que a própria lista não confirma: nada quebra, o rodapé só
  passa a mentir. `test_total_sempre_casa_com_a_lista` cobre sete combinações de filtro.
- ⚠️ **O `q` escapa `%` e `_` antes do `ilike`.** Sem isso, digitar `%` casa com tudo e a busca
  parece funcionar enquanto não filtra nada — defeito sem sintoma. A implementação ingênua passa em
  todos os outros testes e falha só em `test_q_escapa_curinga_do_like`.
- ⚠️ **`from` é palavra reservada em Python:** o parâmetro é `due_from` com `alias="from"`.
- [x] **`POST /payables/bills/{id}/reactivate`** — conta cancelada volta para `open` **com o
  vencimento original**. Reativada depois do prazo, nasce **Atrasada**, que é o que ela é: empurrar
  a data para hoje apagaria o vencimento contratado e a Projeção/DRE passariam a contar uma data
  que nunca existiu.
  - ⚠️ **Não é `/reverse`, e a separação é de significado.** `reverse` quer dizer *"esta saída não
    vai acontecer"* e seu trabalho é **apagar o movimento bancário**; `cancel_payable` só aceita
    conta em aberto, que nunca teve movimento nenhum. Fundir os dois obrigaria um
    `if status == canceled: pula tudo` no meio da lógica mais delicada do arquivo.
- [x] **`pagar/filtros.ts`** — estado do filtro, puro e sem DOM (12 testes). ⚠️ **`fimDoMesSeguinte`
  faz aritmética de string, nunca `new Date`:** o dia já chega no fuso do tenant (`today(useFuso())`)
  e reconstruir um `Date` devolveria o cálculo ao fuso do navegador — em UTC−3, das 21h à meia-noite
  o horizonte pularia um dia (regra §6.0).
- [x] **`GanchoDaVima` desceu para DEPOIS da tabela.** Acima do título ele ocupava ~200px da
  primeira dobra e empurrava a lista para fora da tela.
- [x] **Centro de custo e Categoria ficam atrás de "Mais filtros" SÓ no celular** — e isso foi
  **medido, não suposto**. Com os cinco controles na mesma linha, em 360px a barra refluía em cinco
  linhas, ocupava ~300px e jogava a tabela para `y=765`, fora da dobra de 740px. Recolhidos:
  `y=653`. De `sm` para cima os cinco aparecem juntos. `e2e/pagar-360.spec.ts` mede por
  `boundingBox`, nunca por classe CSS.
- ⚠️ **BUG DE INTEGRAÇÃO ACHADO E CORRIGIDO: o axios serializava `status[]=open`.** O FastAPI
  declara `status: list[str] | None = Query(default=None)` e só reconhece a forma **repetida**
  (`status=open&status=scheduled`); com colchetes ele não vê o parâmetro, recebe `None` e devolve a
  lista **sem filtro nenhum** — a tela pediria "o que eu devo" e receberia pago e cancelado junto,
  sem erro e sem sintoma. Corrigido com `paramsSerializer: { indexes: null }` nos **dois** clientes
  de `lib/api.ts`.
  - ⚠️ **Nenhuma camada de teste pegava isso, e vale entender por quê:** o pytest monta a URL crua
    já na forma certa, o vitest assere o objeto `params` **antes** de serializar, e o gate de layout
    recebe payload fixo seja qual for a query. Só medir a URL real fecha a fresta — é o que
    `e2e/pagar-contrato.spec.ts` faz, e é o único lugar do projeto onde axios de verdade roda.
- **A busca da barra de cima CONTINUA DESLIGADA** (`AppShell.tsx`, `<input>` sem `onChange` — o
  próprio código diz *"é decoração até alguém ligá-la"*). **Não é regressão e não é bug**: é o
  Projeto B, ainda sem spec. Registrado aqui para a próxima sessão não gastar tempo procurando um
  defeito que não existe. O filtro de texto de Contas a Pagar é o primitivo que ele vai reusar.
- **Dívida:** `receivables.cancel_charge` tem o mesmo beco sem saída — cobrança cancelada também
  não volta. Fora de escopo (não foi pedido e dobraria a superfície de teste); a rota seria
  `POST /receivables/charges/{id}/reactivate`, com a mesma forma do `reactivate_payable`.
- **Dívida:** sem índice para o `ilike` sobre `description`/`supplier`. Com alguns milhares de
  linhas por tenant, já cortadas pela RLS, roda sem. `pg_trgm` é o gatilho quando incomodar —
  otimização especulativa agora.

## Os dois gates herdados de `main` — e a diferença entre "vermelho aqui" e "vermelho num clone novo"

O parágrafo acima registrava `pnpm lint` e `pnpm typecheck` como duas dívidas irmãs de `main`.
Medidos num **clone novo** (worktree limpa, `pnpm install`, nada mais), eram coisas diferentes:

- [x] **`pnpm lint` era defeito real do repositório** — `financeiro/investimentos.test.ts:68`
  reprovava por `no-irregular-whitespace`: um **NBSP (U+00A0) LITERAL dentro da regex** de
  `.replace(/ /g, " ")`. A normalização é intencional e continua (o `Intl.NumberFormat` produz
  NBSP, e comparar contra `formatBRL` seria tautológico), então o conserto **não** foi apagar o
  caractere: foi trocá-lo pelo **escape `\u00a0`**. Mesmo valor comparado, e agora o caractere é
  visível para quem lê o diff **e** para o linter. Os 13 testes do arquivo seguem verdes.
  - O comentário no teste diz que o NBSP vai como escape e **por quê** — o literal faz exatamente
    o que o próprio teste descreve (some no diff), e foi assim que ele entrou no PR #102.
- [x] **`pnpm typecheck` NUNCA foi defeito do repositório.** `@playwright/test` está declarado em
  `apps/web/package.json` e travado no `pnpm-lock.yaml` **desde o PR #105** (o que trouxe a régua
  de 360px). O que faltava era o `pnpm install`: o checkout de dev tinha `node_modules` de antes
  do #105. Em clone novo, `pnpm install && pnpm typecheck` passa **sem tocar em nada** — e o job
  `frontend` do CI sempre foi verde nisso, porque ele roda `pnpm install --frozen-lockfile` antes.
  - ⚠️ **A receita `pnpm typecheck | grep "^src/"` está REVOGADA.** Ela filtrava justamente os
    erros de `e2e/` e do `playwright.config.ts` — os arquivos DA RÉGUA, que o CI executa. Quem vir
    esses erros deve rodar `pnpm install`, nunca filtrar a saída.
- [x] **`pnpm lint` não rodava em NENHUM job do CI**, e é essa a explicação de por que o NBSP
  sobreviveu do #102 até aqui: `ci.yml` tinha typecheck, vitest e o gate de 360px, e nada de
  `eslint`. O job `frontend` ganhou a etapa **Lint** (antes do typecheck, que é a mais rápida das
  quatro). Ela **barra o merge** como o resto do job: `frontend` é required check em `main` (§5.1).

> **A regra que fica:** gate vermelho no SEU checkout não é, por si, dívida do repositório.
> *"Vermelho aqui"* e *"vermelho num clone novo"* são afirmações diferentes, e distinguir as duas
> custa **um `pnpm install`**. Registrar a primeira como se fosse a segunda transforma um passo de
> setup esquecido em folclore com receita de contorno — e a receita de contorno é pior que o
> problema, porque ela silencia arquivos que o CI cobra. Metade dessa dívida nunca existiu.

## Financeiro: Inteligência Financeira (Epic 5 — Stories 5.1–5.9 ✅ em produção desde 2026-07-11)
> Docs: `docs/prd/epic-5-inteligencia-financeira.md` · stories `docs/stories/5.1`–`5.9` · a DRE em
> matriz e a tela de Lucratividade vieram **fora do fluxo de story** (PRs #46–#52, 2026-07-23/24) e
> estão em `docs/runlogs/financeiro-dre-matriz-lucratividade-RUN-LOG.md`.

**Por que existe.** Contas a Pagar/Receber dizem o que entrou e o que saiu. Nenhuma delas responde
**se dá lucro, de onde vem o lucro, e se o caixa aguenta até lá**. O Epic 5 é a camada analítica
**só-leitura** sobre os dados operacionais que já existiam — não um módulo de escrituração, e não
concorre com o contador. O Epic 8 (abaixo) veio depois para ancorar essa camada no banco: sem
âncora, DRE infla lucro, Lucratividade distorce e a Projeção mente.

### As 4 regras que nenhum relatório deste módulo pode violar
1. **O sinal vem da TABELA DE ORIGEM, nunca do `grupo_dre`.** `Charge` (entrada) = **+1**;
   `Payable` (saída) = **−1**. O grupo é só rótulo de exibição — **nunca derive nem inverta o sinal
   a partir dele**. O total de um grupo é a soma **já-com-sinal**; o resultado é a **SOMA** dos
   grupos de resultado (todos menos `INVESTIMENTO`; `SEM_CATEGORIA` fica fora).
   Isto **generaliza** `RECEITA − CUSTO − DESPESA − TRIBUTOS ± FINANCEIRO`, **não é idêntico a ela**:
   `chart_account_id` é livre nas duas tabelas, então existe `Charge` em `CUSTO_DIRETO` (nota de
   crédito) e `Payable` em `RECEITA` (reembolso). Nesses casos as duas divergem, e é o **sinal
   natural que está certo** — o estorno *reduz* o grupo em vez de inflá-lo.
   **Footgun:** os totais já vêm assinados (custo é NEGATIVO). Quem fizer `receita − custo`
   esperando custo positivo faz dupla-negação. Consuma `resultado_cents`, não re-derive.
   Regra canônica escrita por extenso no docstring de `financial_intelligence/dre.py` — é lá que o
   próximo relatório do módulo deve ler antes de somar qualquer coisa.
2. **Duas datas, dois regimes — nunca inverter.** DRE e lucratividade usam **`competence_date`**
   (competência); caixa e projeção usam **`paid_at`** (o dinheiro mudando de mão), e enquanto o
   item está em aberto a projeção usa `due_date` como pagamento *previsto*. Fixado na 5.2, no
   docstring dos models de `payables`/`receivables`.
3. **Análise não escreve.** Rateio de overhead, baldes da fila, células da matriz, rentabilidade —
   tudo calculado na leitura, nada persistido no lançamento original. Cada serviço tem teste que
   compara snapshot antes/depois de duas chamadas.
4. **Regra determinística primeiro, IA narrando depois.** Os sinais 🟢🟡🔴 existem e estão corretos
   **sem `ANTHROPIC_API_KEY`** — a IA só reformula texto, nunca origina número.

### O que existe (tudo com item no menu, grupo "Análise & Configuração Financeira")
| Tela | Rota | Backend |
|---|---|---|
| **Plano de contas** (5.1) | `/financeiro/plano-contas` | `chart_of_accounts/` · migration **0045** |
| **DRE** + **DRE em matriz** (5.3 + PRs #49–#52) | `/financeiro/dre` | `financial_intelligence/dre.py` · `GET /dre`, `/dre/matrix`, `/dre/matrix/entries` |
| **Lucratividade** por contrato (5.4 + PR #47) | `/financeiro/lucratividade` e `/financeiro/contratos/:id/dre` | `profitability.py` · `GET /contracts-dre`, `/contracts/{id}/dre`, `/contracts/{id}/ledger` · migration **0047** |
| **Centros de custo** (5.5) | `/financeiro/centros-custo` | `cost_centers/` · `GET /by-cost-center` · migration **0048** |
| **Investimentos** (5.6) | `/financeiro/investimentos` | `investments/` · migration **0049** |
| **Projeção de caixa** (5.7) | `/financeiro/projecao-caixa` | `projection.py` · `GET /projection` |
| **Diagnóstico** (5.8) | `/financeiro/diagnostico` | `engine.py` + `diagnostics.py` + `ai_narrator.py` · `GET /diagnostics` |
| **Fila de pagamentos** (5.9) | `/financeiro/fila-pagamentos` | `payables.payment_queue()` · `GET /payables/queue` · sem migration |

- **Fundação (5.1/5.2).** `ChartAccount` (RLS): `grupo_dre` num enum fixo (`RECEITA`, `CUSTO_DIRETO`,
  `DESPESA_FIXA`, `TRIBUTOS`, `FINANCEIRO`, `INVESTIMENTO`) + categoria livre única por grupo;
  arquivar não apaga histórico. A **0046** acrescentou `competence_date`/`paid_at`/`chart_account_id`
  a `charges` e `payables` — tudo **nullable**, nada legado invalidado, competência com backfill a
  partir do vencimento. Não classificado cai no bucket **"sem categoria"**, que aparece no relatório
  em vez de sumir.
  - ⚠️ **A armadilha que a 0046 pagou por nós, e que qualquer migration futura com `UPDATE` vai
    encontrar de novo:** o backfill rodava como **no-op silencioso** no Postgres real. As tabelas têm
    `FORCE ROW LEVEL SECURITY` e a migration roda como `e1p_app` (non-superuser) **sem**
    `app.current_tenant_id` setado → a política filtra o `UPDATE` a **zero linhas**, sem erro. **O
    SQLite dos testes unitários não pega isso.** Fix: desabilitar a RLS só durante o backfill e
    restaurar (`ENABLE` + `FORCE`) — DDL é transacional no Postgres, sem janela de exposição.
    **Regra: migration que faz `UPDATE` em tabela com FORCE-RLS precisa ser validada contra Postgres
    real, não contra a suíte.**
- **DRE em matriz** (a tela que o menu chama de "DRE"): meses nas colunas, grupos/categorias nas
  linhas, agrupável por **DRE** ou por **centro de custo** (`group_by`). Clicar numa célula abre o
  drawer com os lançamentos analíticos daquela categoria naquele mês. `TOTAL GERAL` aparece antes do
  Investimento, e há uma linha `TOTAL GERAL + INVESTIMENTO` (gasto do período incluindo capex) —
  somada por `kind="informational"`, não pelo grupo nomeado, porque no modo centro de custo as linhas
  de investimento ficam espalhadas e não têm seção própria.
- **Lucratividade (5.4).** O eixo "projeto" é o **`Contract`** que já existia — `contract_id`
  nullable em `charges`/`payables`; sem vínculo, o lançamento cai no bucket implícito **"Empresa"**
  (overhead). Calcula margem de contribuição (R$ e %), break-even e o **rateio do overhead só na
  leitura**. Divisão por zero coberta nos três pontos (margem sem receita, break-even sem margem
  positiva, rateio sem receita) — retorna `None`/0, nunca 500.
- **Investimentos (5.6) — o único caminho de escrita novo no modelo de dinheiro.** Registrar
  rendimento cria uma **`Charge` já nascida `paid`** (com `external_ref="investment:{id}"`,
  `chart_account_id` no grupo `FINANCEIRO`) **sem** passar por `mark_paid`/`build_transaction` —
  logo **não gera `Transaction` nem `PlatformEarning`**: rendimento é receita financeira, não venda
  com split. Como nasce paga, um webhook posterior é no-op idempotente. Em troca, ela é **filtrada
  na leitura** de `receivables.list_charges` e do `paid` do summary
  (`coalesce(external_ref,'') NOT LIKE 'investment:%'` — o `coalesce` é obrigatório: sem ele o `NOT
  LIKE` sobre NULL avalia NULL e some com tudo), para não poluir a tela de Cobranças. Aparece na DRE
  no grupo FINANCEIRO, que é onde deve aparecer.
- **Projeção (5.7).** 30/60/90 dias + runway, em regime de caixa. **Itens vencidos e ainda em aberto
  entram em todas as janelas** — decisão da @architect contra a implementação original: esconder
  obrigação vencida deixa a projeção otimista exatamente para quem já está apertado. A incerteza é
  comunicada **por transparência** (`overdue_inflow_cents`/`overdue_outflow_cents` expostos à parte),
  nunca por exclusão silenciosa. ⚠️ **O `saldo_inicial` desta projeção mudou no Epic 8** (Ondas 0 e
  2): não é mais o saldo da Carteira — leia a seção do Epic 8 abaixo antes de mexer nele.
- **Diagnóstico (5.8).** `engine.py` é **puro** (sem I/O, sem relógio) e determinístico; `diagnostics.py`
  faz a leitura; `ai_narrator.py` narra em PT-BR **depois** de passar o texto pelo `core/anonymizer`
  e grava rastro "Ação executada pela IA" (Regras de Ouro nº 2 e nº 3). Os sinais de hoje: margem,
  runway, janela de projeção, rentabilidade — mais completude, off-rail e débito suspeito, que o
  Epic 8 acrescentou. A pureza do `engine.py` é garantida por **gate AST**, não por convenção.

### Dívida (verificada contra o código, 2026-08-07)
- 🔴 **O anonimizador não cobre nome livre, e o Diagnóstico manda nome livre.** `core/anonymizer.py`
  é 100% regex sobre PII estrutural (CPF/CNPJ/e-mail/telefone/cartão) — **sem NER**. Duas regras do
  motor injetam nome cru no payload que vai ao Claude: `_margin_signals` usa `contract.title` (e
  título de contrato carrega nome de contraparte rotineiramente) e `_investment_signals` usa
  `inv.name`. **É débito transversal do core, não defeito da 5.8** — o Jurídico, em produção e sob
  segredo de justiça, tem exatamente a mesma lacuna. O fundador **aceitou o risco residual em
  2026-07-11**; o gate registrado é: **não expor isto com `ANTHROPIC_API_KEY` real em produção sem o
  hardening do anonimizador (story própria, escopo Financeiro + Jurídico) ou um aceite adicional por
  escrito.** Ver `docs/stories/5.8.story.md` §"PENDÊNCIA FORMAL A ABRIR" e §6.1 abaixo.
- **Duas fórmulas de "resultado" convivem.** A tela de contrato segue o AC2 (margem de contribuição =
  só `RECEITA` + `CUSTO_DIRETO`; outros grupos do contrato ficam fora, sinalizados por uma `note`);
  a regra geral da 5.3 somaria todos os grupos de resultado. A divergência foi declarada pelo @dev e
  nunca reconciliada. Quem for unificar: decida qual é a canônica **antes** de escrever a terceira.
- **Bucket "sem categoria" mostra a soma líquida** (receber − pagar) numa linha só; separar entradas
  de saídas se virar ruído.
- **Sem observabilidade do fallback `COALESCE(competence_date, due_date)`** — contar quantas linhas
  caem no fallback denunciaria backfill incompleto da 0046. Hoje ninguém conta.
- **`kind`/`index_rate_label` do investimento são rótulos livres** — nenhuma integração com CDI/IPCA
  reais; rentabilidade é sobre o que foi digitado.
- **Os cortes da fila (hoje / 7 / 30 dias) são convenção da 5.9**, não do PRD — bordas inclusivas à
  direita, cobertas por teste em cada borda.
- **Seletor "vincular a contrato" só existe nos modais de CRIAÇÃO** de Pagar/Cobranças (o relink por
  `PATCH` funciona e é testado, só não tem UI); e a Ficha 360° do cliente não tem link "Ver DRE".
- **`paid_at` não aparece em lugar nenhum da tela de DRE** (nem na matriz, nem no drawer). Follow-up
  identificado e não pedido.
- **Render-test de DOM das telas do Epic 5.** As stories registraram isto como limitação de tooling
  ("o projeto não tem jsdom") — **a premissa não vale mais**: `jsdom` + `@testing-library` entraram
  desde então e outras telas já têm `.test.tsx`. O que falta agora é escrever os testes de
  `DrePage`, `ContratoDrePage`, `DiagnosticoPage`, `InvestimentosPage`, `PlanoContasPage` e
  `CentrosCustoPage` — a lógica pura já é coberta pelos `.ts` irmãos.
- **Nenhuma das 5 waves da DRE em matriz / Lucratividade tem story formal** em `docs/stories/`.
  Dívida de rastreabilidade registrada 5 vezes no RUN-LOG e nunca fechada. Foi assim que uma
  feature inteira ficou pronta numa worktree órfã por semanas sem ninguém saber — ver o RUN-LOG.

## Financeiro: Controle Bancário e Conferência (Epic 8 — Ondas 0, 1 e 2 ✅ em produção)
> Docs: `docs/prd/epic-8-controle-bancario.md` · `docs/architecture/controle-bancario-design.md` + `...-ratificacao.md` · `docs/decisions/0003-controle-bancario-nativo.md` · `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` · pesquisa em `docs/research/2026-07-29-*`
> Onda 2: `docs/architecture/controle-bancario-onda2-design.md` + `...-onda2-ratificacao.md` · `docs/qa/epic-8-onda-2-gate-2026-08-04.md` (veredito **CONCERNS**) · `docs/qa/epic-8-gate-8.19-8.20-2026-08-07.md`

**Por que existe.** Receber tem três testemunhas independentes (gateway, webhook, o dinheiro entrando). **Pagar não tem nenhuma**: se o dono paga pelo app do banco e não lança, nada protesta — e o silêncio de uma despesa não lançada é indistinguível do silêncio de um mês sem despesa. Sem âncora externa, DRE infla lucro, Lucratividade distorce e a Projeção mente. O banco é a testemunha que faltava. **O objetivo é achar furos, não fazer escrituração** — não é competir com o contador.

### As 7 regras que impedem o próximo bug (leia antes de mexer em qualquer coisa com saldo)

1. **A Regra dos Planos.** Três planos de dinheiro que NÃO se cruzam: **plataforma** (`transactions`, split 40/30/20, `platform_earnings`), **negócio** (`charges`, `payables`), **banco** (`bank_*`). O único contato legítimo entre plataforma e banco é o payout da Carteira (**Onda 3**, não construída). **Foi misturar plano de plataforma com plano de banco que produziu o bug de origem.** Gates estruturais em `apps/api/tests/test_money_planes.py` reprovam a reintrodução.
2. **Dois eixos de proveniência, nunca achatados num campo.** `*_origem` = **plano** (`plataforma｜banco｜misto｜indisponivel`, em `app/core/money_planes.py`); `*_fonte` = **porta de entrada** (`manual｜ofx`, em `bank/models.py`). Os valores `declarado` e `extrato` foram **revogados** — eram o eixo B disfarçado.
3. **Todo campo de saldo em schema de saída declara sua proveniência.** Comparar saldos só é legítimo quando ambos são do mesmo plano.
4. **Saldo é DERIVADO dos movimentos, nunca coluna, nunca digitado.**
5. **O checkpoint NUNCA corrige o saldo derivado.** Se corrigisse, a divergência iria a zero por construção e a métrica que justifica o épico morreria. Testado em `test_bank_checkpoints.py`.
6. **A conferência é POR CONTA, com a mesma data de referência dos dois lados** (o `reference_date` do checkpoint daquela conta — não "hoje", não uma data comum). `derived_balances_as_of` é **PROIBIDA** na conferência: recebe um `as_of` só, e usá-la ali compara saldos de datas diferentes. Seu consumidor legítimo é a tela de lista. Varredura AST reprova a chamada.
7. **Dentro da banda: verde e SILÊNCIO.** Banda `max(R$ 50, 0,5%)`, borda `==` é dentro. **Fixa de propósito** — a divergência é o instrumento que mede o gate de decisão das ondas de importação, e régua ajustável pelo tenant invalidaria a leitura. ⚠️ **Mas leia a correção do gate acima antes de usar esse número para decidir qualquer coisa**: a leitura só vale a partir do primeiro ciclo completo posterior à Onda 2 (a origem do movimento). Antes disso a divergência mede a própria incompletude do sistema. Uma tela que grita por R$ 3 destrói a confiança no sinal.

### Onda 0 — o saldo inicial parou de mentir
- [x] **A Projeção de Caixa semeava `saldo_inicial` com `wallet_summary()["available_cents"]`** — saldo da **carteira da plataforma**, não da conta bancária do dono. Errada desde sempre, independente de lançamento esquecido. Agora declara `saldo_inicial_origem` e **suprime no backend** (não na UI) toda afirmação sem lastro: `runway.days=None` + `days_suprimido`, `ProjectionWindow.alert=False` + `alert_suprimido`, ícone de tendência neutro. **Princípio: suprimir a afirmação, nunca o número** — o saldo continua visível.
  - Suprimir na origem, e não na tela, porque o mesmo saldo alimentava **três** superfícies: a Projeção, o sinal de runway do Diagnóstico (`engine._runway_signal`) e o ícone do `WindowCard`. O design mapeava uma.
  - O `alert` era **máquina de falso negativo**: como `request_payout` só marca `withdrawn` (saque real não existe) e `payables` não toca a Carteira, `available_cents` **só cresce** — o alerta ficava silencioso justamente quando deveria disparar.
  - **Supersede o AC1 e o AC2 da Story 5.7**, que mandavam partir do saldo da Carteira. É correção, não regressão — não "conserte de volta".

### Onda 1 — o controle bancário
- [x] **`bank_accounts`** (migration 0058) — N contas por tenant (corrente/poupança/aplicação/caixa), saldo de abertura, RLS `FORCE`. `platform_wallet` é rejeitado como `kind`: é a Regra dos Planos em forma de validação.
- [x] **`bank_transactions`** (0059) — `amount_cents` assinado, `posted_at` como `DATE`, `raw_description` **imutável** (é evidência; a edição do usuário vai em `user_description`). Colunas de dedupe (`fitid`, `dedup_hash` + unique) já criadas para a Onda 3. `status <> 'ignored'` é aplicado **dentro** do saldo derivado — quem consome não refiltra.
- [x] **`bank_balance_checkpoints`** (0060) — "o saldo desta conta no fim deste dia era X". Redeclarar o mesmo dia **corrige** (200), não dá 409.
- [x] **Conferência** (`bank/reconciliation.py`, read-only) — `GET /bank/reconciliation-report`. Divergência **por conta**; o consolidado nunca aparece sem a decomposição. Sem checkpoint na janela → `indisponivel`, e o relatório **diz que não sabe** (`None` ≠ zero).
- [x] **Sinal de completude no `/financeiro/diagnostico`** — 🟢🟡🔴, **um sinal por conta** (3 contas nenhuma conferida = 3 sinais, não 6), com precedência semântica sobre margem/runway: se o produto não sabe se os lançamentos estão completos, qualquer afirmação sobre margem é feita sobre base possivelmente furada. `engine.py` permanece **puro** (sem I/O, sem relógio) — gates AST + varredura de texto garantem.
  - **Decisão do fundador:** o 🟡 "nenhuma conta bancária cadastrada" aparece para **todos** os tenants, sem opt-in e sem dispensa. O sinal é verdadeiro, e escondê-lo seria a mesma mentira por omissão que a Onda 0 corrigiu.
- [x] **Projeção com `origem="misto"`** — saldo bancário + carteira, com as **duas parcelas sempre expostas separadamente**. Somar sim; esconder a composição, nunca. Sem conta cadastrada, cai no fallback da Onda 0 — e a restauração do runway/alert/ícone acontece **por construção** (a supressão sempre foi condicionada à origem; o componente não tem condicional própria).
- [x] **Telas** — `/financeiro/contas` ("Contas & Saldos", na sidebar) e `/financeiro/conferencia` (**fora** da sidebar, alcançada pelo sinal do Diagnóstico: conferência é resposta a um sinal, não tarefa de rotina — vira item de menu, vira peso de ERP). **A frase vem antes da tabela.**
  - Dois recortes rotulados e distintos: **"Total em contas"** (todas as ativas) × **"Disponível como caixa"** (exclui aplicação — é a parcela que a Projeção soma). A string `"no banco"` é proibida nesta tela; pertence à Projeção, com outro sentido.

**Restrição de produto (decisão do fundador):** **sem agregador de Open Finance** — Pluggy, Belvo e Klavi vetados. Formato de arquivo (OFX/CSV) é aceitável porque é formato, não serviço. E **não posicionar como conformidade tributária**: a LC 214/2025 tem obrigação **documental** (NFS-e) e o split payment não alcança o Simples com DAS unificado, que é o regime da sociedade unipessoal de advocacia. A justificativa é conferência e controle interno.

**⚠️ CORREÇÃO (2026-07-30, mesmo dia): a leitura do gate abaixo estava ERRADA e quase custou a decisão de produto.**

A versão anterior deste parágrafo dizia: *"se a divergência medida na Onda 1 for pequena e estável, as Ondas de import são over-engineering; a Onda 1 é o instrumento que decide isso."* **Isso é falso**, e o erro é instrutivo.

A Onda 1 mede a divergência com o razão bancário **vazio**, porque nada no sistema escrevia nele — baixar uma conta a pagar não gerava movimento bancário. Então a divergência medida ali é enorme **por construção**: ela mede a **ausência de uma porta**, não o furo. E teria argumentado, com número grande e aparentemente sólido, para liberar justamente a onda mais cara e a única com dependência externa perpétua (import de OFX). **A feature que faltava teria pedido a construção da feature mais cara.**

**A leitura do gate só é válida a partir do primeiro ciclo completo posterior à Onda 2**, e sob a pré-condição de que toda conta paga e todo recebimento da janela tenham conta bancária informada. Antes disso, o número não significa nada.

⚠️ **E mesmo isto é otimista demais — a ratificação da Onda 2 corrigiu esta frase.** Lida ao pé da letra, a pré-condição acima é **insatisfazível** (uma cobrança do trilho nunca terá conta bancária, pela Invariante do Trilho), e reescrita em termos executáveis ela se parte em quatro, cada um zerado por uma onda diferente. **O gate não abre "depois da Onda 2" em geral: abre para um tenant cujos únicos eventos que movem conta real na janela sejam baixa de Contas a Pagar e recebimento fora do trilho.** Quem registra rendimento de aplicação precisa da Onda **2b**; quando o payout virar real, da **3**. Ver a seção da Onda 2 abaixo, item 5.

**Regra de método que fica** (vale para qualquer métrica que decida escopo): antes de usar um número como gate, pergunte **o que ele mede quando o sistema está incompleto**. Se a resposta for "mede a própria incompletude", ele não é gate — é termômetro do que ainda não foi construído, e vai sempre pedir mais construção.

**⚠️ REGRA — INSTANCIAÇÃO OBRIGATÓRIA** (derivada no mesmo dia, depois de a mesma seção quebrar duas vezes de formas opostas — primeiro medindo a própria incompletude, depois virando insatisfazível):

> Todo conjunto definido por **descrição** num documento de arquitetura nasce com **pelo menos um membro E um não-membro escritos, no mesmo parágrafo**. Sem o membro, o conjunto é vazio e você descobre tarde. Sem o não-membro, a condição é trivial e não decide nada. **Em critério de decisão é obrigatória.**

Por que o critério de decisão é onde mais se erra: todo o resto do design tem **consumidor mecânico** que protesta — a função é chamada na página seguinte, o índice é criado por uma migration, a invariante ganha teste no CI. **O critério de decisão é o único artefato cujo consumidor é um humano num ciclo futuro** — e humano não levanta `TypeError`. Quem lê *"toda cobrança recebida precisa ter conta informada"* assente, porque a frase é razoável; e ela é razoável **e** insatisfazível, sem nada entre as duas que dispare. Não erra por ser difícil: erra por ser a única seção sem ninguém para contradizê-la.

Custo de aplicar, medido nos quatro casos reais que teria pego: 2 a 5 segundos cada. Nenhum exigia mais análise — todos exigiam **um exemplo**.

**Ondas** (renumeradas — a numeração antiga em qualquer doc anterior a 30/07/2026 aponta para outro conteúdo): `0 ✅ → 1 ✅ → 2 ✅ (origem do movimento) → 2b (aplicação) → 3 (payout) → 4 (import OFX) → 5 (match) → 6 (baixa de Contas a Receber, **bloqueada** pelo vínculo ausente `platform_earnings → transaction`, mesmo pré-requisito do estorno de cobranças descartado acima)`. Critério da ordem: **dependência externa crescente** — 2, 2b e 3 não dependem de nada fora do repositório.

**A Regra da Origem** (Onda 2, `docs/architecture/controle-bancario-onda2-design.md`): todo evento que o sistema já emite e que move dinheiro no banco **escreve o movimento bancário**; a porta manual e a importação existem para o **resíduo**, e só o resíduo justifica o custo delas. Antes de desenhar a porta de entrada de um plano de dados novo, enumere os eventos que o sistema já emite e ligue-os primeiro — foi não fazer isso que produziu o erro do gate acima.

- [x] **A validação em ~360px de Contas & Saldos FOI FEITA (2026-08-10)** — ver "360px: alvo de toque é 44px" na seção da Onda 2, abaixo. Largura passou (`scrollWidth` 360, valores inteiros); o que estava quebrado era o **alvo de toque**.
- **[CORRIGIDO — UX-001]** `"no banco"` nomeava sentidos **opostos** em duas telas: na Projeção é o saldo que o e1p **calculou**; na Conferência era o que o **banco atestou** — as duas pontas exatas da comparação, com a mesma palavra. **A correção foi do lado da Conferência** (decisão do fundador): as colunas viraram **"O que o banco diz"** × **"O que o e1p calculou"**, pareadas sob uma legenda comum e numa faixa visual compartilhada, e a frase da tela passou a usar o mesmo par. **`ROTULO_BANCO` da Projeção foi mantido de propósito:** ali o rótulo diz *onde está o dinheiro* (a parcela irmã é `ROTULO_PLATAFORMA`, outro **lugar**, não outra testemunha), e qualquer sinônimo locacional encostaria em `TOTAL_EM_CONTAS_LABEL`/`DISPONIVEL_CAIXA_LABEL` — trocando esta colisão por aquela que a divergência D-6 já pagou para separar. **A garantia é a invariante, não o nome:** `"no banco"` tem **um** consumidor (a parcela da Projeção), e agora tanto `ContasSaldosPage` quanto `ConferenciaPage` têm teste provando que não a reusam. Regra que fica: **nunca use "no banco" para nomear um saldo que o e1p não calculou** (checkpoint declarado, `<LEDGERBAL>` de OFX) — para esse lado o vocabulário é "o que o banco diz". Ver `docs/stories/8.7.story.md` (seção UX-001).
- **Dívida:** a virada de mês apaga uma conferência recente e bem-sucedida — a janela do Diagnóstico é o mês da DRE, então um saldo declarado em 28/06 que bateu exato vira 🟡 em 01/07. O motor tem o número de dias e não o usa (SIG-001).
- **Dívida:** `audit.record(target='')` em **17 call sites** — `acc.id` ainda é `None` quando `audit.record` roda logo após `db.add()`. O módulo `bank` faz `db.flush()` antes e está correto; `chart_of_accounts`, `cost_centers` e `crm` gravam trilha apontando para lugar nenhum (MNT-001).
- **Dívida:** `test_tenancy_guard.py` só varre `*/router.py` — um `service.py` que abrisse sessão global passaria batido. Auditado nesta onda: **nenhuma violação hoje**.
- **Dívida:** o gate global `test_todo_saldo_declara_origem` (varredura de contrato exigindo par de proveniência para todo campo de saldo) foi **adiado com registro formal** — hoje a cobertura é por instância. Inventário no artefato de QA: 14 campos `saldo_*_cents`, 6 sem irmão, mais 8 campos de saldo que o regex nem alcança.
- **Dívida:** `days_since_last_declared_balance` implementada e **sem consumidor**.
- **Dívida:** `packages/shared-types/src/generated.ts` defasado desde o PR #45, com **zero** menções a `bank` e sem check de drift no CI.
- **Dívida:** `scripts/check.sh` resolve `ruff`/`python` do PATH (que pode não ser o do venv) e **mascara falha de frontend** com `|| true` no vitest — rode as etapas individualmente até isso ser corrigido.
- ~~**Dívida:** o Epic 5 nunca foi documentado aqui.~~ **FECHADA em 2026-08-07** — ver a seção
  "Financeiro: Inteligência Financeira (Epic 5)" acima. A camada que o Epic 8 ancora agora está
  escrita. E a causa raiz foi fechada junto: a entrada no CLAUDE.md virou **AC obrigatório de toda
  story** (§5, passo 4) — documentar deixou de ser o último passo, que é o passo que se corta.

### Onda 2 — a origem do movimento (Stories 8.9–8.20, PR #71, 2026-08-04)

Antes dela o razão bancário era livro em branco: **nada no e1p escrevia nele**, e baixar uma conta a
pagar não gerava movimento bancário nenhum. É por isso que a divergência da Onda 1 media a ausência
de uma porta e não o furo (a correção do gate acima). A Onda 2 abre a porta: **todo evento que o
sistema já emite e que move dinheiro numa conta real escreve o movimento, na mesma transação**, e a
porta manual e a importação passam a existir só para o **resíduo**.

⚠️ **As migrations desta onda são a `0064` e a `0065` — não a `0061`/`0062`.** As stories e o gate de
QA dizem `0061`/`0062`; foram renumeradas no merge, porque as frentes de WhatsApp (`0062`, `0063`,
`0066`–`0072`) e do fuso do tenant (`0073`) entraram no meio. A 8.18 exigia ler `alembic heads`
**programaticamente** antes de escrever o `down_revision` e por isso não quebrou; as que copiaram o
número do documento erraram **todas as vezes**. Vale para a baseline de testes também: as stories
declararam `1051/22/304` da 8.9 até a 8.20, contra `1451/38/476` medidos pelo gate. **O repo vence o
documento, e a divergência se mede antes de começar, nunca depois de o CI ficar vermelho.**

#### 1. A classe de defeito que mais custou: o documento que afirma sobre a camada de baixo

**Quatro vezes neste épico um comentário ou docstring descreveu o comportamento de outro módulo, e
nenhuma das quatro tinha código atrás.** Não são descuidos isolados — é uma classe, e é a que produz
os defeitos mais caros porque *desliga quem viria conferir*:

- **A docstring que matou 36 testes.** `_validate_reference_date` dizia que declarar o saldo na data
  de abertura é *"o caso mais sadio que existe"* e que **"a comparação vale"**. A premissa está
  certa — a data pode ser gravada sem inconsistência, que era a pergunta **da 8.4**. A conclusão
  responde a pergunta **da 8.5** (*"esta comparação detecta alguma coisa?"*), cuja resposta é **não**,
  pelo mesmo motivo. **Duas perguntas, uma resposta, sinal trocado.** Consequência: dos 36 testes de
  `test_bank_reconciliation_report.py`, **zero** exercitavam o caso de propósito — quem foi escrever
  o teste leu que o caso era o mais sadio que existe e foi testar outra coisa. E havia uma **segunda
  ponta** repetindo a frase (a docstring de `test_data_igual_a_abertura_e_aceita`), que confirmaria o
  erro para quem fosse conferir. Corrigido pela 8.20; hoje um teste assere que a docstring **não**
  contém `"a comparação vale"` e **contém** `"tautológica"`.
- **A Regra da Origem (d) existia só em prosa.** A 8.9 escreveu *"movimento de origem do sistema não é
  editável nem ignorável"* na docstring, e o comentário em `update_transaction` afirmava que a edição
  *"é impedida antes, pela Regra da Origem (d)"* — **sem nada no código**. Nem `update_transaction` nem
  `ignore_transaction` olhavam para `tx.source`. Qualquer perna de transferência e todo movimento de
  `payable`/`charge` desde a 8.12 podiam ser **ignorados pela tela**, e ignorar uma das duas pernas de
  uma transferência produz na Conferência uma divergência com a aparência exata de lançamento
  faltante. A 8.18 teve de implementar a guarda que deveria herdar (`_recusa_se_origem_do_sistema`,
  `bank/service.py:1167`, escrita contra `SOURCES_SISTEMA`, nunca contra `'transfer'` solto).
- **`app/scripts/bank_audit.py` era citado como ativo existente em três documentos e nunca existiu.**
  O epic mandava "não recriar" um script inexistente. Sem o `grep` do @po, o @dev o teria criado
  inteiro — escopo inventado. A obrigação virou **teste**, não script.
- A quarta é a entrada de CPF/CNPJ do §6.1 deste arquivo, que induziu a 8.2 a especificar validação
  fraca.

> **A regra que fica:** *"o valor é bem definido"* e *"o valor é informativo"* são afirmações
> diferentes, e a primeira **não implica** a segunda. Toda vez que uma docstring de validação (que
> responde *"posso gravar isto?"*) opina sobre o **consumo** do dado (*"e serve para X"*), a opinião
> está fora da jurisdição de quem a escreveu — e **não vai ter teste, porque o teste dela mora no
> outro módulo**. Uma afirmação sobre o comportamento de outra camada é verificável; verifique-a ou
> não a escreva.

#### 2. O teste que passa e não prova nada — oito ocorrências independentes

Foi a família dominante da onda. Quase toda armadilha cara aqui foi **teste verde sobre código
errado**, e o mutante foi o único instrumento que as achou. As formas, todas reais:

- **Afirma o mecanismo, não o efeito.** `expect(linha.className).toContain("flex-wrap")` passou com a
  `FilaPagamentosPage` **quebrada em produção por duas sessões**: `flex-wrap` sozinho não quebra a
  linha quando a descrição é `min-w-0 flex-1` (`flex: 1 1 0%` encolhe até caber, e o wrap nunca age).
  Duas auditorias estruturais deram confiança; a terceira sessão — a primeira com stack de dev viva —
  viu a tela. Custou o **terceiro** PR de fix de campo por 360px (#89, 2026-08-06), depois dos #56 e
  #58 que o epic já contabilizava. **Layout só se prova medindo.**
- **Par de recortes complementares sem caso na borda.** O mutante `posted_at > since` → `>=`
  **sobreviveu a 58 testes verdes**: todos os cenários usavam data futura, e a borda era o único lugar
  onde os dois recortes podem se sobrepor. Regra: **um teste em cada lado passa com os dois
  operadores** — a invariante tem de ser escrita como partição (`(…, hoje]` e `(hoje, …)`, sem
  sobreposição e sem buraco).
- **`and` de duas condições com um caso só.** A guarda `fitid IS NULL AND import_batch_id IS NULL`
  era testada com as duas setadas juntas; remover metade mantinha a linha viva pelo outro marcador.
  **Uma condição, um caso.**
- **Asserção por substring genérica.** `"trilho" in detail` casava também com *"fora do trilho"*, e a
  guarda podia ser removida sem ninguém notar. A distinção importa fora do teste: mandar quem tem
  dinheiro na Carteira para *"use a edição da cobrança"* leva o dono a um lugar que não resolve.
- **O cenário não produzia o estado que o teste dizia medir.** Um teste de dupla contagem de agendada
  agendava *"para hoje"* — e a borda é estrita (`paid_on == hoje ⇒ paid`), então **não havia
  `scheduled` nenhum no banco**. Verde, medindo o vazio. Hoje a pré-condição (`status == "scheduled"`)
  é asserida **antes** de o número ser medido.
- **Um teste caía no caso degenerado por acidente e passava por causa do bug.**
  `test_checkpoint_na_borda_do_start_serve` usava `opening_date` e `reference_date` iguais. Consertado
  **na fixture**, com a docstring dizendo **por que** a data foi afastada — senão a próxima pessoa
  "simplifica" de volta.
- **Gate estático não vê o que não é import.** Uma anotação `-> "Payable | None"` **em string, sem
  import nenhum**, passa nos dois gates da 8.9 (AST *e* texto cru). Só morre com um gate que proíba a
  **string** em qualquer posição. E o mutante `importlib.import_module("app.modules." + "pay" +
  "ables")` **sobreviveu ao gate de QA** — teto conhecido de qualquer gate estático, registrado como
  INFO e não como falha.
- **O remédio óbvio cobre um ramo e deixa o outro.** *"Se a divergência der zero, ignore"* resolve o
  🟢 falso e **deixa vivo** o ramo em que as duas declarações discordam e o produto manda o dono caçar
  um lançamento que não existe. Só o teste do segundo ramo mata o mutante.

> **A regra que fica, escrita na 8.9 e reconfirmada na 8.14:** **um mutante que nenhum teste mata não
> é um teste faltando — é um teste do TIPO ERRADO.** E: restaure mutação por **cópia de arquivo, nunca
> por `git checkout`** — um `checkout` sobre arquivo com trabalho não commitado já apagou uma sessão
> inteira nesta onda.

#### 3. O épico quase se auto-aprovou, duas vezes

`derived_balance(until=opening_date) ≡ opening_balance_cents` **por construção** (`_movements_sums`
usa `posted_at > opening_date`, estrito). Então declarar o saldo no dia da abertura produz
`divergencia_cents == 0` com qualquer tolerância, satisfaz `todas_batendo` e emite **🟢 "Está tudo
batendo"** para um tenant com 45 contas pagas e razão bancário **vazio**. É a mesma família do erro do
gate: **um número que mede a própria incompletude com aparência de fato.**

- **A correção é "não avaliável no bloco 1, VÁLIDO no bloco 4"** — o degenerado é a **comparação**, não
  a **declaração**. *"O saldo da conta no dia em que ela abriu"* é verdade, e recusá-la com 422
  apagaria uma afirmação verdadeira: o inverso do princípio da Onda 0. **Rejeitado também "aceitar e
  apenas anotar ao lado"** — é a pior das três: **uma nota que convive com o verde perde para o
  verde.**
- **A segunda porta era materializar o saldo de abertura como checkpoint** (a direção "natural", e o
  que a 8.19 quase fez). Injetaria exatamente o mesmo 🟢, agora **no dia do cadastro**. A diferença que
  importa: um checkpoint que o dono declara **por ato** pode valer qualquer número; o materializado
  **não pode** — ele é literalmente a âncora do derivado. **Um checkpoint que a conferência precisa
  ignorar não é um checkpoint.**
- **Por isso a 8.20 tinha de mergear ANTES da 8.16** (epic §6.1): a 8.16 consome o bloco 1 para o sinal
  de completude, e com a comparação degenerada de pé o épico ganha um caminho para emitir 🟢 no mesmo
  ciclo em que a nota do bloco 4 diria que o gate ainda não pode ser lido.
- **O 🟢 é segurado por `divergencia_cents is not None`, não pelo contador de dias** — sutileza que a
  8.19 poderia ter quebrado sem perceber ao fazer o contador nunca mais ser `None`.

#### 4. A premissa sobre o dado que ninguém verificou com o dono — três em três semanas

A 8.19 nasceu com **duas premissas falsas**, as duas mortas por uma frase do fundador:

- a heurística `opening_balance_cents != 0` para separar *"digitou"* de *"aceitou o default"* — morta
  por *"o zero é pq cadastrei a conta com saldo zero no dia de hoje… então o zero é consciente"*. A
  regra excluía **exatamente quem deveria incluir**, com falso negativo **silencioso**;
- *"a Projeção está afirmando sem lastro em produção"* — morta por *"é o saldo real hoje"*. Com R$ 0,00
  real e ~R$ 18.000/mês de saída, *"Caixa no limite (0 dias)"* e os 4 críticos eram **verdadeiros**. A
  tela estava certa; a story é que estava errada.

Custou dois desenhos e reduziu a story de *"entra na frente de toda a Onda 2"* para **três arquivos de
leitura**. Com o epic §1.2 (a falha de escopo) e a §3.1.1 (o erro do gate), são **três em três
semanas** do mesmo padrão: uma premissa plausível sobre o estado dos dados, **não verificada com o
dono**, que quase virou construção. É a origem da **regra da instanciação obrigatória** acima.

⚠️ **Risco operacional que fica, e que nenhum sinal do produto avisa:** entre recuar a `opening_date`
de uma conta e terminar de repagar as contas legadas, `derived_balance(hoje)` semeia a Projeção com o
saldo antigo **apresentado como saldo de hoje** — runway longo demais e alerta de janela negativa
**calado**. Faça recuo e repagamento **na mesma sessão**; se partir em dias, **Projeção e Diagnóstico
não devem ser lidos no intervalo.** O sistema não distingue *"conta dormente"* de *"tudo aconteceu e
nada foi registrado"*. A ordem do mutirão também não é negociável: recuar a abertura declarando o
saldo daquele dia → estornar → repagar informando conta e data. Invertida, deixa contas estornadas e
**nenhuma repagável** (o piso de `_validate_posted_at` recusa com 422).

#### 5. O gate NÃO abre "depois da Onda 2" — corrige o que este arquivo dizia

A pré-condição, lida ao pé da letra (*"toda cobrança recebida precisa ter conta informada"*), era
**insatisfazível**: pela Invariante do Trilho uma `Charge` do trilho tem `transaction_id` e **nunca**
terá `bank_account_id` — e o trilho é o caminho normal do produto. A ratificação a reescreveu em
quatro termos, cada um com o predicado que o decide e a **onda que o zera**: **P1** baixa de Contas a
Pagar sem conta (Onda 2) · **P2** recebimento fora do trilho sem conta (Onda 2) · **P3** rendimento de
aplicação sem perna bancária (**Onda 2b-i** ✅, ver abaixo) · **P4** payout da Carteira (**Onda 3**, hoje vazio por
construção — `request_payout` só marca `withdrawn`).

**Consequência que muda a leitura do épico:** o gate abre depois da Onda 2 **apenas para um tenant
cujos únicos eventos que movem conta real sejam P1 e P2**. Quem registra rendimento de aplicação
precisava da **2b-i** — ✅ **entregue**, ver a seção dela abaixo; quando o payout virar real,
precisa da **3**. Não é escopo novo — P3 e P4 sempre foram termos da divergência.

⚠️ **O achado A-1, que teria fechado a métrica primária do épico para sempre.** A `Charge` sintética
de rendimento (`investments/service.py`, Story 5.6) nasce `paid` com `transaction_id=NULL` **e**
`bank_account_id=NULL` — caía **inteira** na população do termo P2. Para quem tem conta de
investimento (o fundador tem), o gate **nunca abriria**, e o defeito não se anunciaria como defeito:
se anunciaria como *"a pré-condição ainda não foi satisfeita, continue corrigindo lançamentos"*, para
sempre. **Dois @sm trabalhando em paralelo: a 8.15 lembrou o predicado `_not_investment_yield()`, a
8.16 esqueceu.** O predicado é **importado de `receivables/service.py`, nunca reescrito** — a guarda de
lógica ternária SQL (`coalesce(external_ref, '')`) que ele carrega é o que um reescritor perderia,
excluindo **todas** as cobranças normais em silêncio.

#### 6. O acoplamento invisível que segura a Projeção (leia antes de tocar em `projection.py`)

O recorte que impede a dupla contagem no dia agendado tira a agendada de `_window_sums` **confiando**
que o movimento já está no `saldo_inicial`. Isso só é verdade porque **`_saldo_inicial` passa
`until=today`**. Trocado por `None` ou por `SEM_CORTE`, a agendada futura passa a contar **nos dois
lugares**, em silêncio, pelo lado oposto — num arquivo que a story do recorte declara **não tocar**.
O comentário que já existia ali dizia **por que** o argumento existe, mas **não dizia o que quebra** —
e o que quebra está noutro arquivo. Hoje há um espião sobre `active_balance_total` capturando o kwarg
`until`: **é o que torna o recorte auditável, e não só correto hoje.**

Pelo mesmo motivo `active_balance_total` **manteve** o default antigo quando `derived_balance` e
`derived_balances_as_of` mudaram o significado de `until=None` para "hoje". A assimetria é
**deliberada e testada** (`test_active_balance_total_so_e_chamada_com_until_explicito`); uniformizar as
três é decisão de Onda 2b/3 e **exige revisitar esta seção junto** — não é limpeza de passagem.

#### 7. Decisões cujo motivo some no código

- **A idempotência é o índice único parcial `(tenant_id, source, origin_id) WHERE origin_id IS NOT
  NULL` — NUNCA o `dedup_hash`.** No manual, `_manual_dedup_hash` chaveia no **UUID da própria linha**,
  único por construção: **nunca deduplica nada**. Ele existe para o pipeline de importação. E
  `origin_dedup_hash = sha256(f"{source}|{origin_id}")` é **sem** `bank_account_id`, de propósito —
  trocar a conta de um lançamento é **UPDATE da mesma linha**, e com a conta no hash deixaria de ser.
  ⚠️ A justificativa escrita no AC da 8.9 para a cláusula parcial era **falsa** (`NULL` é distinto de
  `NULL` em índice único por padrão) e o mutante que a removia **sobreviveu**. A cláusula fica por
  tamanho/intenção e por não depender de um comportamento que é **configurável desde o PG15**
  (`NULLS NOT DISTINCT`).
- **`tenant_id` é a PRIMEIRA coluna do índice único** porque **índice único é global e não respeita
  RLS**: sem isso o tenant B receberia violação inexplicável causada por dado do tenant A — bug **e**
  vazamento de existência. Lição já paga na 8.2.
- **`origin_id` é `VARCHAR(64)`, não 36 nem 48.** Ele não é "o id do lançamento": é **chave de
  origem** — perna única = id; multi-perna = `f"{id}:{perna}"`. Em Postgres `VARCHAR(n)` é
  armazenamento variável (64 e 36 custam o mesmo em disco), mas errar para menos custa `ALTER COLUMN`
  **sobre tabela com dado sob `FORCE RLS`**. Só a transferência quebraria, e só em produção:
  `f"{uuid}:out"` tem 40 chars. `test_origin_id_cabe_na_coluna` varre **cada forma de chave** do
  repositório e reprova em CI, não no `ALTER`.
- **Transferência = duas pernas `:out`/`:in` pareadas por `transfer_id`.** A forma "o mesmo `origin_id`
  nas duas + índice relaxado" **destrói a idempotência onde ela mais importa**: um retry move o
  dinheiro duas vezes. E a alternativa "coluna `leg` no índice" destruiria a garantia para **todas** as
  origens em silêncio, porque `leg` seria `NULL` em toda origem de perna única.
- **`scheduled` é estado próprio, não `paid` com data futura** — rejeitado por **bug verificado**, não
  por gosto: com `paid`+futuro a conta sai dos fluxos de saída **e** o movimento não entra no saldo, e
  os R$ 5.000 agendados **somem por completo da Projeção**. A máquina de falso negativo da Onda 0
  ressuscitada, na mesma tela que a Onda 0 consertou. O estado é **derivado da data** (`scheduled ⟺
  paid_at.date() > hoje`), a API nunca aceita `status` do cliente, e **o worker não é componente da
  aritmética**: o movimento nasce com `posted_at` na data agendada e o saldo é função da data — entra
  sozinho quando o dia chega. O worker só move o `status`.
- **O estorno APAGA o movimento.** Um movimento bancário é a afirmação *"este dinheiro saiu"*;
  estornado, o sistema não afirma mais isso. Rejeitados: **contrapartida `+valor`** (inventa um crédito
  que nunca existiu, e na Onda 4 a importação acharia dois órfãos irreconciliáveis) e
  **`status='ignored'`** (é julgamento do dono, não estado de sistema — e **colide com o índice único**
  no repagamento).
- **Não existe coluna `payment_route`.** A rota é **derivada** dos dois ponteiros; um rótulo separado
  pode divergir do fato e vira a terceira fonte de verdade. Gate de AST reprova o nome em qualquer
  posição, **inclusive como kwarg**.
- **`bank` não importa `payables`/`receivables` — e a saída não é import lazy nem SQL cru.** Os dois
  seriam **evasão**, e *"evadir um gate é pior do que quebrá-lo às claras"*. A forma é **porta de saída
  registrada**: `Protocol` + DTO com `referencia_id` **opaco** (o campo não pode nem **nomear** um
  conceito do outro módulo), implementação no módulo de negócio, fiação em `app/main.py`. **O gate fica
  verde porque a dependência sumiu.**
- **Fail-closed é de BOOT, não de request.** A app **não sobe** sem o probe registrado. *"Um erro de
  fiação é condição de startup"* — e um 500 numa ação legítima do dono (lançar uma tarifa de R$ 2,90)
  é o pior lugar imaginável para descobrir que o `main.py` não ligou um `Protocol`. Precedente: a
  guarda do `JWT_SECRET` fraco. E o probe não registrado faz o relatório **recusar**, nunca devolver
  zero: **zero por ausência de medição não é zero**, e a tela diria por omissão *"nenhum termo
  pendente"* — a leitura errada que já custou uma decisão de produto neste épico.
- **`SEM_CORTE = date.max` é feio de propósito, e a feiura é a funcionalidade.** Não existe
  `incluir_futuro=True`: um booleano seria discreto, e discrição é o que não se quer num campo que
  inclui o futuro num saldo. Assim a decisão fica **visível no diff** e uma busca por `SEM_CORTE` lista
  todos os lugares que a tomaram.
- **Conta de outro tenant devolve 404, não 409** — 409 vazaria existência. Com zero contas próprias
  todo id recebe 409; com contas próprias, um id alheio recebe 404.
- **O seletor de conta e a data vivem DENTRO da mesma barra fixa do botão**, com teste de co-localização
  por ancestral comum — porque **dois PRs de fix já foram pagos** por elemento fora da área visível, e
  numa delas uma conta real foi marcada paga sem o usuário conseguir ver o checkbox. Pré-selecionar a
  conta primária **não** torna o campo opcional: o AC exige o nome da conta **no próprio botão**
  (*"Anexar e dar baixa · sai do Itaú PJ"*), porque um default invisível é na prática um campo pulado.
  Sem conta primária, **nada** é pré-selecionado e a ação fica desabilitada — **silêncio, nunca um
  palpite.**
- **Nomear um débito inocente é pior do que ficar calado.** O critério de casamento do débito suspeito
  é `|valor − divergência| <= max(R$ 50, 10%)`, não `[0,5×, 2×]` — o fator 2 casaria um débito de
  R$ 5.000 com uma divergência de R$ 2.500. **Um sinal por relatório, não por cobrança**, e sem opção
  de desligar: *"o dono que mais precisa é o que desliga"*. E **nenhuma palavra** sobre split, taxa ou
  receita da e1p no texto: recebimento fora do trilho é vazamento de receita da plataforma, mas a
  decisão é informação **neutra ao dono, nunca reportada ao Master**.
- **O nome "agendamento suspeito" foi banido por varredura de texto.** Depois que o worker promove
  `scheduled → paid`, **nada no dado distingue** *"agendei e o banco não executou"* de *"paguei no
  caixa e o banco não compensou"* — o adjetivo não sobrevive ao worker. Virou `debito_nao_confirmado`,
  e uma varredura reprova o **radical "agendad"** no motor e na tela, para a renomeação não ser
  desfeita por um *"voltei o nome antigo, ficou mais claro"* daqui a três meses.
- **A natureza do lançamento manual não é whitelist rígida** — texto curto, vocabulário sugerido,
  *"Outro (descreva)"* sempre aceito: *"o extrato está cheio de coisas que não imaginamos; recusar um
  fato bancário legítimo porque não está na lista recria a incompletude que a onda combate"*. A
  obrigatoriedade é **de UI**; a API segue aceitando `null`, senão todo movimento legado quebraria.

#### 8. O que ficou aberto

- **Dívida:** ⚠️ **`charges.bank_account_id` continua SEM o índice irmão.** `payables` tem
  `ix_payables_bank_account`; `charges` não tem, e o caminho de leitura do gate filtra por essa coluna
  a cada diagnóstico. Assimetria sem justificativa escrita — **verificada ainda aberta em 07/08**.
- **Dívida:** ⚠️ **o débito suspeito casa conta por `bank_account_name`**, e `bank_accounts` **não tem
  unicidade de `name` por tenant** (o único índice único é `(tenant_id, institution_code, branch,
  number) WHERE number <> ''`). **Duas contas "Itaú" no mesmo tenant fazem o débito de uma explicar a
  divergência da outra** — e o produto nomeia a conta errada, que é o modo de falha que o próprio
  epic diz ser *"pior do que ficar calado"*. Resolver exige `bank_account_id` em
  `CompletenessAccountInput`. **Verificada ainda aberta em 07/08** (`engine.py:480`).
- **Dívida:** **a lista de caminhos de mutação do design §3.3 ainda tem CINCO** — *baixar, trocar
  conta, trocar data, estornar, repagar*. O gate achou o sexto (**cancelar**) da pior forma: cancelar
  uma conta a pagar agendada deixava o movimento bancário **órfão**, e
  `test_cache_de_movimento_nunca_diverge_do_origin_id` **passava**, porque cobria exatamente os cinco
  enumerados. **A lista era a garantia, e a garantia estava incompleta.** O defeito está **corrigido**
  (`cancel_payable` recusa `scheduled` com 409, regressão em `test_payables.py:185`), mas **a lista
  não foi para seis**. Quem enumerar casos como prova de completude: a enumeração é o teto da
  cobertura, não a cobertura.
- **Dívida:** **`operation_nature` não entrou em `BankTransactionUpdate`** — preencher a natureza de um
  movimento legado **pela tela de edição não é possível hoje**. Verificada aberta.
- [x] **360px: alvo de toque é 44px, e a suspeita sobre o `TotaisCard` NÃO se confirmou** (medido
  em 2026-08-10). O `flex-wrap` puro **empilhou certo**: `scrollWidth` da página = **360**, zero
  elementos fora, zero texto cortado, e `R$ 179.570,79` / `R$ 128.450,79` / `R$ 3.000,00` aparecem
  INTEIROS. A preocupação herdada da 8.13 não se materializou aqui — com número.
  - O que estava quebrado era outra coisa: **34 dos 35 controles tinham menos de 40px de altura**.
    As sete ações por conta ("Declarar saldo", "Lançar movimento", "Transferir entre contas",
    "Conferir", "Ver movimentos", "Editar", "Arquivar") eram links de texto de **16px**, com
    "Arquivar" — destrutiva — a 4px de "Editar", e "Mostrar arquivadas" era um checkbox de 13×13.
    É a classe do PR #56, no alvo que o polegar erra.
  - Agora: `ACAO_DA_CONTA` (**uma constante, sete consumidores**) com `min-h-[44px]`, e 44px na
    linha inteira do "Mostrar arquivadas". O padding cresce, a fonte não — o cartão fica mais alto
    e rolar na vertical é nativo e gratuito; errar "Arquivar" não é. Travado por
    `apps/web/e2e/toque-360.spec.ts`.
- **Dívida:** `contas_sem_checkpoint` virou **nome impreciso** — passou a contar também as contas com
  checkpoint degenerado. O **texto** de todas as superfícies foi corrigido para *"não avaliada(s)"*; o
  **nome do campo de API** não. Decisão consciente: renomear campo de contrato por precisão semântica,
  com a nota já dizendo a verdade na tela, custa mais do que ganha.
- **Dívida:** o OpenAPI da rota de conferência descreve **um** dos dois motivos de `indisponivel` —
  quem ler a doc conclui que `indisponivel ⇒ saldo_banco_data === null`, e o discriminador é
  justamente o contrário.
- **Dívida:** o 🟡 do Diagnóstico diz *"sem comparação avaliável no período"* nos **dois** motivos, sem
  distingui-los. A **severidade está certa**; falta a precisão do texto, e a nota por conta na tela já
  a tem.
- **Dívida:** `"Agendado para entrar"` nasce **sem consumidor visível** (só ganha valor com recebimento
  fora do trilho com data futura), e `app.worker` **não registra o probe** de contagem dupla — hoje
  inofensivo porque nenhum caminho do worker chama `create_transaction`, com a guarda de boot como
  rede se um dia chamar.
- **Dívida:** SIG-001 (a virada de mês apagando conferência recente) segue aberto e é **vizinho do
  bloco 4** — quem mexer no bloco 4 deve lê-lo antes. Foi mantido **fora** da 8.16 de propósito: fundir
  correção de regra existente com regras novas no mesmo diff tira do gate a capacidade de julgar qual
  mudança quebrou o quê. Mesmo argumento que manteve 8.19 e 8.20 separadas.
- **Dívida:** `generated.ts` **cresceu** nesta onda (duas rotas novas, `bank_transfers`, os campos de
  agendado) e continua sem check de drift no CI.

#### 9. O que foi construído

- [x] **A Regra da Origem** (`bank/origin.py::sync_origin_movement`, migration `0064`) — **a única
  função do repositório que escreve `source ∈ SOURCES_SISTEMA`**, guardada por allowlist de call sites.
  Não commita: movimento e lançamento entram na **mesma transação**. Toda regra é escrita contra os
  **conjuntos** `SOURCES_SISTEMA`/`SOURCES_EXTERNA`, nunca contra valor solto de `source` — porque
  `source` mistura dois eixos desde a `0059` e consertar exigiria reescrever coluna sob `FORCE RLS` por
  estética. **Alimenta `saldo_sistema`, NUNCA `saldo_banco`**: a divergência cair porque o sistema
  passou a saber mais é o objetivo; cair porque um lado foi ajustado contra o outro continua proibido.
- [x] **`until=None` passa a significar hoje** em `derived_balance`/`derived_balances_as_of` —
  pré-requisito de tudo com data futura. Sem ele, um agendamento entra no "Total em contas".
- [x] **Baixa de Contas a Pagar com conta bancária obrigatória** e data editável (default no
  vencimento, por decisão do fundador: *"se estiver fazendo retroativo, é pq não deu certo no dia"*).
  409 acionável `{"acao":"cadastrar_conta"}`, com cadastro embutido que **retoma a baixa**.
- [x] **`scheduled`** — agendar sem sumir da Projeção. Cabe em `String(12)`, e é por isso que **não há
  migration**.
- [x] **Recebimento fora do trilho** (`settle_off_rail`) — o dono declara o Pix que caiu direto na
  conta dele. **Nunca** toca a Carteira, **nunca** cria `Transaction`/`PlatformEarning`. Guardado pela
  **Invariante do Trilho**: para toda `Charge` paga, **exatamente um** de `transaction_id` e
  `bank_account_id` é não-nulo. O caminho do gateway mantém `paid_at = now()` e **não é editável** —
  fato externo atestado por terceiro; editá-lo transformaria uma testemunha em opinião.
- [x] **Diagnóstico e conferência aprendem a onda** — 🟡 de recebimento fora do trilho, desambiguação
  do débito não confirmado, e até **três notas** no bloco 4, uma por termo não-zero, **cada uma
  nomeando a onda que a fecha**. Achatá-las prometeria na tela *"isso some quando você terminar o
  mutirão"* sobre um termo que não some. Zero termos ⇒ zero notas, e **é esse silêncio que sinaliza que
  o gate pode ser lido**. A nota **ANOTA, nunca SUBTRAI** (Regra 5).
- [x] **Manual curado + guarda de contagem dupla** — o formulário pergunta **para que serve**
  (`operation_nature`, coluna que já existia, zero migration); lançar à mão um débito que já tem conta
  a pagar correspondente (mesmo valor, ±3 dias) dá **409 com escolha**, `confirmar_avulso=true` para
  insistir. A janela e o valor exato são **deliberadamente os mesmos** do enriquecimento da Onda 4 —
  dois números para *"estas duas linhas são o mesmo dinheiro?"* seriam duas respostas quando o matcher
  chegar.
- [x] **Transferência entre contas próprias** (`bank_transfers`, migration `0065`) — DRE-neutra por
  construção, com snapshot campo a campo provando; **zero acoplamento com `investments`** (dois gates,
  AST e texto cru); `kind` **derivado** dos dois seletores, sem terceiro campo que possa discordar
  deles. `DELETE` apaga as duas pernas — sem ele, a única correção possível seria a contrapartida que o
  design rejeita nominalmente.

### Onda 2 (correção) — "tenho a conta e NÃO sei o saldo" (Story 8.21, PR #94, 2026-08-07)

**O defeito.** `bank_accounts.opening_balance_cents` é `NOT NULL DEFAULT 0` e o formulário
pré-preenchia `"0,00"` — então *"informei zero"* e *"não informei nada"* eram **a mesma linha**. Uma
conta cadastrada por quem não sabia o saldo virava elegível e a Projeção de Caixa afirmava runway e
alerta sobre um saldo que **ninguém informou**. `ORIGEM_INDISPONIVEL` existia em `core/money_planes.py`
desde a Onda 0 **sem gatilho nenhum**; esta story é o gatilho.

- [x] **`bank_accounts.opening_balance_is_known`** (migration `0074`) — o **ATO** de declarar, ao lado
  do **VALOR**. `false` ⇒ `opening_balance_cents` é **placeholder, não afirmação**.
  - **`opening_balance_cents` anulável foi REJEITADA** pela @architect: quebraria
    `_validate_opening_date_recuo` (Story 8.11), cujo mecanismo inteiro é *"presença é a única coisa
    que a API consegue distinguir de 'não mudou'"* — com a coluna anulável o `None` do `Update`
    passaria a significar duas coisas e a guarda morreria em silêncio. Ela também é a âncora da
    fórmula do §3.1, e `None` ali se propagaria por toda a leitura de saldo.
  - ⚠️ **Migration SEM backfill, e é por isso que é segura.** As armadilhas das `0046`/`0066`/`0067`/
    `0068`/`0069`/`0073` são todas a mesma: `UPDATE` de backfill filtrado em silêncio pela RLS, com
    **sucesso aparente**. `ADD COLUMN` é **DDL, não DML** — a RLS não o alcança. O `server_default=true`
    cobre o legado e **cai no mesmo `upgrade`**: mantido, todo `INSERT` que omitisse a coluna gravaria
    *"eu sei o saldo"* em silêncio. Mesma disciplina de `ai.complete` exigir `db`/`tenant_id`/`task`.
  - ⚠️ **O nome trip um gate estrutural, e isso foi resolvido pelo lado certo.**
    `opening_balance_is_known` contém a substring `"balance"` e faz
    `test_saldo_derivado_nao_e_coluna_no_modelo` falhar — gate que existe para impedir saldo
    MATERIALIZADO. **A exceção lá é nominal e justificada** (um booleano não pode divergir dos
    movimentos); **renomear a coluna para fugir da substring foi rejeitado**: seria deixar o teste
    ditar o vocabulário do domínio.
- [x] **BASTA UMA conta elegível desconhecida para calar a Projeção inteira** (veredito da @architect).
  Somar só as conhecidas erraria nas **duas** direções, e nada na tela diria em qual: como
  `opening_balance_cents` **pode ser negativo** (cheque especial), a parcela que falta tanto subestima
  (alerta grita sem motivo — Regra 7) quanto **superestima** (alerta CALADO quando deveria soar — a
  máquina de falso negativo que a Onda 0 desmontou, atingindo quem tem cheque especial).
  - **As duas obrigações que vêm junto**, sem as quais a escolha seria pior que a rejeitada: **(a)** o
    número continua visível e a composição continua fechando (*suprimir a afirmação, nunca o número*);
    **(b)** a supressão **NOMEIA a saída** via `CashProjection.notes`, dizendo **quais** contas faltam.
    Sem (b) o dono vê o runway sumir e não descobre o que fazer — o beco sem saída do WhatsApp item
    12(b). `notes` já existia e já era renderizado: **zero campo novo**.
  - `_ORIGENS_SEM_LASTRO` (`projection.py`) — **um conjunto, três consumidores.** As duas supressões
    comparavam `== ORIGEM_PLATAFORMA` em três pontos; acrescentar `indisponivel` repetindo a comparação
    deixaria um deles para trás algum dia, e o sintoma seria o defeito desta story sobrevivendo à
    própria correção.
- [x] **A procedência é decidida em UM lugar** — `service.origem_do_saldo_derivado(account)`. Ela
  estava escrita duas vezes no `router.py`, uma por rota que expõe saldo derivado: a **mesma conta**
  por duas portas, e divergindo uma diria `banco` e a outra `indisponivel`. **É a classe que
  `whatsapp.__init__._resolve` já pagou** (item 12 abaixo) — achado pelo `dedup-checker` no gate.
  Gate por varredura AST do router, com controle positivo.
- [x] **O formulário força a escolha nos DOIS modos** (`AccountModal`). Só o cadastro deixaria o
  caminho *"descobri o saldo depois"* sem UI — capacidade de backend sem consumidor. E o backend
  recusa (422) o PATCH que informa saldo numa conta *"não sei"* sem declarar o ato: sem isso o dono
  digita o saldo real, salva, e a Projeção continua calada **sem explicação**. Pior que não ter saída:
  é uma saída que **parece funcionar**.
- **Lição de processo que custou 4 rodadas de validação:** a story levou **três NO-GOs do @po**, todos
  da mesma família — *o artefato descrevia o backend corretamente e não verificava quem o alcança*
  (o router sobrescrevendo o default do schema; o flag sem caminho de tela; o nome da coluna vs. o
  gate). **Nenhum apareceu lendo a story; os três lendo o código ao lado dela.** O que quebrou o ciclo
  foi um **spike de 20 minutos** do @dev, que confirmou os três e ainda revelou que o bloqueio de
  numeração de migration havia caído sozinho. **Regra: quando duas validações de documento seguidas
  falham pelo mesmo motivo, a terceira não deve ser de documento.**
- [x] **O aceite em ~360px FOI MEDIDO (2026-08-10) — e a escolha da 8.21 estava a 467px do botão
  que a efetiva.** Conteúdo de **1010px** numa caixa de **629px** (`max-h-[85vh]`): "Cadastrar
  conta" nascia a 942px do topo do modal, ou seja **y=1043,5 — 303px ABAIXO da borda da tela**. O
  dono escolhia *"Não sei o saldo agora"* (visível em y=528,5) e tinha de rolar 467px dentro do
  modal para achar o botão que tornava aquilo real: **a forma exata do PR #56**, o controle e a
  ação que o efetiva em lugares separados. Os rádios tinham **13×13px**.
  - Agora: **`Modal` aceita `footer`** (`components/Modal.tsx`) — a ação primária vive numa barra
    `sticky bottom-0` DENTRO da caixa que rola, e não sai da tela enquanto o dono preenche. Prop
    **opcional**: modal que não a passa continua idêntico. **Formulário longo em modal DEVE usar
    `footer`.** Alvo dos rádios e de "Conta principal": 44px na **linha inteira** do rótulo, não no
    círculo. O erro continua no corpo — na barra ele empurraria o botão para fora justamente quando
    o dono mais precisa dele. Travado por `apps/web/e2e/modal-conta-360.spec.ts`.
  - ~~**Dívida:** os campos de texto do `Field` têm **38px** de altura (mínimo tocável é 44).~~
    **PAGA no #215** (2026-08-22). A razão de não engordá-los aqui continua boa para o escopo
    daquele PR; o #215 existiu para pagar a dívida com o alcance declarado. Ver "Campo de
    digitação" abaixo.
- **Dívida:** conta `is_known=false` + recuo de data pede um saldo cujo campo está escondido no
  formulário; tem saída (marcar *"sei o saldo"* revela o campo), mas a mensagem de erro pede algo que
  não está visível.

### Onda 2b-i — a perna bancária do rendimento (o termo P3 fecha)

> Spec: `docs/superpowers/specs/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento.md`

**A Onda 2b foi PARTIDA EM DUAS, e o recorte é a decisão.** O §647 do PRD descreve cinco
entregáveis; só dois tocam o gate, e o mais arriscado do épico inteiro (o backfill de
`principal_cents` sob `FORCE RLS`) não é nenhum dos dois. **2b-i** entrega o vínculo e o movimento;
**2b-ii** fica com o principal derivado, o backfill, o 409 de edição e o extrato na tela. Manter o
backfill colado ao destravamento da métrica primária refaria o acoplamento que o épico já desfez
uma vez ao separar a 2b da Onda 2.

#### O achado que motivou o recorte, e que teria custado a onda inteira

`receivables.contar_rendimentos_sem_perna_bancaria` **não verificava se existia perna bancária** —
nenhum join, nenhum `NOT EXISTS`. Contava todo rendimento da janela. Pré-2b era inofensivo, porque
*"todos os rendimentos"* e *"os sem perna"* eram o mesmo conjunto. Ligado o movimento, eles se
separam e P3 seguiria contando o que passou a ter perna: **o gate não abriria nem depois da onda que
existe para destravá-lo**, e a nota continuaria dizendo *"este termo só fecha na Onda 2b"* sobre uma
onda já fechada. O único teste que tocava a função afirmava que ela era `callable`.

> **A regra que fica (reverberar): função cujo NOME promete um filtro tem de tê-lo, mesmo quando o
> filtro é hoje redundante.** Ela esteve certa **por coincidência de população** durante uma onda
> inteira. A coincidência não deixa rastro no código, não quebra teste ao terminar, e o dia em que
> ela termina é exatamente o dia em que a função vira defeito. É a família do §2 desta seção (o
> teste que passa e não prova nada) com um agravante: **aqui o teste correto não podia sequer ser
> escrito** no caminho de produção — o membro que o mataria era inconstruível.

#### O que foi construído

- [x] **`investment_accounts.bank_account_id`** (migration `0075`) — ligação 1:1 com a
  `bank_account` `kind='investment'`. `investment_accounts` **não** é absorvida: ela é a faceta de
  PRODUTO (rentabilidade, indexador), a `bank_account` é ONDE o dinheiro está. Índice único parcial
  com `tenant_id` na FRENTE (índice único é global e não respeita RLS — lição da 8.2). **Sem
  `UPDATE`:** `ADD COLUMN`/`CREATE INDEX` são DDL e a RLS não os alcança; a aplicação que já existia
  é vinculada pelo dono, **por ato**, na tela. Validada contra Postgres real via `rls_e2e`.
- [x] **`register_yield` sem vínculo recusa com 409 acionável** (`{"acao":"cadastrar_conta"}`,
  terceira cópia da string, sincronia por teste). **É isso que põe P3 em zero POR CONSTRUÇÃO** — o
  mesmo mecanismo pelo qual a 8.12 zerou P1. A degradação graciosa da Onda 3 (*"nada acontece, nada
  quebra"*) foi rejeitada aqui, e a diferença é **quem está na sala**: o payout é disparado pelo
  sistema, sem humano a quem perguntar; o rendimento é o dono digitando um valor agora.
- [x] **`register_yield` gera `bank_transaction` `source='yield'`** pelo mesmo
  `sync_origin_movement`, na mesma transação, nascido conciliado. **`SOURCE_YIELD` já estava em
  `SOURCES_SISTEMA` desde a `0059`** — como nenhuma regra do repo é escrita contra `source` solto,
  todas já cobriam `yield` sem uma linha de mudança. Precisa de `db.flush()` antes: o id da `Charge`
  tem default **Python-side** e sem ele o `origin_id` nasceria vazio (o defeito MNT-001).
  **A IV1 da 5.6 NÃO foi relaxada:** `bank_transactions` é o plano do BANCO,
  `Transaction`/`PlatformEarning` são o da PLATAFORMA, e continuam intocados.
- [x] **`posted_at` = data do rendimento, não o instante do registro** — que erraria sempre que o
  dono lançasse com atraso. O resíduo (competência 31/07 × crédito 01/08) é o **termo 3** da
  decomposição da divergência, que a banda de tolerância existe para absorver. **A escolha só é
  barata porque o predicado de P3 é `NOT EXISTS`:** ele pergunta *"existe perna?"*, não *"a perna
  caiu nesta janela?"*. Se a data fosse o eixo do termo, isto seria decisão de gate.
- [x] **Data futura: 422** — a decisão que `bank/transfers.py:185` exigia que a 2b tomasse **em vez
  de copiar**. A razão não é a da transferência: um rendimento que ainda não caiu não é um
  rendimento, e não teria para onde ir — não existe `scheduled` para rendimento, nem superfície,
  nem caminho de promoção (Art. IV). Comparação com `hoje_do_tenant`, nunca com `now(UTC)`.
- [x] **A nota de P3 deixou de nomear uma onda e passou a nomear a AÇÃO** (*"Vincule a aplicação à
  conta bancária dela"*). Ela fica mesmo inalcançável no caminho normal: se disparar, é linha legada
  ou defeito, e apagá-la deixaria a 2b-ii sem quem avise se os dados voltarem inconsistentes.
- [x] **A tela vincula** — seletor único para os dois modais, e no 409 o modal vincula e **reenvia o
  rendimento sem o dono redigitar valor e data**. Sem esta parte o 409 seria um beco: backend
  pedindo um vínculo que não tinha onde ser criado (a classe do item 12 do WhatsApp).

#### Três coisas que só apareceram implementando

- **O gate da allowlist do `sync_origin_movement` pegou o chamador novo, e é para isso que ele
  existe.** `investments/service.py` entrou em `_CHAMADORES_PERMITIDOS` **com a justificativa** —
  que é o que faz a revisão acontecer, e não uma linha na lista.
- **Um teste meu passou ANTES da implementação, pelo motivo errado.** `register_yield` grava
  `paid_at = now()` (o instante do registro) enquanto `posted_at` usa a competência informada: uma
  janela em julho não continha o `paid_at` de um rendimento registrado em agosto, e P3 dava `(0,0)`
  por vacuidade. Corrigido com **controle positivo** (o mesmo rendimento sem perna, que conta).
- **`date.today()` é a data LOCAL e `paid_at` é `now(UTC)`** — às 23h em UTC−3 as duas já são dias
  diferentes, e uma janela de teste de um dia só perdia o rendimento pela borda, em silêncio.

- **Dívida:** o ramo *"origem desliquidada → apaga"* de `sync_origin_movement` é **inalcançável**
  para `source='yield'` (não existe estorno nem exclusão de rendimento; o router só expõe
  `register_yield`). Está na docstring para não parecer esquecimento na 2b-ii.
- [x] **O aceite em ~360px do campo de vínculo FOI MEDIDO (2026-08-10) e PASSOU.** Com o 409
  acionável disparado, o modal de rendimento tem **596px numa viewport de 740** — cabe sem rolagem
  interna, "Registrar rendimento" fica visível sem rolar, o seletor de conta renderiza e a largura
  não passa de 360. Sem conserto necessário. (Os campos de `Field` tinham 38px — dívida geral do
  componente, registrada na 8.21 e **paga no #215**.)
- **Dívida:** ~~a 2b-ii continua com o único backfill do épico, e ele continua sendo o item de
  maior risco.~~ **FECHADA na 2b-ii (2026-08-08): o backfill não foi mitigado, deixou de
  existir.** Ver a seção da Onda 2b-ii, logo abaixo.

### Onda 2b-ii — o principal deixa de ser digitado (e o backfill deixa de existir)

> Spec: `docs/superpowers/specs/2026-08-08-onda-2b-ii-principal-derivado-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-08-onda-2b-ii-principal-derivado.md`

**A onda que era "o item de maior risco do épico inteiro" NÃO TEM MIGRATION.** Todo documento
anterior a ela a descrevia como a onda do backfill — o único `UPDATE` sobre dado existente do
épico, sob a armadilha do `FORCE RLS` (`UPDATE` filtrado a zero linhas **em silêncio**, que o
SQLite dos testes não pega). Duas coisas o dissolveram: a **2b-i já executou os passos 1-2 do
design-mãe §6.2 por ato do dono** (coluna via DDL puro, vínculo pela tela), e
`investment_accounts` está **vazia em produção** (confirmado pelo fundador). Os passos 3-4 não
tinham sobre o que rodar.

> **A regra que fica (reverberar): quando um backfill existe para reconstruir histórico que um
> ATO DO DONO reconstrói melhor, o backfill é o caminho pior.** Ele escreve sem testemunha, num
> regime onde o fracasso é silencioso. Trocar escrita retroativa por *auditoria + ato* foi a
> manobra da 2b-i; esta é a segunda aplicação, e agora é padrão.

- [x] **`principal = opening_balance_cents + Σ movimentos com `source <> 'yield'`.** O saldo de
  abertura entra, e **isso não estava no design-mãe §6.2**: é o dinheiro que já estava aplicado no
  dia do cadastro, principal que nunca teve movimento. Sem ele, uma conta cadastrada com R$ 10.000
  mostraria principal **zero** — número errado com aparência de fato, a família que a Onda 0 existe
  para não repetir. O recorte de `source` impede a dupla contagem: o rendimento já é
  `accrued_yield_cents` e, desde a 2b-i, também é `bank_transaction`.
- [x] **`exclude_sources` entrou em `_movements_sums`, não numa query nova.** A docstring dela já
  dizia por quê: duas cópias da fórmula divergiriam, e o sintoma seria um saldo que muda conforme a
  tela que o pede. `bank.service.movement_sums` é a porta pública fina — existe porque `investments`
  precisava dela e importar um símbolo `_` de outro módulo é acesso que ninguém encontra depois.
- [x] **Saldo de abertura desconhecido ⇒ principal `None`, nunca zero.** Reusa
  `origem_do_saldo_derivado` (Story 8.21) em vez de recomparar `opening_balance_is_known` — foi
  exatamente essa recomparação duplicada que a 8.21 pagou para eliminar. Zero seria a afirmação
  *"você não tem nada aplicado"*, falsa e indistinguível de um saldo genuinamente zerado.
- [x] **A coluna `principal_cents` está CONGELADA** — sem leitor, sem escritor, com gate AST e
  **controle positivo**. Terceiro uso do padrão (`attachments.data`, `tenant_profiles.timezone`).
  **Eram NOVE leitores**, levantados por `grep` **antes de a spec fechar** e não durante a
  implementação — a lição da 0073, onde três consumidores não apareceram na investigação inicial.
  Drop numa migration posterior.
  - ⚠️ **O gate proíbe `<conta>.principal_cents` e PERMITE `data.principal_cents`**, e a assimetria
    tem teste próprio: ler o campo do **request** é como a recusa 409 sabe que alguém tentou editar.
    Quem "endurecer" o gate acrescentando `data` à lista torna a guarda inalcançável e devolve a
    edição do principal — com o gate verde o tempo todo.
- [x] **O DÉCIMO leitor não estava no inventário, e não era do módulo: o Diagnóstico.** A regra 4
  do motor (`engine._investment_signals`, Story 5.6) só avalia quando `period_rentability_pct` não
  é `None` — e essa fração agora depende do principal DERIVADO. Aplicação sem conta vinculada
  deixou de produzir o sinal 🟡 "sem rendimento no período". O inventário do §4.2.1 da spec buscou
  por `principal_cents` e o achou em nove lugares; este décimo **não menciona a coluna** — consome
  a rentabilidade, dois saltos adiante. Quem o pegou foram dois testes de `financial_intelligence`,
  não o grep.
  - ⚠️ **Um deles era o `rls_e2e` do vazamento de PII cross-tenant**, e o modo de falha é o pior
    possível: sem conta vinculada, nenhum sinal cita nome de aplicação, e o teste passaria **verde
    por vacuidade** — sem exercitar o vetor que ele existe para exercitar. A fixture agora semeia a
    `bank_account` junto e continua gravando a coluna congelada de propósito, provando que **não é
    ela** que aparece.
  - **Regra que fica: um grep pelo NOME do dado acha os leitores diretos, e para nos leitores que
    o consomem transformado.** Quem congela uma coluna precisa perguntar também *"quem consome o
    que se calcula a partir dela?"* — aqui a resposta estava a dois saltos e em outro módulo.
- [x] **O leitor que quase passou: `_pct` DIVIDE pelo principal.** Com `None` levantaria
  `TypeError`; com **negativo** devolveria um percentual de sinal invertido — plausível na tela, e
  errado. Agora protege os três casos (`None`, zero, negativo). *"Quanto rendeu percentualmente o
  que você não aplicou?"* não é pergunta com resposta menor: é pergunta sem resposta.
- [x] **Editar o principal: 409, e ele é o OPOSTO do 409 da 2b-i.** Aquele era caminho normal e por
  isso a tela oferecia a saída no próprio modal. Este é **inalcançável pela tela** (o campo saiu do
  formulário): se disparar, é integração antiga ou defeito. Por isso **não** tem `detail["acao"]` —
  um `acao` sem modal do outro lado é contrato com ninguém. A guarda do `create` é sobre o **valor**
  (`if data.principal_cents:`) e a do `update` sobre a **presença** (`is not None`), porque o
  default do schema é `0` num e `None` no outro; a assimetria é deliberada e cada metade tem teste.
- [x] **REQ-25 cumprido na LEITURA, não na escrita — desvio declarado.** O resgate bruto (principal
  + rendimento embutido, que é como o banco credita) deixa o principal negativo. Recusar o resgate
  exigiria `bank/transfers.py` consultar `investments`, que o gate
  `test_bank_transfers_nao_importa_investments` proíbe — e recusaria um fato que **já aconteceu no
  banco**, o inverso do princípio da Onda 0. A tela nomeia a diferença e a ação, e **não adivinha o
  valor** (Artigo IV): o sistema sabe que faltam R$ 500 e não os lança sozinho.
- [x] **`app/scripts/investment_audit.py` — sem `--fix`, e a ausência é a decisão.** Com uma flag de
  correção, alguém a rodaria no deploy sem ler a saída e o `UPDATE` voltaria pela porta dos fundos.
  Imprime **quantos tenants varreu**: `0 aplicações em 0 tenants` e `0 em 7` são resultados
  diferentes, e o primeiro é defeito do próprio script (a lição da sondagem de `phone_key`, onde a
  RLS devolveu zero linhas sem erro e o silêncio quase virou aprovação). Principal `None` **não** é
  divergência: é ausência de comparação, e marcá-la mandaria o dono caçar um erro que não existe.
- [x] **O extrato da aplicação é a SEGUNDA superfície sobre o mesmo razão, de propósito** (decisão
  do fundador). A primeira é "Ver movimentos" em Contas & Saldos — a conta de aplicação é uma
  `bank_account` como qualquer outra. **A garantia contra divergência virou estrutural em vez de
  documental:** `contas.ROTA_MOVIMENTOS` é uma constante com dois consumidores, e um gate por
  `import.meta.glob` reprova a string literal em qualquer das duas telas (com controle positivo
  próprio, senão um glob que deixasse de casar tornaria o gate vacuamente verde).

- [x] **O aceite em ~360px FOI FEITO, com screenshot — e achou um defeito na primeira medição.**
  Depois de três dívidas abertas na fila (8.13 AC9, 8.21, 2b-i) e três PRs de campo pagos (#56,
  #58, #89), esta onda mediu antes de mergear. **O extrato nasceu como `<table>` de 3 colunas com
  `min-w-[20rem]` dentro de `overflow-x-auto`, e em 360px a coluna de VALOR nascia fora da vista:
  a tela mostrava `R$ 3.` no lugar de `R$ 3.000,00`.** Virou lista (`<ul>`): data e descrição
  empilhadas à esquerda num bloco `min-w-0`, valor à direita com `whitespace-nowrap`.
  > **A lição do PR #58 era "role, não corte" (`overflow-x-auto` em vez de `overflow-hidden`), e
  > ela funcionou — não houve corte silencioso. A desta onda é mais funda: em 360px uma tabela de
  > 3 colunas não cabe, e a saída não é fazer a rolagem funcionar melhor, é não precisar dela.**
  > Num extrato o valor é *a* informação, e informação que exige rolagem lateral para existir é
  > informação que o dono não lê. **Nenhuma asserção de classe CSS pegaria isto** — o `overflow-x`
  > estava correto, o `flex-wrap` estava correto, e a tela estava errada.
- ⚠️ **Achado PRÉ-EXISTENTE, fora do escopo desta onda e não corrigido aqui:** em 360px o
  `document.scrollWidth` da tela de Investimentos é **375px** — a página inteira rola 15px na
  horizontal. Medido idêntico **com e sem** o extrato (logo não é desta onda), e ausente em
  Contas & Saldos (345px). Fica registrado com a medição, e **não** foi corrigido junto: misturar
  correção de defeito existente com regra nova no mesmo diff tira do gate a capacidade de julgar
  qual mudança quebrou o quê — mesmo argumento que manteve SIG-001 fora da 8.16 e separou 8.19
  de 8.20.
  - ⚠️ **CORRIGIDO em 2026-08-10, e a atribuição acima estava ERRADA.** Dizia que *"o culpado é o
    `ChevronDown` do menu do usuário em `app/AppShell.tsx:209`"* — atribuição **geométrica, não
    causal**: o chevron é o último elemento da fila, então é sempre ele que sobra para fora.
    Medida a largura mínima da linha por rota: **216px** sem ação primária, **326px** com "Nova
    conta", **375px** com "Nova conta de investimento". Quem decide se cabe é o **comprimento do
    rótulo da ação**. Tirar o chevron compraria 24px e mascararia a classe até o próximo rótulo
    longo. Ver a correção completa abaixo.

- **Dívida:** `packages/shared-types/src/generated.ts` tem `principal_cents` em quatro lugares e
  segue defasado desde o PR #45, sem check de drift no CI. Dívida do épico, não desta onda.
- **Dívida:** REQ-26 (cotização e liquidação em datas diferentes) segue não implementado —
  declarado fora de escopo, não esquecido.
- **Dívida:** o `DROP COLUMN principal_cents` é migration posterior, depois de um ciclo.
- ~~**Dívida:** o estouro horizontal de 15px do `AppShell` (acima) — vale para todas as telas.~~
  **FECHADA em 2026-08-10** — e a atribuição ao `ChevronDown` estava errada. Ver
  "360px: a barra superior reflui" em §5.1 / na seção do shell abaixo.


### Onda 3 — o payout fecha o circuito (o termo P4 zera)

> Spec: `docs/superpowers/specs/2026-08-09-onda-3-payout-circuito-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-09-onda-3-payout-circuito.md`

**Os quatro termos da pré-condição do gate estão fechados.** P1 e P2 na Onda 2, P3 na 2b-i, P4
aqui. A obstrução para ler `|divergencia_cents|` **deixou de ser de código** — passou a ser de
dado (ver o aviso no fim desta seção).

- [x] **O saque virou FATO.** `request_payout` marcava `withdrawn` e não deixava linha nenhuma:
  o dono via o saldo sumir e não conseguia listar o que sacou, quando, nem para onde — o audit
  guardava `target=str(total)`, o **valor**, não um id. Agora existe `payouts` (migration
  **0077**, RLS `FORCE`) e `transactions.payout_id` liga cada venda ao saque que a levou.
  Sem entidade, `sync_origin_movement` não tinha `origin_id` para apontar, e era isso que
  impedia o payout de virar movimento como as outras quatro origens.
- [x] **A migration NÃO tem `UPDATE`** — tabela nova + coluna nullable, só DDL. A armadilha do
  `FORCE RLS` (0046/0066/0067/0068/0069/0073) **não a alcança**, e as `Transaction` sacadas antes
  ficam com `payout_id NULL` para sempre: elas não têm saque a que pertencer, porque o saque nunca
  foi registrado. Inventar um `Payout` retroativo seria escrever história sem testemunha.
- [x] **O ponto de contato entre os planos NÃO é o barramento — e o §6.6 do design-mãe está
  superado nisso.** `core/events.emit` **engole exceção de assinante por contrato** e os dois
  assinantes existentes rodam **depois** do commit; a Regra da Origem (a) exige o movimento na
  MESMA transação. Pelo barramento, um payout commitaria sem perna bancária **e sem erro em lugar
  nenhum**. No lugar dele, o padrão que `main.py` já usava duas vezes (8.17 AC6, 8.16 AC7/AC8):
  a **Carteira declara** `RegistradorDePayout` (`Protocol`), `bank/payout.py` **implementa**, e a
  fiação mora na composição com **fail-closed no boot**. Direção final: `main → wallet`,
  `main → bank`, e **nada** entre os dois.
  - ⚠️ **Os dois gates da Regra dos Planos continuam apertados E SEM ALLOWLIST** — a dependência
    **sumiu**, não foi escondida. `test_bank_nao_referencia_transaction` diz na docstring que quem
    precisar do símbolo o atualize com justificativa: **esta onda não precisou**, e um gate que já
    permite o que ninguém usa não avisa nada quando alguém começar a usar.
  - ⚠️ **O gate por TEXTO CRU reprovou o comentário que explicava o gate.** Ele faz `grep` literal
    e não distingue comentário de código — e isso é **recurso**: um gate "esperto" o bastante para
    abrir exceção a comentário deixaria passar a primeira string montada em runtime (a mutação
    TEST-001). Quem escrever aqui: não grafe o caminho do módulo proibido, nem em comentário.
- [x] **`bank/payout.py` — o QUINTO chamador da Regra da Origem**, e o único que atravessa a
  fronteira dos planos. Recebe `amount_cents` **pronto e positivo**; nunca vê `Transaction`. Tem
  gate próprio (`test_bank_payout_nao_alcanca_o_plano_da_plataforma`) contra o atalho óbvio —
  *"já que ele registra o saque, podia somar as transações sozinho"* —, que poria o cálculo do
  saldo da Carteira dentro do módulo do banco: a mistura exata que originou o Epic 8.
- [x] **O que cai no banco é o LÍQUIDO** (`net_cents`), nunca o bruto. Mandar o bruto criaria uma
  divergência na conferência **causada pelo próprio e1p**, e a métrica que decide as Ondas 4 e 5
  mediria um erro nosso. Tem teste dedicado.
- ⚠️ **MUDANÇA OBSERVÁVEL DE COMPORTAMENTO (R-1): sacar sem conta principal agora RECUSA (409).**
  Antes o saque sempre funcionava. Recusar é legítimo **aqui** porque quem ORIGINA o payout é o
  e1p — ele ainda não aconteceu no banco; o resgate bruto da 2b-ii não podia ser recusado
  justamente porque já tinha acontecido. E custa nada de real: o saque não move dinheiro (sem
  integração bancária nem KYC). `test_payout_withdraws_available` ganhou o pré-requisito e um
  não-membro explícito. **Não "conserte" removendo a conta do teste** — sem o pré-requisito, P4
  reabre e a divergência volta a medir a própria incompletude do sistema.
- [x] **`POST /bank/accounts/{id}/set-primary` — o pré-requisito que NÃO estava na spec e que a
  revisão do plano contra o código achou.** `service.set_primary` existia desde a Story 8.7, com
  docstring dizendo que foi escrito para o consumidor do payout, **sem rota, sem botão e sem um
  único chamador**: a tela só exibia o selo. O dono **não conseguia** eleger conta principal. Sem
  isso, o 409 acima mandaria o dono a uma tela onde a ação não existe e o saque ficaria travado
  para sempre — a onda trocaria um problema silencioso por um barulhento. **Regra que fica: uma
  frase de erro que manda o usuário agir é uma promessa; verifique que a ação existe antes de
  fazê-la.**
- [x] **A primeira conta bancária do tenant JÁ nasce principal** (`create_account`,
  `is_primary=primary_account(db) is None`). Então *"tem contas e nenhuma principal"* só acontece
  **depois de arquivar a principal** — arquivar não elege sucessora em silêncio (AC7). O caso é
  mais raro do que a spec supunha, e o teste exercita o cenário que existe de verdade.
- [x] **Histórico de saques** (`GET /wallet/payouts`) dentro da própria Carteira — **não** item de
  menu (a Conferência já ensinou que tela nova no menu vira peso de ERP). É `<ul>`, nunca
  `<table>`, com teste que **reprova a tabela**: a lição da 2b-ii é que em 360px uma tabela de 3
  colunas não cabe e a saída não é rolar melhor, é não precisar. Data por `formatDay`
  (`lib/datetime`) — `new Date("2026-08-09")` leria UTC e mostraria o saque do dia 9 como dia 8.
  - ⚠️ **A ordenação ganhou desempate por `id`, e não é decoração:** `created_at`
    (`server_default=now()`) tem resolução de **segundo** no SQLite, então dois saques no mesmo
    segundo saíam em ordem arbitrária — que inclui **mudar entre duas chamadas idênticas**. O
    teste SQLite afirma **estabilidade**; a ordem cronológica de verdade é afirmada no `rls_e2e`,
    onde o Postgres tem microssegundo. Dentro do mesmo instante não existe "mais novo", e um teste
    que o afirmasse estaria testando o acaso.
- [x] **Cockpit: os dois planos lado a lado, e nunca somados.** `saldo_em_conta_cents` +
  `saldo_em_conta_origem`, reusando `TOTAL_EM_CONTAS_LABEL` de Contas & Saldos (inventar sinônimo
  recriaria a colisão D-6/UX-001 numa terceira tela) e com teste provando que `"no banco"` — o
  rótulo da Projeção — não aparece aqui. `None` sem conta cadastrada, **não zero**. Basta UMA
  conta sem saldo de abertura declarado para a procedência cair para `indisponivel`: um total não
  é mais confiável que a sua parcela mais frágil.
  - ⚠️ **`net_revenue_cents` NÃO ganhou `_origem`**, contra a leitura literal do §6.5: §1.3c é
    sobre campo de **saldo**, e faturamento não é saldo. Aplicar a regra fora do alvo a
    transformaria em ritual.
  - ⚠️ **Quem pegou o card foi um gate escrito ANTES dele existir, e a lição é sobre como
    atualizá-lo.** `test_projection_saldo_misto::test_cockpit_e_carteira_intactos` congelava o
    **dict inteiro** de `finance_summary`, com a docstring dizendo *"o card 'Em conta' é Onda 6 e
    está fora daqui"*. A onda chegou, `saldo_em_conta_cents` passou a mudar **de propósito**, e o
    teste reprovou a funcionalidade **correta**. A correção óbvia — apagá-lo — levaria junto a
    invariante real (o plano 1 não ser contaminado pelo plano 3). Ele foi **reescrito campo a
    campo**: faturamento e custos imóveis, `saldo_em_conta_cents` **obrigado a mudar** (controle
    positivo — senão passaria verde com o card devolvendo `None` para sempre). **Regra que fica:
    um teste que congela um agregado inteiro reprova o dia em que o agregado ganha um membro
    legítimo; congele os campos cujo valor é a invariante, e dê controle positivo ao que deve
    mudar.**
- [x] **O aceite em ~360px FOI MEDIDO, com screenshot** (`onda-3-payout-360px.png`,
  `onda-3-payout-360px-recusa.png`), por Vite + `page.route` + `boundingBox`, sem backend.
  Carteira: viewport 345, `scrollWidth` **350**; Cockpit: 345 / **345** (zero estouro). **Nenhum
  valor cortado**, inclusive `R$ 12.345,00` na lista de saques. Os únicos elementos que cruzam a
  borda na Carteira são o `button` do menu do usuário e seu `svg` — o `ChevronDown` do `AppShell`,
  o defeito **pré-existente** já registrado na 2b-ii. Conta ausente vira "Conta removida", não
  `undefined`.

- **Dívida:** o estouro horizontal do `AppShell` (`app/AppShell.tsx:209`) segue aberto e vale para
  **todas** as telas — deliberadamente fora desta onda, pelo mesmo motivo que a manteve fora da
  2b-ii: misturar correção de defeito existente com regra nova tira do gate a capacidade de julgar
  o que quebrou o quê.
- **Dívida:** não existe **estorno de payout**, então o ramo *"origem desliquidada → apaga"* de
  `sync_origin_movement` é **INALCANÇÁVEL** para `source='payout'` — declarado na allowlist, como a
  2b-i declarou para o `yield`, em vez de fingir cobertura. Se um dia existir, ele reativa o ramo e
  precisa responder o que acontece com as `Transaction` que voltam a `available`.
- **Dívida:** `packages/shared-types/src/generated.ts` segue defasado desde o PR #45 e sem check de
  drift no CI — `FinanceSummary` foi atualizada **à mão** em `index.ts`. Dívida do épico.
- **Dívida:** a conta principal pode ser de `kind='investment'` (`set_primary` não restringe tipo),
  então um saque pode cair numa aplicação. Estranho, mas não incoerente — e restringir aqui
  inventaria regra que a Story 8.7 não tem. Se virar problema, a guarda mora em `set_primary`.
- ⚠️ **O gate ainda NÃO pode ser lido, e agora o motivo é outro.** Com P1–P4 fechados, a obstrução
  deixou de ser de código e passou a ser de **dado**: a produção foi zerada em 05/08 e o gate
  precisa de um ciclo de uso real (conta cadastrada, contas pagas com conta informada, saldo
  declarado). **Um número medido sobre base vazia não é gate** — foi esse erro que quase liberou a
  Onda 4 em julho. ~~O próximo passo natural **não é a Onda 4**: é instrumentar o ciclo mínimo.~~
  **O instrumento existe desde 2026-08-11** — ver a seção do ciclo, logo abaixo. O próximo passo
  agora é **rodar o ciclo**, não construir mais nada.

### O ciclo da conferência — o instrumento que torna `|divergencia_cents|` legível (2026-08-11)

> Spec: `docs/superpowers/specs/2026-08-11-ciclo-da-conferencia-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-11-ciclo-da-conferencia.md`

Até aqui o sinal de *"a pré-condição está satisfeita"* era a **ausência de notas** no relatório de
conferência — zero termo não-zero ⇒ zero nota. Silêncio, e silêncio é indistinguível de *"não
medi"*. É a mesma forma do erro de 2026-07-30, uma camada acima: o critério de decisão é o único
artefato cujo consumidor é um humano num ciclo futuro, e humano não levanta `TypeError`.

**Um ciclo é um mês de calendário no fuso do tenant**, e não uma janela livre — embora
`reconciliation_report` aceite qualquer `start`/`end`. Fronteira escolhível permitiria selecionar a
janela que produz o número desejado: a régua andando junto com o que ela mede, que é exatamente o
que a banda fixa da Regra 7 existe para impedir.

- [x] **O número nunca mais aparece sem o volume que o produziu.** `movimentos_no_periodo` e
  `valor_movimentado_cents` **por conta** (`_volume_counts`, query em lote, com o **mesmo** recorte
  `status <> 'ignored'` do saldo derivado — contar aqui um movimento que o saldo não viu diria que
  houve movimento onde não houve). `func.abs` porque volume é **movimentação**, não resultado:
  R$ 5.000 entrando e R$ 5.000 saindo é um mês movimentado, e a soma assinada diria zero.
  - **A armadilha desta frente é a VACUIDADE da janela, irmã simétrica do erro de julho.** Lá o
    número media a incompletude do sistema; aqui, um mês em que o dono não pagou nada tem P1–P4
    zerados, todas as contas avaliadas e divergência R$ 0,00. O sistema **não distingue** *conta
    dormente* de *tudo aconteceu e nada foi registrado* (§4 da Onda 2), e o volume não faz essa
    distinção tampouco — ele **impede que o número seja lido sem ela**, que é coisa diferente.
  - **Volume mínimo como predicado foi REJEITADO:** N seria número inventado (Artigo IV), e recusar
    a janela **esconde** o número dela em vez de qualificá-lo — o inverso do princípio da Onda 0.
    O ciclo dormente sai legível, com denominador zero à vista, e o zero se lê sozinho.
- [x] **As quatro condições da legibilidade**, cada uma com membro e não-membro escritos
  (`CicloDaConferencia`): **(a)** há conta ativa · **(b)** toda conta avaliada · **(c)** P1+P2 e P3
  zerados · **(d)** a janela começa em ou depois de `PRIMEIRO_CICLO_MEDIVEL`.
  - ⚠️ **(a) não é redundante com (b).** Sem conta, `contas == []`, `contas_sem_checkpoint == 0` e os
    contadores dão zero: (b) e (c) passariam **por vacuidade**. Mesma família do 🟢 sobre razão
    vazio que a Story 8.20 desfez.
  - **`motivo_nao_legivel` é UMA frase**, na precedência `(d) → (a) → (b) → (c)`, por
    **acionabilidade**: mandar o dono declarar o saldo de um mês anterior ao corte é mandá-lo a um
    ato que não resolve aquele mês. Enumerar motivos reconstruiria o ruído que a Regra 7 evita.
- [x] **`PRIMEIRO_CICLO_MEDIVEL` (`2026-09-01`) — o corte de P4, e a frase que o justificava estava
  VENCIDA.** `ConferenciaReport` e `main.py` diziam que a população de P4 é vazia *"porque o payout
  só marca a solicitação como sacada"*: isso descrevia o `request_payout` de **antes da Onda 3** e
  ficou falso no merge dela — a classe §1 da Onda 2 (o documento que afirma sobre a camada de baixo
  e desliga quem viria conferir). A população continua vazia, por **construção nova** (409 sem conta
  principal + a perna bancária na mesma transação), e **só a partir do deploy**. Numa janela
  anterior existem saques sem perna que ninguém conta, e o relatório os reporta como zero **por
  omissão**.
  - ⚠️ **É o único valor do módulo que depende de um fato FORA do repositório, e erra em silêncio
    para o lado caro.** Mesma forma de `CORTE_AUTORIA`: data cravada, motivo ao lado, e um teste de
    piso contra a data do **merge** (2026-08-10), que é um fato do repo — o deploy não é. **Ao mover
    a data, mova o piso junto.** Item no `docs/HOSTINGER-DEPLOY.md`.
- [x] **`GET /bank/reconciliation-cycles` — derivado na leitura, sem migration e sem escrita.**
  Roda o relatório uma vez por mês, teto de 6 (**exibição**, não regra: o PRD marca os "3 ciclos"
  como `[SUPOSIÇÃO DO @PM]`, e codificá-los seria inventar). Persistir foi rejeitado por motivo
  concreto: um lançamento retroativo muda **legitimamente** a leitura de um ciclo passado, e um
  valor congelado passaria a discordar do recalculado — segunda verdade sobre a mesma divergência.
- [x] **ANOTA, NUNCA SUBTRAI, mecanizado.** `test_volume_nao_altera_a_divergencia` congela campo a
  campo o que não pode mudar e dá **controle positivo** ao volume — a lição do
  `test_cockpit_e_carteira_intactos` da Onda 3, onde congelar o agregado inteiro reprovou a
  funcionalidade correta e apagá-lo teria levado junto a invariante.
- [x] **A tela: `CicloCard` ACIMA das frases por conta, histórico abaixo da tabela.** Acima porque
  `fraseConferencia` é **por conta** e o `PeriodPicker` é de intervalo livre — embaixo, a
  qualificação pareceria falar daquelas frases, que são de outro período. **Nenhum substantivo novo
  na tela:** "legível" é termo de domínio e não aparece para o dono; `completo` colidiria com a
  *completude* do Diagnóstico e `comparável` já está tomado no nível da conta pela 8.20. A tela não
  diz "gate", "Onda 4" nem conta até três — **a decisão continua sendo do dono, com os ciclos lado
  a lado.**
  - Histórico é `<ul>`, nunca `<table>` (lição da 2b-ii), e o gate é **escopado** por `within(...)`:
    a página tem um `<table>` legítimo, e a asserção sobre a página inteira falharia no caminho
    normal — "consertá-la" apagando a linha mataria a guarda. Tem controle positivo próprio.
- [x] **O Vima cutuca: `financeiro.conferencia.saldo_do_mes`, SEM limiar novo.** Um limiar exigiria
  a 8ª pergunta de Calibração (`test_todo_limiar_tem_pergunta`) e ela seria um número sem evidência
  (Artigo IV). Não precisa: a **declaração retroativa existe**, então avisar depois do fechamento
  não perde nada. `dias` desde o fechamento ⇒ a cadência `0 → 1 → 2 → 4 → 8 → 16` sai de graça do
  `_proximo_marco`.
  - ⚠️ **O mês entra no `subject_id`** (`{account_id}:{YYYY-MM}`): com o id da conta sozinho, o marco
    do mês anterior sobreviveria à virada, `dias` voltaria a zero e `_calada` engoliria o aviso do
    mês novo — o silêncio permanente que a correção de 2026-08-09 desfez no eixo do dinheiro.
  - Existe porque **quando tudo está verde o dono não abre a Conferência** — e é aí que o contador
    de ciclos importa. Superfície alcançada só por alerta fica invisível justamente no sucesso.

**Duas coisas que só apareceram implementando, e as duas foram achadas por testes:**

- **`list_accounts` traz as ativas de HOJE, e o relatório confere todas** — inclusive a conta aberta
  DEPOIS do fim da janela. Sem recorte, cadastrar uma conta nova tornaria **retroativamente
  ilegíveis** todos os meses anteriores ao cadastro dela, e a tela cobraria de uma conta o saldo de
  um mês em que ela não era do dono. O recorte por `opening_date` mora no **ciclo**, não no
  relatório: aquele comportamento é pré-existente, e consertá-lo junto tiraria do gate a capacidade
  de julgar o que quebrou o quê.
- **Escolher o card do ciclo por `ciclos[0]` duplicava a frase na tela.** Funcionava hoje (o
  primeiro é sempre o mês corrente) e duplicaria no dia em que a ordem mudasse. Passou a ser por
  **semântica** (`ciclos.find(c => !c.fechado)`): o card mostra o em curso, o histórico os fechados,
  e os dois conjuntos são disjuntos por construção.

- [x] **O aceite em ~360px virou TESTE, não screenshot** — `apps/web/e2e/conferencia-ciclo-360.spec.ts`,
  6 asserções na régua que o PR #105 acabou de trazer para o repositório. A medição ad-hoc desta
  frente (Vite + `page.route` + `boundingBox`, num script de scratchpad) foi **descartada assim que
  a régua chegou**: ela já era uma cópia pior — comparava só com a viewport, enquanto
  `textoForaDaTela` acha o **ancestral que recorta**, que é o que pega o `R$ 3.` no lugar de
  `R$ 3.000,00` da 2b-ii. Medido: `document.scrollWidth` **360**, nenhum texto do ciclo dependendo
  de rolagem lateral, `R$ 18.402,00` e `R$ 23.100,00` inteiros, e o denominador zero por extenso.
  O que rola de lado vive **dentro** da `TabelaContas`, pré-existente e no próprio contêiner.
  - **Regra que fica:** quando um ativo do repositório aparece fazendo o que você fez à mão, a
    resposta é **trocar**, não manter as duas — a segunda cópia é a que ninguém atualiza. Aqui a
    troca ainda pagou juros: as asserções passaram a rodar no CI (job `frontend`, também do #105),
    e a medição ad-hoc não rodaria nunca mais.
- **Dívida:** `PRIMEIRO_CICLO_MEDIVEL` depende da data do deploy da Onda 3, que não é fato do
  repositório. O teste de piso elimina a classe barata (cravar no passado), não o erro.
- **Dívida:** conta **arquivada** some do histórico (`list_accounts` a esconde), então arquivar uma
  conta hoje muda a leitura de um mês passado. Preço aceito de não congelar um número que pode
  legitimamente mudar.
- **Dívida:** `packages/shared-types/src/generated.ts` segue defasado e sem check de drift — os dois
  schemas novos entram nessa mesma dívida do épico.
- **Fora de escopo, declarado:** SIG-001, o estouro de 15px do `AppShell`, o índice irmão de
  `charges.bank_account_id`, a unicidade de `bank_accounts.name`, e **contar P4 de verdade** (o
  corte (d) compra a honestidade sem cruzar a Regra dos Planos). E esta frente **não mede a
  divergência nem decide a Onda 4**: ela constrói o instrumento e para.

**O que a Onda 4 já tem escrito, e por que ele aponta para cá.** A spec de design da importação de
OFX existe desde 2026-08-11 (PR #107) e foi escrita **sob gate fechado, de propósito** — decisões
tomadas, riscos nomeados, custo estimado, e o que a faria não valer a pena. Ela **não autoriza nada**.
Ver `docs/superpowers/specs/2026-08-11-onda-4-import-ofx-design.md`, e comece pela **§1**.

- ⚠️ **A §1.2 daquela spec nasceu incompleta, e esta frente é quem provou isso** — as duas foram
  escritas no mesmo dia, sem uma ver a outra. Ela dizia que a leitura vale quando **P1–P4 = ∅**:
  necessário, **não suficiente**. Faltavam **(a)** e **(b)**, e sem **(a)** as outras passariam **por
  vacuidade** num tenant sem conta; e tratar **P4 como predicado de janela** manda conferir um mês
  anterior ao deploy da Onda 3, onde saques sem perna são reportados como zero **por omissão** — o
  erro assinatura do épico, cometido dentro da seção que existe para não cometê-lo. Corrigido na
  **§1.2.1** daquela spec, que aponta para cá em vez de repetir a regra.
- **A regra que fica:** **quando existir código que decide a mesma coisa que um documento, o documento
  aponta para o código e para de repetir a regra.** `legivel` é a verdade; a prosa é genealogia. Foi
  o §1 da spec da Onda 4 que se descreveu como *"o único artefato cujo consumidor é um humano"* —
  ganhou um consumidor mecânico em horas, e ele discordou em três pontos.

## WhatsApp Evolution: em produção de verdade (deploy 2026-08-04)

O transporte Evolution (Onda 0-3, ver `[[e1p-whatsapp-evolution-merged]]` na memória / PR #62)
foi **implantado e validado ponta-a-ponta em produção** nesta sessão: Evolution+Redis subiram na
VPS, um tenant real escaneou o QR, conectou de verdade, recebeu mensagem de texto E mídia de um
contato real, e respondeu — via UI, não via teste automatizado. **Cada etapa achou um bug real que
nenhum teste local pegava**, porque cada um dependia de infraestrutura viva (rede da VPS, a
Evolution real, o schema real da resposta dela) que o CI/testes locais não têm como exercitar.
Lição geral que se repetiu 6 vezes: **nunca confie no formato de request/response de uma API de
terceiro por suposição — teste ao vivo ou leia o código-fonte real dela** (`evolution-foundation/
evolution-api` no GitHub; ver padrão de investigação com `gh api`/`WebFetch` nos PRs abaixo).

**Bugs achados e corrigidos, nesta ordem** (cada um só apareceu depois que o anterior foi resolvido
e uma tentativa real de conexão avançou mais um passo):
1. **PR #63** — `mem_limit` da Evolution reduzido de 1g→512m só no `docker-compose.traefik.yml` (VPS compartilhada com pouca memória livre); `docker-compose.prod.yml` (VPS dedicada) ficou em 1g.
2. **PR #64** — imagem `atendai/evolution-api` não existe mais; o registro real é `evoapicloud/evolution-api`.
3. **PR #65** — `REDIS_URI` não é a env var certa; é `CACHE_REDIS_ENABLED`+`CACHE_REDIS_URI` (+`CACHE_LOCAL_ENABLED=false`). Sem isso, cache cai pra filesystem em silêncio + loop de erro nos logs.
4. **PR #66** — `evolution` só estava na rede `db_internal` (`internal: true`, sem saída pra internet — isola Postgres/Redis de propósito). O Baileys precisa alcançar a internet de verdade (servidores do WhatsApp); sem isso, DNS externo falhava dentro do container e a conexão entrava num loop silencioso de reinício, nunca completando o handshake do QR. Fix: `evolution` entra também na rede `edge` (mesmo mecanismo que já dá saída ao `api`), sem label de Traefik — continua inalcançável de fora.
5. **PR #67** — `/instance/fetchInstances` da v2.3.7 devolve os campos direto no item (`name`/`connectionStatus`), não aninhado (`instance.instanceName`/`instance.status`, formato de uma versão mais antiga que nosso código assumia). `get_status()`/`confirm()` sempre viam "desconectado" mesmo já conectado.
6. **PR #68** — `POST /webhook/set/{instance}` espera o corpo **aninhado** sob `"webhook"` (`{webhook: {enabled, url, byEvents, events, base64}}`), não solto. Sem isso, nenhum webhook era configurado — mensagens recebidas nunca chegavam na plataforma.
7. **PR #69** — mídia recebida (imagem/áudio/documento/vídeo) nunca tinha sido implementada, só texto. Payload real capturado ao vivo confirmou `imageMessage`/`audioMessage`/`documentMessage`/`documentWithCaptionMessage` (este último embrulha um nível a mais) e o mecanismo: com `webhook.base64=true`, a Evolution baixa e decifra a mídia (ela tem a `mediaKey`) e injeta em `message.base64` — evita reimplementar a criptografia de mídia do WhatsApp na mão. `ingest_webhook_payload` agora cria o `Attachment` **sincronamente** pra mídia da Evolution (ela não tem endpoint de resolução separado como a Meta — o worker assíncrono existente é Meta-only).
8. **PR #70** — despachante (`core/whatsapp/__init__.py`) nunca tinha sido de fato adaptado pra Evolution em `send_text`/`send_media`/`upload_media`: sempre chamava com `token=`/`phone_id=` (parâmetros da Meta), que a Evolution não aceita (`instance=`, credencial global). `TypeError` ao tentar responder qualquer conversa real — só apareceu porque foi a PRIMEIRA resposta de verdade enviada por um tenant Evolution.
9. **PR #72** — UX: miniatura de imagem inline (busca o blob autenticado, `<img src={objectURL}>`) em vez de só um link "Ver imagem".
10. **A conversa não tinha autor nem relógio** (achado usando a tela com conversas reais). `ingest_webhook_payload` fixava `direction=DIRECTION_IN` para TODA mensagem do webhook, e `evolution.parse_inbound` nem lia `key.fromMe` — mas o Baileys espelha no MESMO evento `messages.upsert` o que o contato mandou **e** o que o dono digitou no WhatsApp do celular dele. Resultado: as duas pontas da conversa entravam como recebidas, e a tela pintava tudo cinza-à-esquerda. Fix: `InboundMessage.from_me` (default `False` — a Meta nunca entrega mensagem própria em `messages`, só status em `statuses`) → `direction="out"` no ingest. **Três efeitos colaterais que vinham junto e foram corrigidos no mesmo passo:** (a) `is_within_session_window` conta só `DIRECTION_IN`, então mensagem NOSSA reabria a janela de 24h e liberava resposta livre onde a Meta exigiria template; (b) `unread` na lista marcava como não-lida a conversa em que quem falou por último fomos nós; (c) `pushName` de mensagem espelhada é o do **próprio dono** — batizava o cliente novo com o nome do dono (agora só nomeia quando o contato escreveu, senão cai no telefone). A trilha de auditoria ganhou ação própria (`...message.mirrored`): registrar "received" numa mensagem que o dono escreveu é trilha que mente. UI: cabeçalho com nome/telefone do contato, separador de dia (Hoje/Ontem/`dom., 19/07/2026`), horário em toda bolha e a marca **"Você ·"** nas nossas — autoria em TEXTO, não só por cor e lado.
    - ⚠️ **As mensagens já gravadas antes deste fix continuam erradas** (todas `in`) e **não têm conserto retroativo**: `fromMe` nunca foi persistido, e nada no que está no banco distingue as duas pontas. Só vale daqui pra frente.

11. **Grupo não tinha onde existir** (achado no mesmo ciclo de uso real, logo após o item 10). Sintoma: *"mensagem de grupo não aparece o texto/imagem da conversa e nem o nome do grupo"*, e **todo grupo aparecia como "Não identificados"**. Eram três defeitos empilhados, e o terceiro é o estrutural: (a) `parse_inbound` só reconhecia `@s.whatsapp.net`, então todo `@g.us` virava `from_phone=None`; (b) sem telefone não havia `client_id` — e `client_id` era a ÚNICA identidade de conversa que existia, então TODOS os grupos colapsavam num balde só; (c) esse balde tinha `client_id: null` e a tela usava esse nulo como chave de rota, então clicar nele não abria nada (o painel voltava para "Selecione uma conversa"). **A causa raiz é que a caixa de entrada era indexada por cliente do CRM**, e grupo não é cliente.
    - **Decisão do fundador:** grupo aparece em Conversas e **NÃO vira contato do CRM** (senão o funil de vendas e o painel de inadimplência enchem de grupo), **mas é respondível** — não é só leitura.
    - Fix: **`whatsapp_chats`** (migration 0066) — a conversa como entidade própria, chaveada por `chat_jid` (o `key.remoteJid`, que é também o endereço de volta no envio). `client_id` desce de chave para **enriquecimento opcional** da conversa direta. `whatsapp_messages` ganha `chat_id` + `sender_phone`/`sender_name` (em grupo, sem o autor por mensagem o fio vira um muro de balões anônimos). O estado de leitura migra para `whatsapp_chats.last_read_at` — e isso **dissolveu por construção** a corrida de `IntegrityError` que `mark_read` precisava tratar: não há mais INSERT, só UPDATE de uma linha que já existe.
    - **Dois achados do payload real** (capturado ao vivo, v2.3.7 — o assunto do grupo NÃO vem na mensagem, só o JID; é buscado à parte em `/group/findGroupInfos` e cacheado em `title`, com `title_checked_at` limitando a 1 tentativa/6h para não consultar a rede a cada mensagem): **`key.participantAlt`** traz o telefone real de quem falou no grupo mesmo com `participant` mascarado como `@lid`; e **`key.remoteJidAlt`** traz o telefone real em conversa DIRETA que chegou como `@lid` — eram 60 mensagens em 12h caindo em "Não identificados" por não lermos esse campo. `chat_jid` é **canônico** (sempre `{telefone}@s.whatsapp.net` quando o telefone é conhecido): sem isso o mesmo contato viraria duas conversas, uma por modo de endereçamento, partindo o histórico no meio.
    - Grupo **ignora a janela de 24h** (é regra da Cloud API da Meta, que nem tem grupos — exigi-la deixaria o grupo mudo por engano, e nem template existiria para destravar) e **recusa template**.
    - `@lid` **nunca** é tratado como telefone (`_phone_from_jid` devolve `None`): parece um número e não é. Sem contato conhecido a conversa existe e abre; o rótulo diz "Contato não identificado" em vez de inventar nome.
    - **Migration validada contra Postgres REAL** (container descartável, rodando como o papel não-superusuário `e1p_app`, com dados legados semeados): backfill preservou as 7 mensagens de teste, 0 ficaram sem conversa, `last_read_at` migrou, RLS `FORCE` restaurada nas 4 tabelas e isolamento cross-tenant fail-closed conferido (sem GUC → 0 linhas). O backfill **desabilita a RLS na sua janela** — sem isso ele seria um no-op silencioso (armadilha da `0046`, que o SQLite dos testes não pega).
    - **Dívida:** `whatsapp_conversation_states` fica órfã (o estado de leitura mudou de casa); não foi dropada porque `DROP TABLE` é irreversível e vale manter um ciclo para conferência — dropar numa migration posterior.

12. **As regras da Meta seguiam valendo sob a Evolution, porque `capabilities.py` não tinha
    consumidor nenhum.** Sintoma reportado: o nó de WhatsApp do funil respondia *"Selecione um
    template de WhatsApp aprovado"* num tenant conectado por QR code — que não tem template
    nenhum e não consegue criar (a Evolution recusa templates por design). **Template aprovado e
    janela de 24h são artefatos da Cloud API da Meta**, e o módulo que já codificava exatamente
    isso (`app/core/whatsapp/capabilities.py`, `EVOLUTION.templates=False`,
    `session_window=False`) existia desde a Onda 0 com **zero call sites em produção** — só o
    próprio teste unitário. Sua docstring **afirmava** que 3 consumidores o consultavam; nenhum
    dos 3 tinha sido escrito.
    - **A lição de método:** um módulo de capacidades sem consumidor não protege ninguém — ele
      documenta uma intenção, e a docstring que descreve consumidores inexistentes *impede* que
      alguém note a lacuna (é a mesma classe de erro da **INSTANCIAÇÃO OBRIGATÓRIA** do Epic 8:
      conjunto definido por descrição, sem membro escrito, sem consumidor mecânico que proteste).
      **Regra que fica: capacidade nova nasce com o consumidor no mesmo passo**, e a lista de
      consumidores na docstring tem que ser verificável por grep.
    - **Três instâncias do mesmo defeito**, todas corrigidas aqui: (a) o nó do funil exigindo
      template (`funnels/service.py::run_node` → agora texto livre sob Evolution, com
      `{{cliente.*}}` resolvido; `engine._params` passou a carregar `config.body` até a ação, sem
      o que a jornada automática continuaria muda); (b) `is_within_session_window` aplicando a
      janela de 24h — **beco sem saída**, porque fora da janela a única saída oferecida é
      template, que ali não existe: a conversa emudeceria 24h após a última mensagem do contato;
      (c) achado durante a implementação — **os 5 pontos do domínio que resolvem vínculo
      propósito→template no ENFILEIRAMENTO** (quotes, contracts, receivables, platform,
      `on_client_moved`) não sabem por qual transporte a mensagem sai, então um tenant que usou a
      Meta e migrou pro QR mantinha os vínculos e cada notificação chamaria `send_template` →
      falha garantida + retry com backoff até expirar. Guarda posta no **ponto de entrega**
      (`process_pending`), onde o transporte é conhecido: cai em `send_text` sem perder conteúdo,
      porque `notification.message` já é o template renderizado.
    - **`_resolve` do despachante agora DERIVA de `capabilities.for_profile`** em vez de repetir
      a comparação `whatsapp_provider == "evolution"`. Se divergissem, um consumidor concluiria
      "posso mandar texto livre" enquanto o despachante entregaria pela Meta — e a falha
      apareceria no worker, longe de quem poderia relacionar as duas decisões. Gate em
      `tests/test_whatsapp_capabilities.py::test_capabilities_e_despachante_nunca_divergem`.
    - Frontend espelha o mesmo dado em `apps/web/src/lib/whatsappCapabilities.ts` (o builder lê
      `GET /settings/profile` uma vez e passa o transporte aos dois modais). Conversas **não
      precisou mudar**: o backend passou a responder `within_session_window: true` e a caixa de
      texto livre que já existia aparece sozinha.
    - **Dívida:** o espelho do TS é mantido à mão (mesma dívida geral de `shared-types`) — se
      surgir um 3º transporte, os dois arquivos precisam mudar juntos, e nada no CI reprova o
      esquecimento.

13. **"Mensagem registrada" e nada chegava: o telefone ia sem código do país.** Achado logo após
    o deploy do item 12 — o funil parou de dar 422, completou a jornada, gravou
    *"Mensagem registrada para Flavio Kato (whatsapp)"* e **nenhuma mensagem chegou**. A
    `Notification` ficou `failed` com `last_error` VAZIO (o provider devolve `"failed"` sem
    levantar, então nada preenchia o campo) e o worker logava só `400 Bad Request`.
    - **Causa:** o contato estava gravado como `43984074017` — o que o dono digitou, sem o `55`.
      A sondagem de `/chat/whatsappNumbers` em produção fechou o caso: `43984074017` →
      `exists:false`; `5543984074017` → `exists:true`. **A forma correta JÁ existia no banco**
      (`clients.phone_key`, calculado por `normalize_br` na PR #76) — o caminho de envio é que
      usava `clients.phone`, o cru.
    - **Por que a resposta no inbox sempre funcionou e isto não:** contato criado pelo webhook
      nasce com o telefone que veio do WhatsApp, já completo. Contato digitado/importado, não.
    - **Fix na FRONTEIRA (`whatsapp.__init__._addressable`), não em cada call site:** são **seis**
      caminhos que resolvem destinatário de campo de telefone cru (funil, alerta pra equipe,
      convite de funcionário, orçamento, cobrança, contrato) e só `Client` tem gêmeo
      normalizado — consertar um por um deixaria quatro quebrados. O despachante é por onde todo
      envio passa (mesma razão de `capabilities` viver lá). O que está GUARDADO não muda:
      `clients.phone` segue sendo a evidência do que a pessoa digitou.
    - **Nem todo `to` é telefone** e reescrever os outros trocaria falha visível por entrega no
      lugar errado: grupo é JID `@g.us`, não identificado é `@lid`, `_owner_recipient` cai em
      e-mail e o funil cai no NOME do contato. Guarda explícita para `@`; o resto sai intacto
      porque `normalize_br` devolve `None` fora do formato BR.
    - ⚠️ **Suposição BR-only, decidida pelo fundador** (coerente com CPF/CNPJ, boleto, Pix): um
      celular estrangeiro de 10-11 dígitos É reescrito como brasileiro e a mensagem iria para
      outra pessoa — pior que falhar. Por isso **toda reescrita é logada em INFO**: o caso
      estrangeiro precisa aparecer. Se um dia houver contato internacional, este é o ponto.
    - **[CORRIGIDO]** `crm.update_client` fazia `setattr` genérico e **não recalculava
      `phone_key`** — editar o telefone de um contato deixava a chave velha. Não afetava o envio
      (a fronteira normaliza), mas quebrava a deduplicação: o efeito não aparece na tela de
      edição e sim no PRÓXIMO lead, como card duplicado. `phone_key` é derivado e não está no
      `ClientUpdate` (nem deve: derivado não é campo de entrada), então o laço genérico nunca o
      alcançava. Apagar o telefone agora apaga a chave junto — chave órfã casaria um lead futuro
      com um contato que já não tem aquele número. **Verificado em produção antes de corrigir:
      55 contatos, 0 com chave divergente** — nenhum backfill necessário. ⚠️ A primeira sondagem
      devolveu `contatos=0` e quase virou um "está tudo limpo" falso: `clients` tem RLS e
      `SessionLocal` sem tenant é fail-closed. **Auditoria de dados em tabela com RLS precisa do
      papel que faz bypass (`e1p_root`), senão a consulta não vê linha nenhuma e o silêncio
      parece aprovação.**
    - **Lacuna de diagnóstico fechada junto:** `providers/evolution.py` chamava
      `raise_for_status()` e logava só o código — o CORPO da resposta da Evolution, que já
      explicava o erro, era descartado. Investigar exigiu sondar a API à mão em produção. Agora
      `send_text`/`send_media` logam a resposta (truncada em 400 chars). **Regra: ao integrar
      terceiro, o corpo do erro dele faz parte do log — o status sozinho não diagnostica nada.**

**⚠️ `migrations/env.py` silenciava o logging de TODA a aplicação** (achado no mesmo ciclo, por um
teste que passava sozinho e falhava na suíte inteira). `fileConfig()` tem
`disable_existing_loggers=True` por PADRÃO: ele marca `disabled=True` em todo logger já
existente e não nomeado no `alembic.ini` — `e1p.whatsapp`, `e1p.notifications`, `e1p.worker`.
Depois disso `logger.info`/`logger.exception` viram no-op silencioso pelo resto do processo.
Produção escapa **por acidente de topologia** (o compose roda `sh -c "alembic upgrade head &&
uvicorn ..."`, processos separados); dentro do pytest, um único teste que aplica migrations
silencia os testes seguintes. Corrigido com `disable_existing_loggers=False`. É a mesma família
do bug já registrado abaixo ("logs que somem" por falta de `basicConfig`) — **quando um log
sumir, verifique também quem chamou `fileConfig`/`dictConfig` antes**, não só handler ausente.

14. **A mensagem saiu, chegou no celular e mesmo assim não apareceu em Conversas.** Achado
    testando a #79 em campo. Duas causas independentes, e a segunda é estrutural:
    - **O webhook só assinava `MESSAGES_UPSERT`**, que é o que CHEGA (mensagem do contato e a
      que o dono digita no próprio celular, espelhada pelo Baileys). O que sai pela API da
      Evolution vem em **`SEND_MESSAGE`** — evento diferente. Sem ele, tudo que o produto dispara
      sozinho (funil, cobrança, contrato) era entregue de verdade e **não ficava registrado na
      conversa**: o fio mostrava só um lado. Nomes conferidos por `grep` no dist da imagem que
      roda em produção, não na documentação. Duplicar não é risco: `ingest_webhook_payload` é
      idempotente por `wa_message_id`.
    - **O contato do funil não era o contato da conversa.** Seis cards "Flavio Kato" com o mesmo
      `phone_key`: o funil inscreveu `8a75cf66` (`source=api`, zero conversas) e a conversa real
      estava em `4804f5c5` (`source=whatsapp`). `get_timeline` ancora os avisos automáticos em
      `chat.client_id` — cards diferentes, metade da história em cada.
    - **`crm/merge.py`** (+ `app.scripts.merge_duplicate_clients`, dry-run por padrão) fecha a
      dívida que a PR #76 deixou aberta. Descobre as tabelas com `client_id` pelo REGISTRY, não
      por lista escrita à mão (mesmo motivo da purga dinâmica de tenant: lista esquece o módulo
      seguinte, e esquecer aqui deixa cobrança apontando para card apagado). Sobrevivente = o
      mais antigo, **o mesmo critério de `_find_existing`** — se divergisse, `absorb_lead`
      escolheria um card e a mescla outro, e o próximo lead recriaria a divisão.
    - ⚠️ **O guarda que impede a mescla errada:** agrupa por telefone **E nome**. `phone_key` não
      é único de propósito (marido e mulher compartilham telefone) — agrupar só por telefone
      juntaria duas PESSOAS num card, que é pior que o duplicado.
    - **O 9º dígito era a segunda forma de o histórico se partir:** o JID real do contato pode
      não ter o 9 (`554384074017@s.whatsapp.net`, conta pré-2016) enquanto tudo que enviamos
      passa por `normalize_br`, que o acrescenta. `_get_or_create_chat` ganhou busca secundária
      por telefone normalizado, só no caminho de miss — mesma classe que o `chat_jid` canônico já
      resolvera para `@lid` × `@s.whatsapp.net`.
    - **UX:** "Descrição" do nó virou "Anotação (só no desenho)". Duas caixas multilinha
      conviviam na mesma tela e só uma era enviada; o fundador escreveu na errada um texto que
      parecia mensagem e esperou que fosse entregue. Nada na tela dizia o contrário.
    - **Operacional:** mudar a config do webhook numa instância JÁ conectada exige reaplicar o
      `/webhook/set` **e reiniciar o container `evolution`** (armadilha já registrada abaixo) —
      o processo em memória mantém a config carregada na conexão.

**Duas armadilhas operacionais da VPS** (não são bug de código, são do processo de deploy):
- Depois de mudar a config do webhook via `/webhook/set` numa instância **já conectada**, a mudança pode não valer pro processo em memória (cache do canal Baileys carregado na conexão) — precisou **reiniciar o container `evolution`** (não só recriar) pra pegar a config nova. Sessões reconectam sozinhas (credenciais persistidas no Postgres/Redis), sem precisar de novo QR.
- `docker compose up -d --build <serviço>` só reconstrói o serviço **nomeado**. Rebuildar só `api` depois de um PR que também mudou frontend deixa o `web` com o build antigo, **em silêncio** (sem erro, só o comportamento antigo persistindo). Depois de qualquer merge, checar QUAIS serviços mudaram no diff antes de escolher o que rebuildar — ou rebuildar todos (`up -d --build` sem nome, como o `reference_e1p_prod_deploy` já recomendava).

**Estado atual:** conectado e funcionando ponta-a-ponta pro tenant `70c1f435-a21e-4148-a8c6-32a7e346a818` (flaviokato76@gmail.com) — QR, texto recebido, mídia recebida (imagem com miniatura inline), resposta de texto enviada, tudo validado com conversas reais em produção.

## CRM: a jornada única do contato (um card por pessoa)

> Spec: `docs/superpowers/specs/2026-08-04-crm-jornada-unica-do-contato-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-04-crm-jornada-unica-do-contato.md`

O mesmo contato virava vários cards no Kanban (quatro "Flavio Kato" na tela do fundador):
`pages/service.py::public_submit` e `integrations/service.py::capture_lead` chamavam
`create_client` incondicionalmente. O WhatsApp já deduplicava — por telefone cru —, então o
comportamento era incoerente por porta de entrada.

- [x] **Porta única `crm_service.absorb_lead`** — as três portas (página pública, API de
  integração, WhatsApp) convergem nela. Identidade: **telefone normalizado primeiro, e-mail em
  segundo**. Quem já existe é COMPLEMENTADO (campos vazios preenchidos, nunca sobrescritos) e
  ganha um `lead_return` com a data e o texto daquele envio. `notes` do dono não é tocado no
  retorno — era exatamente o que apagava o que ele tinha escrito.
- [x] **`core/phone.normalize_br` + `clients.phone_key`** (migration 0067) — `phone` guarda o
  que a pessoa digitou, `phone_key` a forma comparável. **A regra do 9º dígito por faixa da
  Anatel** (local de 8 dígitos começando em 6–9 é celular e ganha o 9; 2–5 é fixo e não ganha)
  é o que impede o fixo `11 3333-4444` de colidir com o celular `11 93333-4444` — a alternativa
  "compara os últimos 8 dígitos" juntaria duas pessoas num card só.
- [x] **`phone_key` NÃO é único, de propósito** — marido e mulher compartilham telefone, e os
  duplicados legados (não mesclados, decisão do fundador) compartilham chave depois do
  backfill. `absorb_lead` desempata pelo **mais antigo** (`created_at ASC, id`); sem isso o
  próximo retorno cairia num card imprevisível e a história se partiria. ⚠️ Quando o
  `created_at` EMPATA (mesma transação no Postgres, mesmo segundo no SQLite) "o mais antigo"
  deixa de ser um fato observável e a garantia entregue é só **estabilidade** — a mesma
  escolha em toda chamada, via `id` como segundo critério. O teste que cobria isso passava por
  sorte até ser corrigido; ver `test_multiplos_candidatos_*` em `tests/test_lead_absorb.py`.
- [x] **Reabertura** — retorno em coluna terminal (`is_won` **ou** `is_lost`) move o card para
  a primeira coluna ativa e grava `reopened`. Coluna do meio **não** se move (puxar de volta
  apagaria trabalho em andamento). Ganho reabre porque lead recorrente querendo comprar de
  novo é oportunidade nova (decisão do fundador).
- [x] **`client_events`** — a linha do tempo NARRATIVA (`lead_created`, `lead_return`,
  `stage_move`, `reopened`, `note`, `funnel`). **Dinheiro não entra aqui:** orçamento, cobrança
  e pagamento continuam sendo lidos de `quotes`/`charges` por `crm/timeline.py`. Copiar
  `amount_cents` criaria uma segunda versão da verdade sobre dinheiro — a forma exata do bug
  que a Onda 0 do Epic 8 desfez. Ler da origem também deu o histórico financeiro
  **retroativo** de graça. `title`/`body` são texto CONGELADO (renomear a coluna do Kanban não
  reescreve o passado), no princípio do `raw_description` de `bank_transactions`.
  - ⚠️ **`client_events` NÃO EXISTE MAIS** (migration 0069, 2026-08-06): foi absorvida por
    `facts` e dropada. Tudo o que este item descreve continua valendo — mudou a tabela, não
    a regra. `crm/timeline.py` lê de `facts`. Ver §Vima abaixo.
- [x] **`ClientEvent.created_at` tem default do lado do PYTHON**, sobrescrevendo o
  `server_default=func.now()` do `TimestampMixin`. No Postgres `now()` é o timestamp da
  TRANSAÇÃO: `lead_return` e `reopened`, gravados no mesmo commit por `absorb_lead`, sairiam
  com instante idêntico e o desempate cairia no uuid — a timeline mostraria "Reaberto" acima
  de "Voltou pelo site", invertendo a causalidade na tela. **Regra que fica: coluna de tempo
  usada para ORDENAR eventos da mesma transação não pode vir de `func.now()`.**
- [x] **Reinscrição no funil** — `crm.client.returned` reinscreve no funil de entrada, com
  guarda de jornada `running`/`waiting` em `automation.py` (não dentro de `engine.enroll`:
  inscrição manual pela tela continua fazendo o que o usuário mandar).
- [x] **Superfícies** — `<ClientTimeline>` na ficha 360° (primeira `<Section>`) e como painel
  direito de Conversas (**gaveta sobreposta abaixo de `lg`**, pela lição do PR #56). Card do
  Kanban mostra "última interação", calculada por **duas consultas agrupadas** no endpoint do
  board — nunca uma coluna `last_interaction_at`, que seria valor derivado guardado.
- [x] **A coluna do Kanban é uma FILA por ordem de entrada na etapa** (`clients.stage_entered_at`,
  migration 0068). Antes ordenava por `Client.name`, e como a maioria dos leads entra pelo
  WhatsApp sem nome resolvido o "nome" é o telefone — a Entrada aparecia em ordem numérica de
  DDI. Agora o mais antigo fica no topo e quem entra vai para o fim, para o dono atender por
  ordem de chegada. **É coluna e não derivação de `client_events`** (ao contrário de
  `last_interaction_at`, logo acima) porque o log não registra troca de etapa de forma
  completa: `move_client` grava `stage_move`, a reabertura do `absorb_lead` grava `reopened`,
  e **`archive_stage` remaneja em massa sem evento nenhum** — não é derivado materializado, é
  fato primário que não tinha onde morar. O preço da coluna é o gate AST
  (`tests/test_crm_stage_order_gate.py`): um quarto caminho de escrita que esquecesse o
  carimbo não quebraria teste nenhum, a fila só passaria a mentir. **`archive_stage` preserva
  a antiguidade de propósito** (allowlist do gate): arquivar é ato administrativo do dono, e
  recarimbar jogaria a coluna inteira, em bloco, para o fim da fila de destino.
  - ⚠️ **Backfill precisa abrir a RLS de toda tabela que a consulta toca, não só do alvo.** A
    primeira versão da 0068 desabilitava a RLS só de `clients` (alvo do `UPDATE`) e deixava
    `client_events` (fonte da subconsulta) protegida. A RLS filtra **SELECT** também: a
    subconsulta devolvia `NULL` para todos, o `COALESCE` caía no `created_at` e o backfill
    **completava com sucesso aparente**, tendo perdido justamente a informação de
    movimentação que existe para recuperar. É pior que a armadilha conhecida do "zero linhas
    afetadas" (`0046`/`0066`/`0067`), porque a contagem de linhas fica **certa** e só o valor
    é que está errado — nada na saída do deploy denuncia. Achado por
    `tests/test_migration_0068_stage_order_rls.py` no primeiro uso, e provado por mutação.
- **Grupo de WhatsApp não tem histórico de CRM** — `client_id` é nulo e o painel diz isso em
  texto, mantendo a decisão de 2026-08-04 de que grupo não vira contato.

**Armadilha de JS que custou uma depuração e vale para qualquer setter de estado:** o
`ClientTimeline` derrubava a **página inteira** de Conversas quando o endpoint respondia fora
do formato. A causa não era `undefined`: com `data = []`, `data.entries` é
`Array.prototype.entries` — uma **função** —, então `data?.entries ?? []` deixava passar, e um
setter do React que recebe função a trata como updater e a **executa**. O guard correto é
`Array.isArray`. Componente de painel lateral também nunca deve poder derrubar quem o hospeda:
`load` degrada para aviso em vez de estourar.

**Dívida:** os cards duplicados que já existiam **não foram mesclados** (decisão do fundador:
a correção vale daqui para frente) — quem for mesclá-los depois precisa juntar `facts`
(ex-`client_events`), `charges`, `quotes`, `contracts` e `whatsapp_chats` do card absorvido, e não só apagar a linha.
Não há ferramenta de mescla na tela. Também não há "ligar conversa não identificada a um
contato" nem marcação de histórico como lido.

- [x] **360px: a Conversa é uma TELA, não uma coluna** (2026-08-10). Abaixo de `lg` a lista e a
  conversa não dividem a largura — mostra-se uma por vez, com "Voltar para as conversas" no
  cabeçalho da conversa. `w-80 shrink-0` + `flex-1` **sem breakpoint** faziam o painel da conversa
  nascer em **x=360**, inteiro fora da viewport de 360px, e `main` (`overflow-x-hidden`) o cortava
  sem deixar barra nem pan por toque: **o dono tocava numa conversa e nada acontecia** — 12
  elementos fora da tela, incluindo toda mensagem e o campo de envio. Era o "corte" que o PR #58
  proibiu, aplicado à jornada inteira do contato. A gaveta do histórico já tratava o celular assim
  desde sempre; a divisão principal é que nunca foi tratada. Travado por
  `apps/web/e2e/conversas-360.spec.ts` (mede `toBeInViewport` e `boundingBox`, não classe CSS).
  **Fecha a dívida "validação manual em ~360px do painel de Conversas".**

### O card diz de onde o contato veio (2026-08-15)

O fundador olhou a Entrada e perguntou por que uma conversa avulsa de WhatsApp vira lead. A
investigação achou um defeito **anterior** a essa pergunta: os cards do site exibiam
`vindo-do-site` e os do WhatsApp não exibiam nada, então a coluna parecia ter duas naturezas de
contato quando na verdade tinha uma etiqueta a mais em alguns.

- ⚠️ **`vindo-do-site` é TAG, não origem** — não é escrita por nenhum caminho de produção (só
  aparece em `test_crm_merge.py` e na spec da jornada única). Chegou ali à mão ou por uma ação
  `add_tag` de funil. **A regra que fica: `source` é a origem, fato do sistema; `tags` é marcação
  do dono. As duas nunca se parecem na tela** — selo cinza × pílula roxa —, porque foi confundir
  uma com a outra que produziu a pergunta.
- [x] **Zero backend, zero migration, e vale retroativamente.** `BoardClient` herda de `ClientOut`,
  então `source` **já chegava** no board; [`CrmPage.tsx`] apenas renderizava `client.tags` e o
  ignorava. Como `source` tem default `"manual"` e nunca é nulo, **todo card ganhou origem de uma
  vez**, inclusive os que já estavam na tela.
- [x] **`features/crm/origem.ts` cobre os SEIS de `SOURCE_VALUES`, não os cinco de
  `_ROTULO_DE_CHEGADA`** — o mapa do backend esquece o `ai`, que a validação aceita. Origem que o
  backend grava e a tela não sabe nomear apareceria crua no card.
  - ⚠️ **Ele NÃO é espelho do mapa do backend, e não deve virar um.** Lá a string é FRASE de linha
    do tempo ("Chegou pelo WhatsApp"); aqui é SELO que divide largura com o nome e as tags em
    360px. Superfícies diferentes, vocabulários diferentes — copiar a frase longa para o card
    seria a duplicação ruim, não esta. O eixo a manter sincronizado é `SOURCE_VALUES`.
  - Origem desconhecida cai no **próprio valor**, com teste do não-membro: sem ele o mapa passaria
    vazio, e um backend mais novo que a tela devolveria o card a não ter origem nenhuma — o
    defeito que este arquivo existe para corrigir, de volta pela porta dos fundos.
- [x] **`textoForaDaTela` ganhou `raiz`** (`e2e/support/medidas.ts`), no mesmo padrão que
  `alvosPequenos` já tinha. **O Kanban rola de lado por construção**: a página mede 360 (não é ela
  que rola), mas as colunas seguintes ficam fora da viewport e apareciam como três cortes —
  "Em contato", o contador dela e "Solte um card aqui" —, nenhum deles texto de card. Sem o
  recorte, esses três afogariam qualquer corte real. Escopo que deixa de casar cai no documento
  inteiro, **nunca em lista vazia**, e `crm-360.spec.ts` tem controle positivo com seletor podre
  provando que o `[]` escopado é resultado e não vacuidade.
- [x] **A distinção visual é medida por COR COMPUTADA, nunca por classe** (`crm-360.spec.ts`).
  `toContain("bg-neutral-100")` ficaria verde com o Tailwind desligado, com a classe purgada do
  build ou com um `bg-primary-50` vencendo na cascata — e os dois selos idênticos na tela, que é o
  defeito de origem. O teste de jsdom afirma só o que jsdom sabe (elementos distintos, origem
  antes das tags) e **diz no próprio comentário** que a cor é aferida no navegador.
  - ⚠️ **E a asserção é ABSOLUTA, porque a relativa não bastava — provado por mutação.** A primeira
    versão comparava `expect(origem).not.toBe(tag)`, e o `bug-hunter` do §5 aplicou a mutação que
    **TROCA as duas cores**: a diferença se preserva, o significado se inverte, e **os 16 testes
    ficaram verdes** — com o comentário do `CrmPage` afirmando o oposto do que a tela mostrava.
    Hoje o que se afirma é o **matiz**: origem acromática (croma ≤ 8), tag colorida (≥ 12). Os dois
    limiares são **medidos** (`neutral-100` = 3, `primary-50` = 18), não escolhidos, e a mutação
    agora morre (`Expected >= 12, Received 3`).
    > **A regra que fica: comparação relativa entre dois papéis não prova papel nenhum.**
    > `a !== b` sobrevive a trocar `a` com `b` — e trocar os dois é exatamente a forma que o
    > defeito assume quando alguém "arruma as cores" sem ler o comentário. Se o teste existe para
    > dizer QUAL é qual, ele tem de afirmar cada um por si.
- [x] **`rotuloDaOrigem` usa `Object.hasOwn`, e o `?? source` ingênuo era bug** (achado do
  `bug-hunter`). Indexar objeto literal alcança `Object.prototype`: `rotuloDaOrigem("constructor")`
  devolvia a **função `Object`** — que o `??` não pega, porque função não é nula. A assinatura
  `: string` mentia, e o React renderizava o selo **VAZIO** (com "Functions are not valid as a
  React child" no console): card sem origem, o defeito que este módulo existe para corrigir.
  Inalcançável hoje (`ClientBase._source` recusa fora de `SOURCE_VALUES`; a coluna é `NOT NULL`
  desde a 0003) e travado assim mesmo, com os cinco herdados em `it.each` — o custo é uma linha, e
  o dia em que um caminho de escrita novo contornar o schema não vem anunciado.
- **Dívida — e é a pergunta que abriu tudo:** a conversa avulsa **continua nascendo na Entrada**,
  continua sem poder ser descartada (não existe `DELETE /crm/clients`, só mover para "Perda", que
  grava negociação perdida sobre algo que nunca foi negociação), e `_cards_parados` vai cobrá-la
  no briefing em 10 dias. Separar "o contato existe" de "está no funil" foi **adiado por decisão
  do fundador**: primeiro ver a composição real da Entrada com a origem à vista. Quem retomar
  começa por [`whatsapp_inbox/service.py`] (a porta que cria) e por `crm/service.py:229` (o
  `stages[0]` que enfileira).
- **Dívida (levantada pelo `dedup-checker` e pelo `regression-tester`, nenhuma introduzida aqui):**
  `SOURCE_VALUES` é mantido por **três listas manuais sem vínculo mecânico** — o `set` Python, as
  chaves de `_ROTULO_DE_CHEGADA` e as de `origem.ts`. Um sétimo `source` no backend faz o card
  exibir o valor cru **em silêncio**; um `export type ClientSource` em `shared-types` trocaria isso
  por erro de TypeScript. E o padrão `rounded-pill` inline já passou de **7 ocorrências**
  (`Attachments.tsx:79` é quase idêntico ao selo novo) sem nunca virar um `<Pill>` — este diff
  seguiu a convenção local, não a piorou.
  ⚠️ **"7 ocorrências" ficou defasado: são 190**, em ~50 arquivos de `apps/web/src` (contado em
  2026-08-18). O número importa porque é ele que decide a dívida: "7" se lê como *ainda não vale um
  componente*, e **190** se lê como *isto é o design system, e ele não foi declarado*. Enquanto o
  número estiver errado, a dívida vai ser adiada com razão aparente.
  **Acessibilidade:** a distinção origem × tag é por cor e posição; o texto difere e o selo tem
  `title`, então não é codificação puramente cromática, mas não há forma nem ícone separando os
  dois.

### Marcar compromisso: a agenda vem antes do formulário (2026-08-18)

O botão "Marcar com este cliente" da ficha 360° abria o `NewEventModal` com `initialDate={null}`:
o dono escolhia data e hora **sem ver o próprio calendário** e só descobria a colisão depois de
salvar, pelo aviso de conflito. Agora o passo 1 é a disponibilidade; o formulário só aparece com
data e hora já decididas. **Zero backend, zero migration** — reusa `GET /agenda/events`.

- [x] **`features/agenda/grade.ts`** — a aritmética de calendário saiu de dentro do `AgendaPage.tsx`
  (`startOfDay`, `addDays`, `startOfWeek`, `sameDay`, `hojeDoTenant`, `eventYmd`, `eventsOfDay`,
  `gradeDoMes`) e virou módulo compartilhado. Refactor puro, sem mudança de comportamento: os dois
  calendários passam a nascer da MESMA matemática, e é assim que um deles não começa a semana num
  dia diferente do outro.
- [x] **`faixasLivres(eventos, dia, fuso, agora)`** — blocos de 1h entre `HORA_ABERTURA` (8) e
  `HORA_FECHAMENTO` (18). **A janela é FIXA de propósito:** não existe expediente configurável no
  backend, e inventar um (migration + endpoint + tela) para oferecer atalhos de horário seria
  construir um épico para resolver um clique. O botão "Outro horário" é a válvula de escape.
  - ⚠️ **`all_day` NÃO ocupa faixa.** Cobrança, conta a pagar e prazo são **todos** de dia inteiro;
    se ocupassem, todo dia com uma parcela vencendo apareceria cheio — o oposto do que o seletor
    existe para mostrar. Elas aparecem só na lista "já marcado" do dia. Tem teste; não "corrija".
  - Cancelado não ocupa (mesma postura do `exclude_cancelled` do `BlocoDaAgenda`); no dia de hoje,
    faixa que já começou some.
- ⚠️ **`eventosDoDia` é IRMÃO de `eventsOfDay`, e a diferença é o ponto.** Aquele agrupa por
  `localYmd(new Date(iso))` — o fuso do **navegador**, convenção antiga do `AgendaPage`, mantida
  intacta. O novo agrupa pelo fuso do **tenant** (§6.0), porque as faixas livres já são calculadas
  lá: se as duas listas discordassem sobre a que dia pertence um compromisso das 23h, o seletor
  ofereceria uma faixa livre logo abaixo do compromisso que a ocupa. Uniformizar os dois é decisão
  separada, e mexe no `AgendaPage`.
- [x] **`NewEventModal` ganhou `initialHour?: number | null`** — ausente mantém o 09:00–10:00 de
  quem clicou num dia da Agenda sem dizer a que horas. `AgendaPage` não passa nada e segue idêntico.
- [x] **O seletor NÃO recebe `clientId`** — disponibilidade é a agenda do **dono** inteira, não os
  compromissos daquele contato. Filtrar por contato mostraria um mês vazio para quem está com a
  semana lotada. O `clientId` continua indo ao `NewEventModal`, que é quem vincula.
- [x] **O aviso de conflito do `NewEventModal` continua valendo** e não virou redundância: a agenda
  pode mudar entre abrir o mês e salvar, e o seletor não conhece compromisso fora de 08–18h.
- ⚠️ **A grade de 7 colunas NÃO alcança 44px de alvo tocável em 360px, e a exceção está escrita no
  teste.** Sete células de 44px pedem 308px + vãos; a caixa do modal oferece **280px** de área útil
  — é aritmeticamente impossível sem quebrar o calendário em duas linhas por semana. A rede da grade
  é uma altura mínima medida (36px); o recorte segue a postura já documentada do
  `modal-conta-360.spec.ts` para os campos de 38px: **a exceção fica escrita, não escondida num
  filtro**.
- [x] **O aceite em ~360px foi MEDIDO antes do merge, e achou quatro defeitos reais**
  (`apps/web/e2e/ficha-marcar-360.spec.ts`): navegação de mês com **30×30px**, "Hoje" com **26px**,
  as faixas de horário com **32px** e "Outro horário" com **38px** — todos abaixo do mínimo tocável,
  e nenhum deles visível numa asserção de classe CSS. Corrigidos com `min-h-[44px]`; o padding
  cresce, a fonte não.
  - ⚠️ **O spec congela o relógio** (`page.clock.setFixedTime`). Sem isso ele é bomba-relógio: o
    seletor abre no mês CORRENTE, e em setembro "20 de agosto" simplesmente não está na grade.
  - O localizador do título longo é **escopado ao seletor**: o mesmo texto está na lista do
    `BlocoDaAgenda`, atrás do modal, e o Playwright recusa dois elementos em modo estrito.
#### O que o passo 3 do §5 achou — e a suíte estava VERDE o tempo todo

Os três papéis de QA rodaram sobre o código já verde (675 testes, 31 do gate de 360px, `tsc` e
`eslint` limpos) e o veredito do caça-bugs foi **FAIL**. Vale registrar o que nenhum gate mecânico
pegou:

- ⚠️ **Trocar de mês deixava o dia selecionado ÓRFÃO — e um dia lotado passava a exibir dez faixas
  livres.** `irPara` mexia só em `anchor`; `eventos` virava a lista do mês novo e o painel de baixo
  continuava escrito *"15 de outubro"*, agora sobre uma janela que não cobre mais aquela data.
  Dois cliques, sem nada de exótico, e o seletor oferecia horário em cima de um compromisso
  existente — **o oposto exato do que a feature existe para fazer**, sem nem a célula selecionada
  na tela para denunciar. O `dia` agora acompanha o mês (voltar ao mês corrente reencontra HOJE;
  qualquer outro começa no dia 1).
  - O teste `"busca os eventos do mês novo ao navegar"` passava por cima disso porque aferia só os
    PARÂMETROS da requisição, nunca o que a tela mostra depois. **Asserção sobre o pedido não é
    asserção sobre a resposta.**
- ⚠️ **A faixa era ESCOLHIDA no fuso do tenant e GRAVADA no fuso do navegador.** `grade.ts` inteiro
  fala em fuso do tenant, de propósito; aí a hora atravessava a fronteira como string ingênua e o
  `new Date(...)` do `save()` a reinterpretava na máquina de quem abriu a tela. Medido: tenant em
  São Paulo com navegador em Manaus → o dono aponta 14:00 e o evento nasce às 15:00. É a família
  §6.0, reintroduzida **na costura entre dois componentes que, isolados, estavam certos**.
  `instanteNoFuso` (em `grade.ts`, com duas passadas por causa de horário de verão) resolve a hora
  de parede no instante real, e `paraInputLocal` a devolve na linguagem do `datetime-local`. Com os
  dois fusos iguais — o caso normal — o resultado é byte a byte o de antes.
- ⚠️ **Densidade da grade custava 342 ms a 3,3 s de main thread por render.** `eventosDoDia(...)`
  por CÉLULA varria a lista 42 vezes, e `today()` constrói dois `Intl.DateTimeFormat` descartáveis
  por chamada (~200 µs medidos). Com 50 eventos no mês — trivial, porque cada cobrança e cada conta
  a pagar viram um `agenda_events` — a tela travava a cada toque num dia, no aparelho de 360px que
  a feature declara atender. `densidadePorDia` faz uma passada por evento, memoizada.
- ⚠️ **`vi.setSystemTime` + `useFuso` mockado com o MESMO fuso do runner tornam o teste de fuso
  incapaz de falhar.** O `vitest.config.ts` fixa `TZ: "America/Sao_Paulo"`; enquanto o fuso do
  tenant nos testes for esse mesmo, ler o instante pelo fuso do tenant e lê-lo pelas partes locais
  do `Date` dão o mesmo resultado. **Cinco de cinco mutações no coração do `grade.ts` sobreviveram
  aos 11 testes verdes**, incluindo trocar `today(fuso, ...)` por `localYmd(new Date(...))` — no
  teste literalmente chamado *"agrupa pelo dia do TENANT, não pelo do navegador"*. É a família do
  `toContain("flex-wrap")` do §5.1, e a produção estava CERTA: o que faltava era um teste capaz de
  dizer isso. Agora há `FUSO_DISTANTE = "Asia/Tokyo"` (12h à frente do runner), e as mutações
  morrem.
  - **A regra que fica: um teste sobre fuso do tenant que roda com o fuso do tenant igual ao da
    máquina não testa fuso nenhum.** Vale para todo `vi.mock("../../store/auth")` da suíte.
- **Compromisso que atravessa a meia-noite** não ocupava nada do dia seguinte (o plantão 22h→09h
  deixava as 08h do dia 11 oferecidas). `intervaloNoDia` tem três ramos por isso.
- **Na hora cheia exata** a faixa que começa AGORA era oferecida — o corte virou `<=`. O único
  teste de corte usava 14:30, que passa com `<` e com `<=`; **só a hora cheia separa os dois**.
- ⚠️ **O `NewEventModal` fica MONTADO o tempo todo e só reescreve as datas ao abrir.** `allDay`,
  título, descrição e o aviso de conflito sobreviviam entre aberturas — e um "Dia inteiro" herdado
  faz o `save()` **descartar em silêncio** a hora que o dono acabou de apontar na faixa livre.
  Corrigido com `key`, como o `NewBillModal` já havia pago; o `seq` no `key` existe porque
  reescolher exatamente o mesmo dia e hora repetiria a chave. **A primeira abertura de cada sessão
  sempre funciona** — é o que esconde o defeito num teste manual apressado.
- **Corrida na troca de mês**: dois toques rápidos e a resposta do mês antigo chegando por último
  sobrescrevia a do mês visível. Guarda de sequência por `useRef` no `load`.

Duplicações que o dedup separou entre **introduzidas por este changeset** e herdadas — as três
introduzidas foram fechadas: `paramsDaGrade` (a regra da fronteira UTC-date vivia num comentário
copiado em dois arquivos, e regra que mora em comentário duplicado é regra que deriva),
`src/test/fixtures/agenda.ts` + `e2e/support/fixtures.ts` (o literal de 21 campos ia para seis
lugares, e as cópias de e2e nem eram tipadas), e `horaCheia`/`lib/texto.ts`.

#### A segunda rodada — o QA reprovou a PRÓPRIA correção, e três consertos estavam sem prova

Reverificados por mutação, os nove consertos morrem quando desfeitos (cada um derruba o teste que
o cobre). Mas a rodada achou mais quatro coisas, e a primeira é a mais instrutiva do PR inteiro:

- ⚠️ **A correção do fuso INTRODUZIU um bug de fuso.** `offsetEmMinutos` calculava o offset pelo
  truque comum — `new Date(x.toLocaleString("en-US", { timeZone: … }))` dos dois lados, subtrai, e
  o fuso da máquina se cancela. Ele cancela **exceto** quando as duas strings caem em lados opostos
  da virada de horário de verão **do NAVEGADOR**: aí sobram 60 minutos. Medido varrendo 16.643
  combinações de (fuso do tenant × dia × hora):

  | fuso da MÁQUINA | quebras com `new Date(string)` | quebras com `formatToParts` |
  |---|---|---|
  | `America/New_York` | **52** | 0 |
  | `Australia/Sydney` | **29** | 0 |
  | `Europe/Dublin` | **23** | 0 |
  | `America/Sao_Paulo` | 0 | 0 |

  A última linha é o ponto: **sob o fuso que o `vitest.config.ts` fixa, as duas implementações são
  indistinguíveis.** Nenhum teste desta suíte poderia pegar isso — a prova teve de ser uma
  varredura fora do runner. Hoje `offsetEmMinutos` usa `formatToParts` + `Date.UTC` e **não
  constrói `Date` a partir de string em lugar nenhum**; a ausência é a funcionalidade.
  - O Brasil não tem horário de verão e o produto é brasileiro — mas `tenants.timezone` aceita
    qualquer zona IANA, e **o fuso do navegador é de quem ABRE a tela, não de quem configurou o
    tenant**.
- ⚠️ **`densidadePorDia` nasceu sem rede.** Devolver um `Map` vazio — as bolinhas do calendário
  sumindo inteiras, que é o sinal que faz o dono escolher em que dia clicar — passava em **41 de
  41** testes. Foi o helper criado pela correção de performance, exatamente o padrão que a primeira
  rodada tinha acabado de gastar uma rodada eliminando. **Correção nova é código novo, e código
  novo nasce com teste.**
- ⚠️ **O teste de horário de verão era decorativo.** O caso escolhido (`America/New_York`,
  01/11/2026, 14:00) acerta já na primeira aproximação — a transição às 06:00Z fica antes da parede
  das 14:00Z —, então a segunda passada de `instanteNoFuso` nunca era exercitada e uma
  implementação de passada única passava. **A zona e a data não são intercambiáveis:** o caso que
  separa as duas é a LESTE de Greenwich (`Australia/Sydney`, 04/04/2026, 16:00). Há agora um
  invariante varrendo 7 zonas × 4 datas de virada × 10 horas.
- **Dois ramos de `intervaloNoDia` estavam descobertos** — o compromisso que começa DENTRO da
  janela e vara a noite (o teste existente usava 22:00, fora de 08–18, e por isso não distinguia),
  e o que cobre o dia do meio por fora. Sem eles, uma viagem de 9 a 12 deixava os dias 10 e 11 100%
  livres.
- **A régua estava cega para metade do modal.** `data-testid="seletor-horario"` vivia no `children`
  do `Modal`, então cabeçalho e rodapé ficavam FORA de `textoForaDaTela` — e a varredura devolvia
  lista vazia enquanto um nome de contato sem espaço empurrava o botão "Fechar" para **x=698 numa
  viewport de 360**. O `scrollWidth` da página continuava 360, porque a caixa tem `overflow-y-auto`:
  o mesmo disfarce que `medidas.ts` documenta para o `main.overflow-x-hidden`.
  - `Modal` ganhou `testId` (na CAIXA, com a razão escrita na prop) e o `<h2>` ganhou
    `min-w-0 break-words` + `shrink-0` no botão. **O conserto é do `Modal`, não do seletor:** o
    detalhe de evento da Agenda (`AgendaPage.tsx`, `<Modal title={event.title}>`) tinha a mesma
    exposição. **Todo modal medido pela régua deve receber `testId`, nunca um `<div>` interno.**
- **Performance, medida de novo:** a densidade caiu ~10× (135 ms → 14 ms com 50 eventos), mas o
  ramo do meia-noite encareceu `faixasLivres` em 4× — `intervaloNoDia` formatava as horas de TODO
  evento da janela de 42 dias antes de descobrir que 97% deles não encostam no dia. Agora as duas
  datas vêm primeiro e a saída acontece antes de qualquer `formatTime`; `doDia` e `livres` também
  passaram a ser memoizados, senão cada toque num dia repagava a varredura inteira.
- **`limit: 500` deixou de ser silencioso.** É o teto do endpoint e não há campo de total, então
  bater nele corta a CAUDA do mês (o backend ordena por `starts_at`) e aqueles dias apareceriam sem
  bolinha e com as dez faixas livres — a lista incompleta virando uma DECISÃO. Não paginamos:
  quando `length` bate no teto, a tela **diz que não sabe**.

Duas dívidas de teste também fecharam: `vi.useRealTimers()` saiu do corpo para um `afterEach` (no
corpo, uma asserção que falha antes dele vaza fake timers e transforma uma falha em cascata), e o
comentário que dizia *"headless roda em UTC"* foi corrigido — `vitest.config.ts` fixa
`America/Sao_Paulo` desde sempre, e era essa crença que sustentava a asserção incapaz de falhar da
primeira rodada.

- **Dívida:** a grade não tem navegação por teclado (setas entre dias) — hoje é clique/toque e
  `Tab`. E não há atalho para "próximo horário livre", que resolveria o caso do dono que só quer o
  primeiro encaixe possível, sem escolher dia.
- **Dívida:** `eventosDoDia` (fuso do tenant) e `eventsOfDay` (fuso do navegador) são coerentes
  DENTRO de cada tela e discordam ENTRE elas — com navegador ≠ tenant, um compromisso das 23h30
  aparece num dia no seletor da ficha e no dia seguinte no calendário da Agenda. Uniformizar mexe
  em `MonthGrid`/`WeekView`/`DayView` e pede regressão própria.
- **Dívida:** `lib/datetime.ts` documenta duas espécies (instante e data de calendário) e falta a
  terceira que este changeset tornou inegável — **posição de grade** (`Date` local, sem `tz`). São
  6 call sites de `toLocaleDateString` direto entre `AgendaPage` e `EscolherHorario`, e
  `formatWeekday` já existe com exatamente o bag de opções que dois deles remontam à mão — **com
  zero consumidores**, e `noUnusedLocals` não pega export não usado: enquanto ele estiver lá, morto
  e invisível a qualquer busca por uso, é ele que faz a próxima pessoa escrever o 7º
  `toLocaleDateString`. Enquanto isso, a afirmação do §6.0 ("a ÚNICA porta de formatação") tem seis
  exceções.
  ⚠️ **Quando essa dívida for aberta, `instanteNoFuso` e `offsetEmMinutos` vão junto.** Eles vivem
  em `grade.ts` provisoriamente — nasceram da grade, mas produzem e manipulam INSTANTE, que pela
  contabilidade do repo é matéria de `lib/datetime.ts`. Deixá-los lá depois da mudança faria
  `grade.ts` virar o segundo módulo de fuso do frontend, e a porta única deixaria de ser única
  também nesse eixo. O cabeçalho do `grade.ts` já diz isso.
- **Dívida:** a mesma regra de 44px aparece com duas grafias no `EscolherHorario` — `min-h-[44px]`
  (4×) e `h-11 w-11` (2×, a navegação de mês). São 12 ocorrências de `min-h-[44px]` no app;
  `packages/design-tokens` já é dono do `rounded-pill`, e um `minHeight: { toque: "44px" }` no
  preset daria `min-h-toque` greppável. E a nota do `rounded-pill` neste arquivo diz **7
  ocorrências** quando a contagem real é **190** — o erro de 27× faz a dívida se ler como "ainda
  não vale um componente".

## RBAC no frontend: a sidebar e as rotas passam a respeitar `allowed_modules` (2026-08-25)

**O frontend nunca consultava `allowed_modules` — em lugar nenhum.** A sidebar (`navigation.ts`)
mostrava os ~20 itens de menu a todo usuário, dono ou sub-usuário restrito, e nenhuma rota sabia
recusar antes da página tentar buscar dados. O sintoma achado pelo fundador: um sub-usuário sem
Jurídico/Funis abria a ficha do cliente (`/crm/clients/:id`) e ela ficava presa em **"Carregando
ficha..." para sempre** — e o mesmo em `/config` (exige o módulo `settings` inteiro).

- **Causa em `ClientDetailPage`:** o `load()` da montagem juntava as seis leituras (cliente,
  cobranças, contratos, orçamentos, jurídico, funis) num `Promise.all` só. A PRIMEIRA a voltar 403
  rejeitava o lote inteiro — `client` nunca saía de `null`, e nem os dados PERMITIDOS apareciam.
  **Causa em `ConfiguracoesPage`:** `load()` não tinha `.catch`; o 403 de `/settings/profile`
  também deixava `p` preso em `null` para sempre.
- [x] **`lib/access.ts` — `hasModule(user, module)`**, espelho **exato** de `require_module`
  (`app/core/tenancy.py`): `role === "owner" || allowed_modules.length === 0 ||
  allowed_modules.includes(module)`. Porta única desta regra no frontend.
- [x] **`navigation.ts` — cada item ganhou `module`** (o mesmo nome que `require_module` usa na
  rota que ele abre) e `visibleNavSections(hasModule)` recorta a sidebar por permissão — seção que
  fica sem item nenhum some inteira, não deixa título/divisor órfão. `navSections` em si continua
  a lista COMPLETA e estática (o que `navigation.test.ts` já afirmava).
  ⚠️ **A função entra FORA do `Stryker disable all` da issue #191** — aquele bloco existe porque o
  módulo só tinha tabela de dados, sem lógica; `visibleNavSections` é a primeira função exportada
  daqui, e o comentário do próprio bloco já previa isso ("função nova nasce fora dele").
- [x] **`App.tsx` — `<Modulo m="...">`** envolve cada rota de módulo de negócio (crm, wallet, bank,
  receivables, payables, quotes, contracts, products, stock, marketing, funnels, pages, juridico,
  financial_intelligence, investments, chart_of_accounts, cost_centers, settings): sem o módulo, a
  página **nem monta** — mostra "sem acesso" em vez de tentar buscar dados que voltariam 403. É a
  segunda camada, contra link direto/favorito/URL digitada (a sidebar sozinha só esconde o clique).
  A raiz (`/`, Cockpit) ficou **deliberadamente sem guard**: é a página de entrada do app, e
  guardá-la arriscava deixar um sub-usuário sem NENHUMA tela de pouso.
- [x] **`ClientDetailPage.tsx`** — cada leitura secundária só dispara se `hasModule` permitir (não
  há por que pedir o que já se sabe que vai 403) e tem `.catch` próprio (defesa contra falha por
  outro motivo — rede, 500 — não travar as demais seções). As cinco seções e o resumo financeiro
  somem inteiros quando o módulo correspondente falta — nunca mostram contagem zerada de algo que
  o usuário não tem permissão de ver.
- [x] **`ConfiguracoesPage.tsx`** — segunda camada de defesa: `load()` ganhou `try/catch`: qualquer
  falha mostra a mensagem em vez de travar em "Carregando..." para sempre.
- **Por que também é guard de ROTA, não só de sidebar:** a sidebar é conveniência de navegação; a
  garantia real precisa valer para quem chega direto pela URL. As duas camadas espelham o padrão
  que este arquivo já registra em vários lugares (Regra da Origem, Invariante do Trilho): a UI
  nunca é a única fronteira, o backend (`require_module`) continua sendo o fail-closed de verdade.
- **Dívida:** nenhuma tela mede em ~360px o estado "sem acesso a este módulo" — texto simples, sem
  régua própria. E `packages/shared-types` não tem um tipo fechado para os nomes de módulo
  (`hasModule` recebe `string` solto); um typo no `module` de um item novo de menu não quebraria
  build nenhum, só esconderia o item em silêncio.

## Vima: o Registro de Fatos e o briefing (PRs #85 e #90, 2026-08-06/07)

> Spec: `docs/superpowers/specs/2026-08-06-vima-registro-de-fatos-e-briefing-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-06-vima-registro-de-fatos-e-briefing.md`

`core/events.py` é in-process e síncrono, e nada era persistido — nenhuma consulta respondia
"o que aconteceu desde ontem à noite", então o dono abria cinco telas e montava o quadro na
cabeça. **`facts` é a memória narrativa do negócio inteiro**, e o briefing é a leitura dela.

- [x] **`core/facts.py` + migration 0069** — tabela `facts` (RLS), taxonomia
  `<módulo>.<entidade>.<verbo>`. **Absorveu `client_events`, que foi DROPADA** — se você
  procurar aquela tabela, é esta. `crm/timeline.py` lê daqui.
  - ⚠️ **Duas invariantes viraram guarda mecânica em `facts.record`**, não disciplina: (1) o
    `kind` precisa começar com o `module` (senão trinta módulos produzem `payment_received` e
    `payment.received` convivendo em seis meses); (2) o `title` **não pode conter dinheiro** —
    o valor é lido de `charges`/`payables`/`quotes` na composição, nunca copiado. Violar
    qualquer uma levanta `FactError` e estoura a transação de propósito.
  - **`module` é o vocabulário de `User.allowed_modules`**, NÃO o nome da pasta: `quotes` e
    `pages` emitem sob `comercial`. É o eixo de permissão do briefing.
  - `occurred_at` (quando aconteceu) é distinto de `created_at` (quando gravamos). A janela do
    briefing usa o primeiro.
- [x] **Oito módulos emitem** — `crm` · `whatsapp_inbox` · `receivables` · `payables` ·
  `agenda` · `quotes` · `pages` · `funnels`. Onde há vários caminhos para o mesmo
  acontecimento, um helper concentra a emissão (`_registra_recebimento`, `_marca_falha`):
  espalhar `facts.record` deixaria mudo o quinto caminho que alguém acrescentar depois, **sem
  quebrar teste nenhum**.
  - Das quatro formas de marcar cobrança paga, `update_payment` **não** emite (corrigir a data
    de uma baixa não é receber de novo), e liquidação `scheduled` também não — dinheiro com
    data futura ainda não entrou, e anunciá-lo no briefing seria mentira.
- [x] **`GET /vima/briefing`** (+ `POST /vima/briefing/{id}/read`), migration 0070. Idempotente
  por `(tenant, usuário, dia)`: F5 relê o gravado em vez de pagar narração nova, e o dono
  reencontra de tarde as mesmas palavras da manhã.
  - **A IA só NARRA.** Fato, Ausência e Tendência são determinísticos; o compositor decide *o
    que* entra e em que ordem, a Claude decide só *como* dizer. Inferência ("há oportunidade de
    vender para 3 clientes semelhantes") ficou para o V4 por assimetria de credibilidade: fato
    errado é bug, inferência errada ensina o dono a não confiar no briefing.
  - **Sem `ANTHROPIC_API_KEY` o briefing sai íntegro** por template — e nesse caso **não grava
    rastro de IA**, porque não houve IA. Mesmo padrão de `financial_intelligence/ai_narrator.py`.
  - **Ausência é o que faz funcionar no dia 1:** ela lê estado em aberto + relógio, não o log,
    então não depende de backfill (e **não houve backfill** — os fatos valem da implantação em
    diante). Cinco famílias: prazo estourado, dinheiro com data, ninguém respondeu, contato
    sumido, card parado, topo seco. Limiares injetáveis porque o V2 (DNA da Empresa) vai
    substituí-los.
  - **A regra do silêncio:** ausência é reportada ao CRUZAR o limiar, não enquanto permanece
    cruzada — só volta quando os dias dobram. Sem isso o briefing vira papel de parede em duas
    semanas e o dono lê por cima, inclusive no dia em que aparece a quinta pendência. É a Regra
    7 do Epic 8 ("dentro da banda: verde e SILÊNCIO") em outro domínio.
    - ⚠️ **Ela só passou a valer de FATO em 2026-08-09** — até lá o silêncio durava um dia e a
      pendência voltava no seguinte, porque a ausência calada não entrava no mapa gravado. Ver
      "A cobrança ganhou antecedência" na seção do V2.
  - **`vazio` significa "nada ACONTECEU", não "nenhuma linha".** Um tenant recém-criado sempre
    tem pendência e tendência (topo sem lead, o 🟡 de completude do Epic 8), então um flag que
    olhasse `linhas` nunca seria verdadeiro.
  - **A agregação tem como eixo a FRASE repetida** (`kind` + `title`), não o `kind`: quarenta
    vezes a mesma sentença é uma notícia, cinquenta notas diferentes são cinquenta
    acontecimentos, e fundi-las por `kind` seria omitir, não resumir.
  - **O filtro de permissão decide quais REGRAS RODAM, não quais resultados aparecem** — para
    um funcionário só de CRM a regra financeira não é executada, não é calculada e escondida.
    Elimina a classe inteira de bug em que um dado proibido vaza porque alguém esqueceu o
    filtro na saída. A decisão é a MESMA de `require_module` (owner vê tudo; lista vazia vê
    tudo) — divergir daria dois significados a `allowed_modules`.
  - Gate em `tests/test_fuso_do_tenant.py`: varredura AST sobre `app/modules/vima/` separando
    carimbar um INSTANTE (legítimo) de derivar QUE DIA É HOJE (regressão). `absences`,
    `composer` e `permissions` são puros e não podem ler o relógio nem para instante.
- **Dívida:** `occurred_at` das mensagens de WhatsApp cai no default em vez do `messageTimestamp`
  real (`InboundMessage` não carrega o campo) — janela de erro de segundos na virada do dia;
  expurgo dos sujeitos polimórficos (LGPD) não tem rotina, só `client_id` cascateia;
  `comercial.topo.sem_lead` é a única Ausência que lê o log, então enquanto o registro for novo
  ela dispara por falta de histórico e não por falta de lead; o anonimizador não mascara nomes
  apesar da docstring dizer que sim (pré-existente, o briefing herda).

### Onda 4 — as superfícies (PR #90, 2026-08-07)

O dono passou a **ver o briefing na tela** e a **recebê-lo no WhatsApp**, nos dois transportes.

- [x] **Preferência por USUÁRIO** (migration 0072: `users.briefing_whatsapp_enabled`,
  `users.briefing_hour`; rotas `GET/PATCH /auth/me/preferences`). Mora em `users`, e **não** em
  `TenantProfile`, porque dois usuários do mesmo tenant têm telefones e horários diferentes — no
  perfil da empresa um sobrescreveria o outro. É também o que permite editá-la **sem o módulo
  `settings`**: um sub-usuário sem ele precisa poder ligar o próprio WhatsApp.
- [x] **A tela é porta de entrada UMA VEZ POR DIA, não a cada login.** Mecanismo: `read_at`.
  `EntradaDoDia` guarda o dia decidido em `localStorage` **no fuso do tenant** — poupa uma ida ao
  servidor por visita e, principalmente, **quebra o laço** de quem toca "Ir para o painel" antes
  de a marcação de leitura chegar. A autoridade continua sendo o `read_at` do servidor. Roda em
  `ProtectedBareLayout` (sem shell), desenhada para 360px.
- [x] **Job no horário de cada usuário** (`vima/scheduler.tick`, etapa 6 do sweep). O relógio é
  INJETADO e a comparação é com a hora LOCAL do tenant: às 07:05 UTC ainda são 04:05 em São
  Paulo, e comparar em UTC entregaria o briefing das 7h às 4 da manhã, todo dia. Assinatura **por
  tenant** (e não `tick(db_factory)`): o worker já itera tenants com isolamento de falha por
  etapa. A entrega só sai quando o tick GEROU o briefing — é o que impede a mesma mensagem a cada
  passada do sweep até a meia-noite, sem coluna nova.
- [x] **Dia sem novidade: a tela diz que está tranquilo, o WhatsApp NÃO sai.** Um "bom dia, nada
  aconteceu" diário é a forma mais rápida de ser silenciado — e canal silenciado não entrega o
  dia em que importa.
- [x] **Evolution em um passo, Meta em dois.** `capabilities.briefing_needs_optin` — e **o
  consumidor nasceu no mesmo passo** (`scheduler._entregar_no_whatsapp`), pela lição do item 12
  acima. Meta: parâmetro de template da Cloud API **não aceita quebra de linha** e às 7h o dono
  está sempre fora da janela de 24h, então sai um template curto **com botão**, o toque abre a
  janela e o texto inteiro vai depois, livre.
- ⚠️ **`send_template` passou a enviar o COMPONENTE de botão.** Sem ele, a Meta devolve no toque o
  **rótulo que o tenant escreveu no console dela** (texto livre: "Ver resumo", "Bora", "Sim") — e
  não haveria constante para casar do lado de cá. O payload é derivado do `purpose` em
  `process_pending`, sem coluna nova. Formato do webhook **conferido contra a documentação da
  Meta**, não suposto (`type:"button"` + `button:{payload,text}`; e `interactive.button_reply`).
- ⚠️ **O reconhecimento do toque fica DEPOIS do registro da mensagem e FORA do bloco de `facts`.**
  Aquele bloco é pulado quando a mensagem vem do telefone do time (`_e_telefone_da_equipe`), e o
  toque vem SEMPRE de lá — dentro dele, o opt-in seria descartado junto e o briefing nunca sairia.
  A guarda vale nos dois sentidos: o dono não vira lead do próprio funil, e um estranho que repita
  o payload não destrava briefing nenhum.
- **Dependência EXTERNA, fora do repositório:** o template com botão precisa de **aprovação da
  Meta**. Enquanto não houver, o tenant Meta fica sem briefing por WhatsApp — e a UI de
  preferências **diz por quê** em vez de oferecer um switch que liga e não entrega nada
  (`vima/delivery.avaliar`, o mesmo veredito que o scheduler usa; divergirem faria a tela dizer
  "ligado" e o job não mandar nada).
- [x] **A validação em ~360px do briefing FOI FEITA (2026-08-10) e PASSOU, sem conserto.**
  `scrollWidth` 360, 1145px de altura, nada fora da tela, nada cortado, um alvo por linha. Ela é
  imune ao defeito da topbar porque roda em `ProtectedBareLayout` (sem shell).
- **Dívida:** quem gera o briefing abrindo o app antes do próprio horário não
  recebe o WhatsApp daquele dia (a tela já marcou como lido — troca deliberada, ver a docstring
  de `scheduler.tick`).

## Contabilidade de IA e roteamento de modelo por tarefa (PR #87, 2026-08-06)

O produto já gastava IA em produção e **não sabia quanto, nem por quem**: seis módulos chamavam
`ai.complete` e cinco descartavam os tokens que a Anthropic devolvia. A conta chegava pela fatura.

- [x] **Ledger `ai_usage`** (migration 0071, RLS `FORCE`) — tenant, usuário, tarefa, **o modelo
  que realmente rodou** (não o configurado) e quatro contadores de token. Cache tem colunas
  próprias porque tem **preço próprio** (leitura ~0,1× do input, escrita ~1,25×): achatá-lo em
  `input_tokens` daria conta errada.
- [x] **`db`, `tenant_id` e `task` são OBRIGATÓRIOS em `ai.complete`** — é o que torna
  impossível chamar a IA sem contabilizar. Esquecer vira `TypeError` na hora, não uma linha
  faltando na conta seis meses depois. Mesma disciplina de `payables.is_overdue`, que exige
  `today` pela mesma razão. Tudo keyword-only (`db` inclusive), ao contrário de
  `facts.record(db, *, ...)`: vários testes de narrador mockam `ai.complete` com `lambda **kw`.
- ⚠️ **A regra de gravação do ledger é o OPOSTO da de `facts.record`** — quem ler por analogia
  vai concluir errado. `facts` falha junto com a transação de propósito. Aqui não: quando o
  ledger grava, a chamada à Anthropic **já aconteceu e já custou dinheiro**; derrubar a
  transação perderia o documento que o usuário esperou 40 segundos para receber, e o gasto
  teria ocorrido do mesmo jeito. É best-effort com `logger.exception`.
  - **E `try/except` sozinho NÃO entrega essa promessa.** Um `flush()` que falha deixa a
    `Session` em rollback pendente: o `except` engole a exceção e o **commit do CHAMADOR** morre
    depois, longe dali, com mensagem que não menciona IA. `begin_nested()` (SAVEPOINT) delimita
    a falha. Provado por mutação — sem ele, o teste quebra com `PendingRollbackError` apontando
    para `facts.module`. **Se mexer nessa função, mantenha o savepoint.**
- [x] **`MODELO_POR_TAREFA` substituiu o `anthropic_model` global** (`ANTHROPIC_MODEL` saiu do
  `.env`). O critério é o **custo do erro**, não o tamanho do texto: `claude-haiku-4-5` onde a
  IA só reescreve o que um motor determinístico calculou (`vima.briefing`,
  `financeiro.diagnostico`, `receivables.cobranca`); `claude-sonnet-5` onde ela redige
  (`quotes.escopo`, `funnels.compose`, `marketing.carrossel`); `claude-opus-5` onde alucinar tem
  consequência jurídica (`juridico.documento`).
  - **Tarefa desconhecida cai no default, e o default é o modelo mais CAPAZ, não o mais barato**
    — roteada por engano para Haiku degradaria em silêncio; para Opus, só custa mais, e o
    excedente aparece no ledger.
  - `claude-opus-5` custa **o mesmo** que o `claude-opus-4-8` que estava global ($5/$25 por
    Mtok): foi ganho de capacidade sem centavo a mais.
  - Gate `test_toda_tarefa_roteada_usa_um_modelo_conhecido`: um typo num ID viraria 404 só em
    produção, na primeira chamada real daquela tarefa.
- **Escopo:** só MEDIR. Sem cobrança, tela ou teto de gasto — medir é reversível, decisão de
  preço não é, e ela não foi tomada. **Sem backfill:** o consumo passado não foi guardado por
  ninguém e não tem como ser reconstruído. **Dívida:** `LegalDocument.input_tokens` continua
  guardando tokens na linha do documento, agora em paralelo ao ledger (não foi removido).

## Vima V2: o DNA da Empresa (2026-08-08)

> Spec: `docs/superpowers/specs/2026-08-08-vima-dna-da-empresa-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-08-vima-dna-da-empresa.md`

O V1 entregou um briefing que fala com todo mundo do mesmo jeito: os cinco limiares de
`absences.py` eram defaults escolhidos por nós. Um advogado que responde em dois dias e um social
media que responde em duas horas recebiam o mesmo aviso na mesma hora.

- [x] **Duas classes, e a classe é contrato mecânico, não etiqueta** (`dna/catalog.py`, 46
  perguntas em código — eram 45 até a 7ª de Calibração nascer em 2026-08-09):
  - **Calibração (7)** tem consumidor HOJE; responder muda o briefing de amanhã.
  - **Retrato (39)** não tem, por definição; é guardado para o V4.
  - ⚠️ **Duas guardas rodam no IMPORT do módulo**: Calibração exige `consome`, Retrato o proíbe;
    e `consome` tem que apontar para chave real de `LIMIARES_PADRAO`. Sem a segunda, um typo em
    `card_parado_dais` produz **silêncio perfeito** — grava, o `{**PADRAO, **override}` ignora a
    chave estranha, e o dono responde para sempre sem efeito nenhum, sem erro nenhum.
  - **São 7 de Calibração porque só existem 7 consumidores** (eram 6; o 7º nasceu junto com a
    pergunta dele, e é o único caminho legítimo para esse número subir). Qualquer número maior seria
    invenção. `dinheiro.tolerancia_dias` parece Calibração (tem número, tem opções) e é Retrato:
    não existe regra de Ausência sobre carência. A classe é definida pelo contrato, nunca pelo
    formato.
- [x] **`dinheiro_com_data_dias` separou duas regras que dividiam `prazo_vencendo_dias`** — prazo
  da agenda e conta a pagar. Nasce com o mesmo valor `1`: refactor puro no dia do merge.
- [x] **O núcleo do primeiro acesso NÃO é de Calibração** (é a inversão central do design).
  *"Em quanto tempo eu te aviso que ninguém respondeu o Carlos?"* é irrespondível antes de ter
  visto um briefing — a resposta seria um chute que vira comportamento errado com aparência de
  configuração deliberada. Calibração vai toda por **gancho colado à ausência** que a motivou.
- [x] **Uma pergunta por gancho por dia, no produto inteiro**, e pulada em quarentena de 7 dias
  (`dna/cadencia.py`). O núcleo é a exceção declarada: sequência anunciada e interrupção não
  anunciada não cansam igual.
  - ⚠️ **A data do carimbo passa por `local_date`, não por `.date()`.** `answered_at` é
    `timestamptz`: um dono em UTC−3 respondendo às 22h produz carimbo de 01h do dia seguinte em
    UTC, a cota do dia não é reconhecida e ele é perguntado de novo às 22h05. Provado por
    mutação. `app/modules/dna/` entra na varredura AST de `test_fuso_do_tenant.py`.
- [x] **`dna/resolver.py` é a ÚNICA porta de leitura.** Nenhum outro módulo lê `dna_answers`
  direto — é o que mantém Retrato honestamente sem consumidor até o V4, em vez de vazar por um
  `select` esperto. Resposta órfã (opção que saiu do catálogo) cai no default em vez de derrubar
  o briefing.
- ⚠️ **`None` num limiar significa REGRA NÃO EXECUTADA**, não "limiar infinito" — mesma forma do
  filtro de permissão do V1. Só `topo_sem_lead_dias` pode ser desligado, porque é a única
  Ausência que dispara sobre o VAZIO: sem cards não há card parado, mas sem lead ela cutuca todo
  dia, para sempre.
- ⚠️ **`recalibrado_apos` compara `>=`, e o `>` estrito quebrava o recurso inteiro.** O caso
  normal é o dono recalibrar HOJE, pelo gancho do briefing de hoje, cujo `reference_date` também
  é hoje — com `>`, a limpeza do silêncio nunca acontecia no dia seguinte, que é justamente
  quando ela precisa acontecer.
- [x] **`Linha` do compositor ganhou `kind`** (default `""` — briefings gravados antes do V2 não
  têm o campo, e lê-los sem default estouraria).
- **O DNA é da EMPRESA:** `require_module("settings")` na rota inteira, o oposto do
  `vima/router.py` (lá o recorte é por linha). É também o oposto das preferências de briefing do
  V1, que foram para `users` por serem pessoais.
- **O V2 não chama IA em ponto nenhum** — custo marginal zero por tenant.
- **Dívidas:** as 46 perguntas nunca foram validadas com dono real (**não é instrumentável — é
  conversa com dono**); ~~não há medição de ativação do núcleo~~ **FECHADA em 2026-08-11**, ver "A
  ativação do núcleo deixou de ser invisível" abaixo; a quarentena de 7 dias e o "uma por dia"
  continuam sendo números sem evidência, mas **agora existe evidência sendo acumulada** — ler 2
  tenants não confirma número nenhum.
- [x] **A validação em ~360px do núcleo e da aba FOI FEITA (2026-08-10).** **O núcleo passou sem
  conserto** — `scrollWidth` 360, uma pergunta por tela, opções com 54px de altura, e também roda
  em `ProtectedBareLayout`. **A aba "A sua empresa" não:** ela abria com **16.495px = 22,3 telas**
  (Oferta 3096 · Cliente 3552 · Ritmo 3554 · Dinheiro 3366 · Limites 2434), com a pergunta que o
  PR #103 acrescentou ao eixo `dinheiro` a **14,6 telas** do topo. Agora os cinco eixos abrem
  RECOLHIDOS (`<details>` nativo, com contador respondidas/total no cabeçalho) — o texto da própria
  aba diz que "a Vima pergunta aos poucos", e despejar as 46 de uma vez a contradizia. Travado por
  `apps/web/e2e/toque-360.spec.ts`.
  - A régua de abas do `/config` tem 641px de conteúdo em 312px visíveis e **rola**
    (`overflow-x-auto`, obedece o PR #58); "A sua empresa" é a 2ª e está visível sem rolar a régua.
    **Dívida:** as abas 3-5 não têm pista de que existem além de um ícone espiando na borda.

### A cobrança ganhou antecedência, e a regra do silêncio passou a valer (2026-08-09)

> Spec: `docs/superpowers/specs/2026-08-09-vima-cobranca-com-antecedencia-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-09-vima-cobranca-com-antecedencia.md`

Investigar a dívida da cobrança revelou que **a regra do silêncio estava quebrada em dois
lugares**, e um deles já sangrava: uma conta a pagar em aberto aparecia todo dia do
vencimento−1 ao vencimento+2, e depois dia sim, dia não, para sempre.

- [x] **`_proximo_marco` substituiu `anterior * 2`** — três ramos: negativo devolve `0` (falou
  antes de vencer, volta no vencimento), zero devolve `1`, positivo devolve `anterior * 2`,
  **literalmente a expressão de antes**. É essa identidade que tornou seguro aplicar o conserto
  às cinco famílias de uma vez, e ela **foi provada por mutação**: trocar a função de volta pelo
  dobro puro derruba 3 testes, todos de dinheiro ou da própria função — **nenhum comercial**.
  - ⚠️ **O ramo `anterior == 0` é INERTE hoje, e isso está medido.** Removê-lo derruba só o teste
    de unidade que o descreve, nunca a linha do tempo: como `dias` cresce de 1 em 1, `proximo(0)`
    valendo `0` ou `1` produz a mesma sequência. Ele fica por correção semântica ("qual é o
    PRÓXIMO marco" não pode responder o marco atual), não por comportamento — e quem for
    simplificá-lo não vai quebrar nada, o que é exatamente o motivo de estar escrito aqui.
- [x] **O mapa do payload deixou de ser "o que eu disse" e virou "em que ponto cada ausência
  viva parou"** (`Payload.marcos`, chave JSON `marcos`). Antes ele era montado só com as linhas
  `mantidas` e lido só do briefing anterior: a ausência calada não entrava nele, e no dia
  seguinte "sem valor anterior" era indistinguível de "nunca falei disto". **O silêncio durava
  exatamente um dia.** Os testes cobriam as duas transições de UM dia e passavam — o defeito só
  aparece encadeando TRÊS.
  - ⚠️ **`marcos_anteriores` de `absences.Coleta` NÃO é "as caladas"** — é o marco de toda
    ausência viva que já tem um. A diferença aparece no teto: dita e CORTADA pelas 12 linhas
    também preserva o marco, porque ninguém a leu. Reduzir isto às caladas reintroduz a piscada
    por outro caminho.
  - ⚠️ **`service._marcos_do_payload` lê `ausencias_ditas` como fallback, e isso é PERMANENTE.**
    Os briefings gravados em produção têm a chave antiga; sem o fallback o produto perderia
    todo o silêncio no dia do deploy e repetiria de uma vez tudo que já tinha dito.
- [x] **A cobrança a receber avisa antes de vencer** (`cobranca_antecedencia_dias`, default
  **3**, decidido pelo dono do produto e não derivado de outro número). As duas direções do
  dinheiro passaram a seguir a mesma regra, com limiares separados porque as intenções são
  diferentes: juntar dinheiro para pagar × cutucar o cliente antes de ele atrasar. A cadência é
  *aviso → vencimento → 1 → 2 → 4 → 8 → 16*, fixada por um teste que percorre 21 dias.
  - ⚠️ **`financeiro.cobranca.vencida` virou `financeiro.cobranca.vencendo`** — o nome antigo
    passou a ser mentira quando a linha saiu antes de vencer. Custou uma repetição no dia do
    deploy (as chaves gravadas usam o nome velho), e é o preço certo.
- [x] **7ª pergunta de Calibração** (`dinheiro.cobranca_antecedencia_dias`), com o consumidor
  nascido no mesmo passo — o único caminho legítimo para o número 6 subir. **Não entrou no
  núcleo:** Calibração vai por gancho, colada à ausência que a motivou.
  - ⚠️ **O limiar e a pergunta são o MESMO commit porque o repo já exigia isso.**
    `test_todo_limiar_tem_pergunta` reprova limiar sem pergunta ("um número que ninguém pode
    calibrar"); o plano previa dois commits e o gate estava certo. É o princípio "capacidade
    nasce com o consumidor no mesmo passo" já mecanizado — quem acrescentar limiar sem pergunta
    descobre na hora, não em produção.
  - **Gate novo:** todo gancho de Calibração tem de apontar para um `kind` que existe em
    `absences.py` (varredura da fonte, com controle positivo). Renomear um sem o outro não
    quebrava teste nenhum — a pergunta só nunca mais apareceria, e o dono nunca calibraria
    aquela regra. Silêncio perfeito, do mesmo feitio que a guarda de `consome` impede.
- **Efeito visível no dia do deploy:** o briefing fica mais quieto em TODAS as seções, não só na
  do dinheiro — pendências que apareciam dia sim, dia não passam a aparecer só nos marcos.
- **Achado registrado e NÃO corrigido aqui:** `dna/resolver.recalibrado_apos` usa
  `answered_at.date()` num `timestamptz`, a mesma forma que a `cadencia.py` documenta como
  errada. Aqui ela erra sempre para o lado de LIMPAR o silêncio, que é o erro barato declarado
  na própria docstring, e a varredura AST não a pega porque não é leitura de relógio.
- [x] **A validação em ~360px do V2 foi feita em 2026-08-10**, e a linha nova do eixo `dinheiro`
  renderiza correta (278px de largura). Ver a seção do V2, acima.

### A ativação do núcleo deixou de ser invisível (2026-08-11)

> Spec: `docs/superpowers/specs/2026-08-11-vima-v2-medicao-de-ativacao-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-11-vima-v2-medicao-de-ativacao.md`

A dívida escrita dizia *"não há medição de ativação do núcleo"*. Verificado no código, o estado era
**pior**, e em dois pontos era **destruição de dado acontecendo agora**. Esta onda é
**instrumentar, não analisar**: nenhuma tela, nenhum endpoint de leitura, nenhum limiar, nenhuma
migration.

- [x] **A docstring de `dna/models.py` parou de ser falsa.** Ela defendia o upsert dizendo que *"o
  histórico de quem mudou o quê já é trabalho de `core/audit.py`"* — e `audit` aparecia **UMA** vez
  no módulo inteiro, **dentro dessa frase**, com zero chamadas. É a classe de defeito nº 1 do Epic
  8 (o documento que afirma sobre a camada de baixo e desliga quem viria conferir), e aqui mais
  grave que nas quatro instâncias de lá porque **sustentava uma decisão de modelagem**: o upsert foi
  aceito em troca de uma rede que ninguém tinha tecido. A escolha foi **tecer a rede**, não corrigir
  a frase para menos.
- [x] **Quatro `action`s, e o `source` mora no `target`.** `dna.answer.save` · `dna.answer.skip` ·
  `dna.nucleo.open` · `dna.nucleo.abandon`, com `target=<source>:<pergunta>` nas duas primeiras e
  `str(n)` no `open`. ⚠️ **Quatro actions × três sources (`nucleo｜gancho｜config`) seriam DOZE
  strings**, e é assim que 117 actions distintas viram 200 — o repo já tem `account_deleted`, sem
  pontos e fora do padrão, provando que a convenção sozinha não segura o vocabulário.
- [x] **`dna/eventos.py` é a porta única, com guarda mecânica.** `facts.record` valida o `kind`
  contra o `module`; `audit.record` **não valida nada**. `eventos.registrar` recusa toda action
  fora de `ACTIONS`, e um gate AST (`test_dna_vocabulario_gate.py`) garante que ninguém mais no
  módulo chama `audit.record` — allowlist de **um** membro, no padrão de `sync_origin_movement`.
  **Com controle positivo em cada asserção**, inclusive um do próprio scanner: sem ele, um glob que
  deixasse de casar aprovaria o módulo inteiro em silêncio.
- [x] **O teste que prova a dívida fechada:** responder `oferta.ticket_tipico` no núcleo, editar a
  mesma pergunta no `/config`, e asserir **duas** entradas de audit com **uma** linha em
  `dna_answers`. É a diferença entre o upsert apagar história e o upsert ser só estado atual.
- ⚠️ **`db.flush()` antes de gravar a trilha, e a razão aqui NÃO é a do MNT-001.** O padrão do repo
  (`bank.create_account`) existe porque o `target` costuma ser o `id` da linha, que tem default
  Python-side e é `None` antes do INSERT. Aqui o `target` é `<source>:<pergunta>` e **não depende de
  `id` nenhum** — o flush fica pelo segundo motivo que `bank.create_transaction` documenta: é nele
  que a unique constraint de `(tenant, question_key)` fala, e um rastro escrito antes dela afirmaria
  uma resposta que ainda pode ser recusada. **Copiar para cá a justificativa do MNT-001 seria
  cometer, dentro desta onda, a classe de defeito que ela veio fechar.** Os outros 17 call sites
  continuam abertos.
- [x] **`POST /dna/nucleo/{evento}` — UMA rota, evento no caminho**, validado contra tupla
  declarada, 204, e **o front ignora a resposta**.
- ⚠️ **O caminho de erro grava NADA, e é isso que o torna distinguível.** `open` é emitido só
  **depois** de `GET /dna/faltantes` ter sucesso **e só quando havia pergunta para ver** — então
  **ausência de `open` ⇒ a pessoa nunca entrou**, verdade derivada sem inventar um terceiro evento
  (`dna.nucleo.unavailable` seria categoria que ninguém pediu, com consumidor inexistente). Um
  sub-usuário sem o módulo `settings` toma 403 e **não é contado como abandono**.
- ⚠️ **`sair()` do `NucleoPage` tem QUATRO chamadores e só UM é abandono.** 403/rede ruim, núcleo
  vazio e fim da sequência **não são** abandono; só o botão "Pular por enquanto" é. Por isso o
  beacon **não** entrou dentro de `sair()` — lá dentro ele reportaria abandono de quem concluiu o
  núcleo, e gravar `abandon` no caminho de erro seria mentira.
- ⚠️ **A covardia da telemetria é MECANIZADA, não prometida.** O teste clica em "Pular por
  enquanto" com o `POST` rejeitando e verifica `localStorage` e navegação **sem nenhum `await` entre
  o clique e a asserção**: se alguém escrever `await api.post(...)` antes do `sair()`, a marca só
  existiria num microtask seguinte e o teste morre. É a forma executável de *"o abandon é disparado
  e a saída não o aguarda"*.
- [x] **O denominador é GRAVADO; o progresso é DERIVADO.** `faltantes` devolve só as não
  respondidas (na 2ª visita a pessoa vê 4, não 6), e `catalog.NUCLEO` pode crescer — o eixo de
  Calibração já cresceu de 6 para 7 em 2026-08-09 —, o que viraria todo "k de 6" histórico em "k de
  7" **retroativamente**. O número exibido é evidência do que a pessoa viu, no princípio do
  `raw_description` de `bank_transactions`: imutável porque é prova.
- [x] **`python -m app.scripts.nucleo_activation` — sem `--fix`, imprimindo quantos tenants
  varreu.** `0 passagens em 0 tenants` e `0 em 7` são resultados diferentes, e o primeiro é defeito
  do script.
  - ⚠️ **Ele NÃO roda sob `e1p_root`, e a spec pedia isso.** O perigo que ela nomeia é real (uma
    consulta a tabela com RLS por sessão **sem** tenant devolve zero linhas sem erro — a sondagem
    de `phone_key`), mas as duas saídas se **excluem**: sob um papel que faz bypass a policy não se
    aplica, e como nenhuma query deste repositório filtra tenant à mão (Regra de Ouro nº 1), cada
    tenant reportaria os eventos de **todos os outros**. O script segue o molde que a própria spec
    nomeia (`investment_audit.py`): itera a tabela global `tenants` e abre `tenant_session` por
    tenant. **Regra que fica: "rode sob o papel de bypass" e "abra sessão por tenant" são duas
    respostas à MESMA armadilha, e escolher uma proíbe a outra — quem migrar este script para
    `e1p_root` precisa acrescentar `WHERE tenant_id` no mesmo commit.**
- [x] **A instrumentação NÃO é escopada ao núcleo, e isso saiu de graça.** `responder`/`pular` já
  recebiam `source`, então a mesma chamada cobre `gancho` e `config` — é essa contagem por origem
  que vira a evidência sobre a quarentena de 7 dias e o "uma por dia" (a meia dívida acima).
- ⚠️ **O empate de `created_at` no SQLite não é teórico, e apareceu na primeira execução.**
  `AuditEntry.created_at` é `server_default=func.now()`, que no SQLite tem resolução de **segundo**:
  duas chamadas HTTP seguidas saem com o mesmo carimbo e a ordem cai no desempate por `id`, que é um
  uuid — arbitrário. O teste que semeava pela rota e afirmava ORDEM estava testando o acaso, e
  falhou de cara. Agora ele afirma o **recorte** (por conjunto), e a ordem é exercitada só onde pode
  ser fixada: nos testes de `derivar`, com `created_at` explícito. É a mesma distinção do histórico
  de saques da Onda 3 — **dentro do mesmo instante não existe "mais novo"**, e um teste que o
  afirmasse mediria o acaso.
- **Consequência aceita: a marca `localStorage` (`e1p_dna_nucleo`) CONTINUA sendo a autoridade
  sobre reexibir o núcleo.** Movê-la para o servidor seria mudança de comportamento embutida numa
  onda de medição, e misturar as duas tira do gate a capacidade de julgar o que quebrou o quê (o
  argumento que manteve SIG-001 fora da 8.16 e separou 8.19 de 8.20). Um dono que abandonou no
  celular e abriu no desktop **verá o núcleo de novo**, e o rastro mostrará **dois `open`** — isso é
  verdade sobre aparelhos, e o script não os reporta como duas passagens do mesmo dono.
- **LGPD:** `audit_entries` é purgado com o tenant pelo `delete_account` (descoberta dinâmica de
  subclasses de `TenantMixin`). Tenant que sai leva a ativação dele, e é o comportamento correto;
  `platform_audit_entries` **não** é usada aqui — aquela existe para operação destrutiva do Master,
  não para telemetria de produto.
- **A população é 2, e é ela que decidiu o desenho.** Os tenants reais que passarão pelo núcleo nos
  próximos ~3 meses são **dois** (o fundador e o sócio — a produção foi zerada em 05/08 para o sócio
  começar do zero). Funil com N=2 é ilusão estatística: *1 de 2 pulando o núcleo* é "50% de
  abandono" e **não significa nada** — a família de erro que o Epic 8 documenta três vezes. O que
  justifica esta onda **não é estatística, é irreconstrutibilidade**, o mesmo argumento do
  `ai_usage` (*"o consumo passado não foi guardado por ninguém e não tem como ser reconstruído"*).
  **Enquanto forem 2, a resposta à pergunta da dívida vem de conversar com as duas pessoas.**
- **Dívida:** `audit_entries` cresce — quatro eventos por tenant por passagem, mais um por resposta
  de gancho. Dezenas por tenant por ano; irrelevante hoje, anotado para não ser descoberto como
  surpresa.
- **Dívida:** o script não tem teste `rls_e2e` (o `investment_audit.py` tem). A leitura por tenant é
  coberta contra o SQLite dos testes, e o isolamento real depende do mesmo `tenant_session` que os
  outros três scripts já usam em produção.
- **Dívida (a que NÃO fecha):** as 46 perguntas seguem nunca validadas com dono real. Não é
  instrumentável; é conversa com dono.

## Deploy: o script detecta o ambiente — e a lista de compose files vem do LABEL

`infra/scripts/deploy.sh` sobe uma versão nova no ambiente em que o host roda, sem flag de
ambiente: ele lê o label `com.docker.compose.project.config_files` do `infra-api-1`, que registra
**todos** os arquivos com que a stack foi criada. Escolher o compose errado no host errado deixa
de existir quando ninguém escolhe.

- ⚠️ **A lista de compose files era CRAVADA no script, e isso derrubou a produção em 2026-08-20.**
  A instância da AWS tem três arquivos **não versionados** (assim `git pull` nunca conflita):
  `DEPLOY-AWS.md` (o runbook real daquela máquina), `infra/docker-compose.override.yml` e
  `infra/Caddyfile.single`. O override monta o `Caddyfile.single` no lugar do `infra/Caddyfile`
  versionado, que tem o bloco wildcard `*.{$ROOT_DOMAIN}` exigindo `CLOUDFLARE_API_TOKEN` — **vazio
  ali de propósito**. Recriar o `caddy` sem o override fez o Caddy **recusar a config INTEIRA**
  (`missing API token`) e derrubar **também o domínio único**, com o certificado dele intacto em
  disco. ~40 min fora do ar. É a **issue #151**.
  - Um placeholder não salva: o plugin da Cloudflare valida o **formato** do token (40 chars
    `[A-Za-z0-9_-]`), e passando no formato a sobreposição do wildcard com o domínio principal
    (`DOMAIN=e1p.criativaeduca.com.br` é subdomínio de `ROOT_DOMAIN=criativaeduca.com.br`) continua
    impedindo o TLS. Medido, nos dois passos.
- ⚠️ **`--env-file` é obrigatório nos DOIS perfis, e a exceção que existia era falsa.** O script
  dizia que a AWS *"resolve o env por env_file: interno, nao precisa da flag"*. Os dois compose
  files usam `${VAR}` para as senhas, e **interpolação não vem do `env_file:` de serviço** — sem a
  flag o compose morre em `required variable APP_DB_PASSWORD is missing` antes de listar um
  serviço sequer.
- **`COMPOSE_ARQ` (o arquivo primário) sobreviveu**, e só para o `COMPOSE_FILE` que o `backup.sh`
  consome; tudo que roda compose usa `COMPOSE_ARGS`, derivado do label.

> **A regra que fica, e ela é maior que este script:** **o repositório descreve o deploy
> CANÔNICO; a máquina carrega os desvios que ninguém commitou.** Esses desvios são invisíveis a
> qualquer leitura do repo, e um container rodando há dias pode estar servindo uma config que
> **não existe mais em disco** — o defeito só aparece na recriação, longe da mudança que o causou.
> Antes de qualquer comando que recrie container: `git status` no checkout do servidor e procure
> um `DEPLOY*.md` local. É a mesma família do comentário inline no `.env.prod` (§Anexos) e da
> config do webhook da Evolution em memória (§WhatsApp): **estado em memória divergindo do estado
> em disco**, três vezes no mesmo repositório.

#### A guarda de "checkout limpo" abortava 100% dos deploys na AWS (2026-08-21)

**`git status --porcelain` lista arquivo NÃO RASTREADO como `?? caminho`**, e a instância da AWS
carrega três de propósito — `DEPLOY-AWS.md`, `docker-compose.override.yml`, `Caddyfile.single` —
justamente para o `git pull` nunca conflitar. A guarda do passo 2 era
`[[ -z "$(git status --porcelain)" ]] || morre`, então **um `?? DEPLOY-AWS.md` sozinho já
derrubava**: o script morria antes de fazer qualquer coisa, em toda execução, naquele host.

- ⚠️ **A ironia é o que ensina: o MESMO script conhecia os três arquivos.** O comentário do passo
  1 os cita **por nome** para explicar por que a lista de compose vem do label em vez de ser
  cravada. A guarda do passo 2, doze linhas abaixo, não recebeu a mesma informação. **Saber de um
  fato num ponto do arquivo não o propaga para o resto dele** — e nada no #167 protestou, porque
  o script nunca tinha sido rodado no host que ele existe para servir.
- [x] **`--untracked-files=no`, e isso NÃO é afrouxar.** O risco que a guarda existe para pegar
  continua pego: arquivo **versionado** modificado ou em stage — o caso *"editei em produção para
  testar e esqueci"* —, que faria o `git pull --ff-only` do passo seguinte falhar no meio do
  deploy. O que ela parou de recusar é o desvio que a máquina carrega **por desenho**.
- [x] **O teste EXTRAI a linha do `deploy.sh` e a EXECUTA** num repo git descartável
  (`test_deploy_guarda_checkout_limpo.py`) — não é uma cópia da linha escrita no teste, que
  passaria a concordar consigo mesma no dia em que alguém editasse o script. **Provado por
  mutação:** com a guarda de volta ao `--porcelain` puro, morre exatamente o caso do não
  rastreado e os três controles seguem verdes.
  - Os controles positivos são **três**, e cada um mata uma guarda degenerada diferente:
    versionado modificado **aborta**, mudança em **stage** aborta (o `--untracked-files=no` não
    pode cegar a guarda para o índice), e checkout limpo **passa** — sem este último, uma guarda
    que recusasse tudo passaria nos dois primeiros.
- ⚠️ **`bash` nesta máquina de dev é o do WSL, e ele traz um git PRÓPRIO** (`PWD=/mnt/c/...`).
  Com `core.autocrlf` diferente do git do Windows que cria o repo de teste, os dois discordam
  sobre um arquivo escrito com LF: um vê limpo, o outro vê ` M`. O repo de teste nascia **sujo** e
  os dois casos de "aceita" falhavam por um motivo que não tinha nada a ver com a guarda — 20
  minutos de investigação até o `PWD` no log denunciar. O fixture fixa `core.autocrlf=false` **no
  repo** (não por `-c`), que é o que faz os dois gits lerem a mesma coisa.
- **O gate roda no job `cross-tenant-rls`, junto com o do Caddyfile**, no mesmo passo e sob a
  mesma guarda anti-vacuidade — agora `executados >= 9` (5 + 4) em vez de `>= 1`, que aceitaria
  **um dos dois** pulado em silêncio. Os dois dependem de `infra/` alcançável e se auto-pulam
  dentro da imagem da API; um gate que se pula sozinho fica verde sem proteger nada.

> **A regra que fica:** um script de operação só está verificado depois de rodar **no host que
> ele existe para servir**. `--dry-run` na máquina de dev prova que ele RECUSA o ambiente errado
> (o que é uma garantia real, e ela funcionou); não prova que ele aceita o certo.

- **Dívida:** nada no repo REPROVA um deploy que ignore o override — a garantia é o script, e quem
  rodar compose à mão continua exposto. ⚠️ **Mas a issue #151 está FECHADA** (PRs #170 e #193, em
  produção desde 21/08): o `infra/Caddyfile` não tem mais o bloco wildcard incondicional, então
  esquecer o override deixou de derrubar o site. O override segue valendo pelo `Caddyfile.single`.
- **Dívida:** o `deploy.sh` **nunca completou uma execução de verdade** — o `--dry-run` da AWS
  parava na guarda, e o primeiro caminho feliz ainda não aconteceu. Os passos 3 em diante (gate de
  CI, backup, `up -d`, prova do bundle) seguem exercitados só por leitura.
- **Dívida:** o `CLOUDFLARE_API_TOKEN` segue vazio na AWS. Correto hoje (sem wildcard, sem DNS-01);
  vira problema no dia em que subdomínio por tenant entrar em uso.

## 6.0 Correções importantes
- **[CORRIGIDO 2026-08-05] O sistema inteiro passou a viver no fuso do tenant (era UTC).** O sintoma que o fundador viu foi a linha do tempo do Funil exibindo `Aguardando até 2026-08-05T11:11:32.812731+00:00` — formato de máquina e 3h adiantado. A investigação achou **três** defeitos com a mesma raiz: existia infra de fuso (`core/tz.py` + `tenant.timezone`, migration 0044) mas só 3 módulos a consumiam.
  1. **Texto para humano com UTC cru.** `funnels/engine.py` interpolava `resume_at.isoformat()` na mensagem; `contracts/service.py` montava a variável `{{DATA}}` com `datetime.now(UTC)` — um contrato criado às 22h saía datado do dia seguinte, e essa é a data que vale juridicamente.
  2. **"Hoje" ancorado em UTC em 21 pontos** (`payables`, `receivables`, `bank`, `projection`, `wallet`, `quotes`, `products`, `cockpit`). Das 21h à meia-noite em UTC−3 o "hoje" do servidor já era amanhã: vencimento, atraso, projeção de caixa e saldo deslizavam um dia **toda noite**.
  3. **Frontend sem fuso e sem helper.** ~25 telas chamavam `toLocale*` sem `timeZone`, formatando no fuso do NAVEGADOR — certo por acidente num PC brasileiro, "Greenwich" em qualquer máquina em UTC. E o Cockpit pedia `?day=` com `toISOString()`, ou seja, o dia UTC.

  **Como ficou (reverberar):**
  - `core/tz.py` ganhou `local_date`, `tenant_today(tz, *, now=)`, `format_datetime_br` e `format_date_br` — **puras, com relógio injetável**, mesma disciplina de `core/scheduling.py`.
  - `settings/service.py` ganhou os resolvedores: `tenant_timezone(db)` (sessão RLS), `timezone_of(db, tenant_id)` (rotas de auth, que rodam em sessão crua) e **`hoje_do_tenant(db)` — a única âncora de "hoje" do sistema**. Cada `_today()` de módulo delega para ela. ⚠️ **`timezone_of` não funcionava de verdade até o PR #91** — ver a correção logo abaixo.
  - `is_overdue` (payables **e** receivables) passou a exigir `today` como parâmetro **obrigatório**. Um default que lê o relógio é exatamente por onde o fuso errado volta.
  - `TenantOut` carrega `timezone`: a sessão entrega o fuso ao frontend. **Não** use `GET /settings/profile` para isso — aquela rota exige o módulo `settings`, que nem todo usuário tem.
  - Frontend: `lib/datetime.ts` é a ÚNICA porta de formatação, e separa as duas espécies de data — **instante** (`formatDateTime`/`formatDate`/`formatTime`, convertem de fuso) e **data de calendário** (`formatDay`, puramente textual, nunca constrói `Date`). `useFuso()` (em `store/auth.tsx`) dá o fuso e, ao contrário de `useAuth`, **não lança** fora do provider: fuso é exibição, e derrubar a tela por causa dele seria uma troca ruim.
  - **Lição (reverberar): `isoformat()` em texto que um humano lê é bug, não estilo.** Para persistir/trafegar, ISO em UTC; para exibir, a borda converte. E "hoje" **nunca** é `datetime.now(UTC).date()` — é `hoje_do_tenant(db)`.
  - Gates: `tests/test_fuso_do_tenant.py` (backend), `src/lib/datetime.test.ts` + o teste do `?day=` em `CockpitPage.test.tsx` (frontend).
- **[CORRIGIDO 2026-08-07, PR #91] O fuso da sessão era SEMPRE o padrão — a correção acima estava pela metade.** `/auth/login`, `/auth/register`, `/auth/me` e `/auth/change-password` rodam em sessão **crua** (`get_db`, sem a GUC de tenant) e `timezone_of` lia `tenant_profiles`, que tem `FORCE ROW LEVEL SECURITY` desde a 0022. **A policy filtra o SELECT inteiro:** o `WHERE tenant_id = ...` explícito não ajudava, porque o problema nunca foi *qual* linha trazer e sim *conseguir enxergar alguma*. Todo tenant recebia `America/Sao_Paulo`, e o `useFuso()` do frontend inteiro sai desse valor. É a mesma armadilha do backfill da `0068` ("a RLS filtra SELECT também"), do outro lado do produto.
  - **O fuso mudou de casa (migration 0073): mora em `tenants.timezone`**, tabela GLOBAL sem RLS que as rotas de auth já leem naturalmente. Fuso é **identidade do tenant**, não brand kit. Elimina a classe do problema em vez de contorná-la com uma sessão extra por login ou um bypass de RLS (as duas alternativas consideradas — a segunda foge da decisão de que a RLS é a garantia única).
  - ⚠️ **`tenant_profiles.timezone` NÃO foi dropada e está CONGELADA** (um ciclo de conferência, como a 0066 fez). Quem a ler recebe o valor do dia da migration, não o que o dono configurou depois. Use `tenant_timezone(db)` (sessão de tenant) ou `timezone_of(db, tenant_id)` (sessão crua) — **nunca** `get_profile(...).timezone`. Gate: `tests/test_settings_timezone.py::test_ninguem_le_mais_o_fuso_do_perfil` (varredura AST, validado por mutação). Dropar a coluna numa migration posterior.
  - ⚠️ **`tenants` não tem RLS**, então toda leitura precisa de filtro explícito por id — mesma exceção documentada de `users`. Gate: `test_auth_timezone_rls.py::test_o_fuso_NAO_atravessa_tenants`. Trocar um bug de fuso por um vazamento entre tenants seria infinitamente pior.
  - **O achado que valeu mais que o bug: TRÊS consumidores liam a coluna do perfil** e não apareceram na investigação inicial — Agenda (evento de dia inteiro), Cockpit (janela do dia) e validade das notificações. Corrigir só o `timezone_of` teria consertado o login e **quebrado os três em silêncio**: a coluna existe, tem valor, a leitura funciona, e nenhum teste protestaria. **Regra (reverberar): ao mover um dado de casa, faça o grep dos leitores ANTES de assumir que a mudança é local — e deixe um gate mecânico no lugar.**
  - **Por que ninguém tinha notado:** a tela `/config` **não tem seletor de fuso**. O campo existe na API e valida, mas nenhum componente o escreve — então todo tenant estava no default, que é justamente o valor que o código quebrado devolvia. Era armadilha armada para quem fosse adicionar o seletor: o `PATCH` responderia com o valor novo e o login continuaria entregando São Paulo.
  - **Só o Postgres reproduz** (o SQLite dos testes não exercita RLS): o gate de regressão é `tests/test_auth_timezone_rls.py`, `rls_e2e`, com controle positivo em cada asserção.
- **[CORRIGIDO] Agenda não mostrava cobranças/contas a pagar (bug de fuso).** Eventos de dia inteiro (cobranca_receber/cobranca_pagar/prazo) são gravados à **meia-noite UTC** da data de vencimento. A Agenda casava o evento ao dia com `new Date(starts_at)` (horário LOCAL) → em fuso negativo (Brasil UTC-3) o evento "voltava" um dia e, nas bordas do mês, caía fora do range → sumia. Fix (frontend, `AgendaPage.tsx`): eventos all-day casam por **data de calendário** (`starts_at.slice(0,10)` = data UTC) e o range da busca usa fronteiras **UTC-date** (`${ymd}T00:00:00Z`), não local→UTC. Idem para a cor "atrasado". Backend sempre injetou o evento corretamente (validado). **Lição (reverberar): toda data de negócio que vira evento all-day deve ser comparada por data de calendário, nunca por horário local.**
- **[CRÍTICO, CORRIGIDO] RLS perdia o tenant no refresh pós-commit (afetava TODOS os módulos).** A `Session` ligada à Engine devolvia a conexão ao pool no `commit()`; o `db.refresh()` seguinte pegava outra conexão sem a GUC `app.current_tenant_id` → RLS escondia a linha → 500 "Could not refresh instance". Funcionava só quando o pool reusava a mesma conexão. **Fix:** `tenant_session` agora prende a Session a UMA conexão dedicada (`engine.connect()`) por todo o request; o refresh pós-commit usa a mesma conexão (GUC setada). Validado: criar em tenant novo OK em todos os módulos + isolamento entre tenants intacto. Regra: qualquer novo helper de sessão de tenant DEVE usar conexão dedicada, nunca a Engine direto.

## 6.1 Dívida técnica / TODO de segurança (de revisão QA — endereçar antes de produção)
- **Enumeração de e-mail no /register:** retorna 409 "e-mail já cadastrado" (UX comum em signup, mas revela existência). Reavaliar quando houver fluxo de e-mail/confirmação.
- **Validação de CPF/CNPJ:** ~~hoje só valida tamanho; falta dígito verificador~~ — **desatualizado, corrigido em 2026-07-30.** `apps/api/app/core/validators.py` **já valida dígito verificador** e normaliza, e é usado por `auth`, `crm`, `contracts`, `platform` e `bank`. O que resta em aberto é só a **unicidade por tenant**. (Esta entrada induziu a Story 8.2 a especificar validação fraca; o @dev conferiu o código, viu que a premissa era falsa e seguiu o padrão real — comportamento correto: **quando uma instrução se apoiar em premissa que você verificar ser falsa, siga o repo e documente**.)
- 🔴 **Anonimizador sem NER — nome livre chega CRU ao Claude (Regra de Ouro nº 2).** `core/anonymizer.py` é 100% regex e mascara só PII **estrutural** (CPF/CNPJ/e-mail/telefone/cartão). Nome próprio, razão social, título de contrato e nome de aplicação passam intactos. Atinge **dois módulos em produção**: o **Jurídico** (peças sob segredo de justiça) e o **Diagnóstico Financeiro** (`_margin_signals` manda `contract.title`; `_investment_signals` manda `inv.name`). Risco residual **aceito pelo fundador em 2026-07-11**, com gate: não expor com `ANTHROPIC_API_KEY` real em produção sem hardening (story própria cobrindo os dois módulos) ou aceite adicional por escrito. Cuidado ao corrigir: estender para nomes tem risco de **over-masking** quebrar o Jurídico. Ver `docs/stories/5.8.story.md`.
- **Hardening da tabela `users` (global):** não tem RLS (login por e-mail é global). Garantir que módulos de negócio NUNCA consultem `users` via `get_db` sem filtro de tenant.
- **Idle timeout LGPD (30min):** configurado mas não implementado (JWT é stateless, expira em 7 dias). Implementar tracking de atividade / refresh curto quando o frontend de auth entrar.
- **Truncagem bcrypt por bytes (72):** pode cortar caractere multibyte; documentado, aceitável.
- **Geração de tipos:** `shared-types` é mantido à mão espelhando os schemas. Avaliar gerar TS a partir do OpenAPI do FastAPI para eliminar divergência.
- **Rastro da IA não propagado (Agenda):** `CurrentUser.is_ai` é placeholder fixo `False` — nenhum evento é criado pela IA ainda (não há endpoint/ator de IA). Quando a camada de ações da IA existir, propagar `is_ai` em create/update/cancel/reschedule (Regra de Ouro nº 3).
- **Semântica de `all_day` (Agenda):** hoje o campo é só armazenado; o conflito usa starts_at/ends_at crus. Definir normalização (ex.: `[00:00, 24:00)` no fuso do tenant) quando a UI de calendário entrar.
- **Teste de isolamento cross-tenant:** RLS é Postgres-only; os testes unitários usam SQLite e não a exercem. ✅ Validado manualmente via e2e no Docker (Postgres real). TODO: automatizar com testcontainers no CI.
- **Drift de versão venv↔produção:** o venv local tinha FastAPI mais novo que o pinado (0.115.5), o que escondeu um erro de rota 204 que só quebrou no container. Agora alinhado. **Antes de confiar só nos testes locais, rode a stack Docker** (ou recrie o venv com `pip install -r requirements.txt`). Considerar CI que rode os testes na imagem.
- **Como rodar/validar localmente:** `docker compose --env-file .env -f infra/docker-compose.yml up -d --build` → web :5173, API :8000/docs. **`--env-file .env` é obrigatório** (achado 2026-07-12): com só `-f infra/docker-compose.yml`, o Compose v5 resolve o `.env` relativo ao diretório do PRIMEIRO `-f` (`infra/`), não à raiz do repo, e ignora silenciosamente vars da raiz sem erro nenhum (afeta `ANTHROPIC_API_KEY`/`JWT_SECRET`, que seguem via `${VAR:-default}` em `environment:`). Testes: `cd apps/api && source .venv/bin/activate && pytest`. SSD exFAT: rodar `find . -name '._*' -delete` antes de builds Docker (AppleDouble quebra o sender).
  **Credenciais reais (SMTP/gateway de pagamento) usam `env_file: ../.env` no `docker-compose.yml`** (não `environment: ${VAR}`) porque o Compose interpola `${...}` inclusive DENTRO do valor final de uma variável — se o valor tiver `$` literal (ex.: API key da Asaas, formato `$aact_...`), o Compose tenta expandir isso como referência de outra variável e o valor vira string vazia, silenciosamente (sem erro, só um warning fácil de não notar: `"X variable is not set. Defaulting to a blank string"`). Regra: qualquer segredo real com `$` no valor precisa estar escapado como `$$` no `.env`, OU (melhor) chegar ao container só via `env_file:` (lido cru, sem interpolação) — nunca via `${VAR}` em `environment:`. Mesmo padrão já usado em `docker-compose.prod.yml` (`env_file: .env.prod`).
  **Logging da API (achado 2026-07-12):** `app/main.py` não tinha `logging.basicConfig()` (ao contrário de `app/worker.py`, que já tinha) — o root logger ficava sem handler, então `logger.info`/`logger.exception` de `core/email.py`, `core/whatsapp.py`, `core/payment_gateway.py` etc. nunca apareciam em `docker logs`, mesmo em caminhos de sucesso ou erro. Corrigido — se voltar a acontecer (logs "somem"), é o primeiro lugar a checar.

> **Decisão de arquitetura (mantida):** seguimos RLS como ÚNICA garantia de isolamento — o código NÃO adiciona filtro manual de tenant (Regra de Ouro nº 1). Defesa-em-profundidade (filtro explícito redundante) foi considerada e rejeitada para não criar o padrão "algumas queries filtram, outras não" (onde esquecer uma vira vazamento). A RLS é fail-closed inclusive em escrita (WITH CHECK). Revisitar via ADR se necessário.

> Já corrigidos no módulo Agenda (revisão QA): validação de status/priority no update; guarda de transição (não cancelar/remarcar evento terminal); paginação obrigatória em list; `amount_cents >= 0`; duração positiva (rejeita zero); coerção de datetime naive→UTC.

**CRM & Kanban — pendências (de revisão QA):**
- **Unicidade de e-mail de cliente:** não há constraint; mesmo e-mail repetível no tenant (decisão de produto — confirmar se deve deduplicar).
- **`StageUpdate` não edita `is_won`/`is_lost`:** estágio criado com flag errada precisa ser recriado. Adicionar quando houver UI de configuração do funil.
- **Múltiplos estágios `is_won`/`is_lost`:** permitido; o consumidor do evento `crm.client.moved` deve tolerar. Avaliar regra de no máx. 1 de cada.
- **Filtro por tag carrega em memória:** feito em Python p/ portabilidade; trocar por operador JSON do Postgres (`tags @> [tag]`) em escala.
- **Validação de CPF (`document`):** reutiliza a dívida global (sem dígito verificador).

**Super Admin — pendências (de revisão QA):**
- **Log de exclusão (LGPD):** o delete de conta purga também `audit_entries` do tenant — não sobra registro da própria exclusão. Criar um log de plataforma (fora do tenant) da operação destrutiva.
- **Inconsistência de id:** `PATCH /admin/accounts/{user_id}` (id de usuário) vs `DELETE /admin/accounts/{tenant_id}` (id de tenant). Documentado; alinhar quando houver UI de sub-usuários.
- **Forçar troca de senha no 1º login** do super admin (hoje a senha semeada vale até ser trocada manualmente).

> Já corrigidos no Super Admin (revisão QA): guarda de produção p/ senha default do admin; delete ATÔMICO (transação única, sem conta-zumbi); purga de tabelas **dinâmica** (descobre subclasses de TenantMixin — módulos futuros purgados automaticamente); `WHERE tenant_id` explícito na purga (defesa-em-profundidade); `require_platform_admin` revalida no banco (não confia no claim por 7 dias); slug "platform" reservado; guard de exclusão checa qualquer admin no tenant (não só o owner).

**Cockpit — pendência (de revisão QA):**
- ~~**Janela do dia ancorada em meia-noite UTC**, não no fuso do tenant.~~ — **corrigido em 2026-08-05.** A janela já usava `day_window_utc(day, profile.timezone)`; o que faltava era o `day` **default**, que vinha de `datetime.now(UTC).date()` no backend e de `new Date().toISOString()` no frontend. Ambos agora são o dia do tenant. Ver §6.0.

> Já corrigidos no Cockpit (revisão QA): removido efeito colateral de escrita (GET não semeia mais estágios); `today_count` via `COUNT(*)` real (não capado em 500); cancelados fora da contagem; críticos concluídos (`done`) fora do alerta; `day` malformado → 422 (tipado como `date`); CRM agregado por `GROUP BY` (não carrega todos os clientes).

> Já corrigidos no módulo CRM (revisão QA): barramento `core/events.emit` isola exceções de assinantes (não derruba o chamador pós-commit); race de seed de estágios fechada com `UNIQUE(tenant_id, name)` + retry; `create_stage` duplicado → 409; FK `RESTRICT` (impede card órfão sumir do board); filtro por tag agora ordenado/determinístico; limites de tags + birthdate não-futura. (Bug pego por teste: router não capturava `CrmError` no create_stage.)

> Já corrigidos na fundação: guarda de boot p/ JWT_SECRET fraco em produção; RLS fail-closed (valida tenant_id); IntegrityError→409 no register (race); /me revalida is_active e não reemite token; e-mail case-insensitive; alinhamento de `created_at`/`role` com shared-types.

## Infra: o Caddyfile parou de ser tudo-ou-nada (issue #151, 2026-08-20)

**O parse do Caddyfile é ALL-OR-NOTHING, e o `.env.prod.example` prometia o contrário.** O bloco
wildcard usa `dns cloudflare {$CLOUDFLARE_API_TOKEN}`; com o token vazio o Caddy recusa o arquivo
**INTEIRO** (`missing API token`) e **nem o domínio único sobe**, com o certificado dele intacto em
disco. O comentário do template dizia *"vazio = wildcard não emite o certificado (domínio único
segue normal)"* — uma degradação graciosa que **não existia**. Derrubou a produção por ~40 min em
2026-08-20, e o contorno tinha sido um Caddyfile local não versionado, que some no primeiro
`git pull`.

- [x] **`infra/Caddyfile` guarda só o que SEMPRE funciona** (domínio único, HTTP-01) e termina em
  `import /etc/caddy/conf.d/*.caddy`. Os blocos que dependem de configuração externa mudaram para
  `infra/caddy/optional/` — `wildcard.caddy` e `monitor.caddy`.
- [x] **A ativação é por ENV, nunca por arquivo criado à mão no servidor.** `infra/caddy/entrypoint.sh`
  copia para `conf.d/` só o que a env pede: wildcard exige `CLOUDFLARE_API_TOKEN` **e**
  `ROOT_DOMAIN` (sem o segundo o endereço vira `*.`, inválido); monitor exige
  `MONITORING_ENABLED=true`. **A opção 1 da issue, ao pé da letra, pedia que o operador criasse os
  arquivos** — seria trocar esta armadilha pela classe que custou os 40 minutos: config que vive
  só na máquina, invisível a qualquer leitura do repo.
  - O entrypoint **apaga e recria** `conf.d/` a cada arranque (recriar container não pode herdar
    bloco de antes) e **anuncia em log** o que ligou e o que não ligou. Desligar em silêncio é como
    o defeito irmão do `.env` sobreviveu a um deploy inteiro.
  - `caddy:2-alpine` tem `ENTRYPOINT` **null** e o `CMD` completo, então o script recebe o comando
    oficial como `"$@"` e faz `exec "$@"` — nada da imagem base é reescrito.
- ⚠️ **Glob de `import` sem correspondência é NO-OP, e isso foi MEDIDO, não suposto.**
  `caddy validate` com `conf.d` vazio devolve `Valid configuration` e um `warn` (*"No files matching
  import glob pattern"*). É esse fato que torna a degradação real em vez de documental — e o repo
  já pagou seis vezes por supor comportamento de terceiro (§WhatsApp Evolution).
- **Validado com o binário real, na imagem com o plugin**, em cinco cenários: sem token · token +
  `ROOT_DOMAIN` (wildcard entra) · token **sem** `ROOT_DOMAIN` (guarda) · só `ROOT_DOMAIN` ·
  `MONITORING_ENABLED=true`. Os cinco: `Valid configuration`. **Controle positivo:** alimentar o
  formato ANTIGO (wildcard inline) com token vazio reproduz o erro de produção palavra por palavra.
- ⚠️ **`ROOT_DOMAIN` pode ser domínio-PAI de `DOMAIN`, e aí o wildcard COBRE o domínio único.** Em
  produção `DOMAIN=e1p.criativaeduca.com.br` e `ROOT_DOMAIN=criativaeduca.com.br`: com um token
  inválido, o principal deixa de receber certificado mesmo tendo o dele em disco. Um placeholder
  com formato válido (40 chars) **passa** na validação do plugin e não salva — medido.
- [x] **Gate de texto** (`tests/test_caddyfile_blocos_opcionais.py`, 5 asserções): o arquivo base não
  pode conter diretiva que exija config externa, precisa ter o `import`, e **todo arquivo em
  `optional/` precisa de um ramo no entrypoint** — bloco versionado que nenhuma env alcança é falha
  silenciosa perfeita, a família da `capabilities.py` sem consumidor. Com controle positivo, para o
  gate não passar por vacuidade se alguém apagar os dois arquivos. Provado por mutação: devolver o
  wildcard ao arquivo base deixa o gate **vermelho**.
  - ⚠️ **Ele roda no job `cross-tenant-rls`, NÃO no `test-in-prod-image`, e isso não é arbitrário.**
    Aquele job roda a suíte **dentro da imagem da API**, onde só `apps/api` foi copiado: `infra/`
    não existe lá. Na primeira versão o teste resolvia a raiz com `parents[3]` fixo e estourou
    `IndexError` **na COLETA** — 66 testes deselecionados, exit 2, o job inteiro vermelho por um
    gate que nem era sobre a API. Hoje ele **sobe procurando `infra/Caddyfile`** e se pula quando
    não o acha.
  - ⚠️ **E o SKIP é REPROVADO no job que importa.** A etapa do `ci.yml` confere `executados >= 1`
    pelo junit, igual à guarda do `rls_e2e`: um gate que se pula sozinho fica verde sem proteger
    nada, e silêncio é indistinguível de aprovação. **Regra que fica: teste que lê arquivo FORA
    de `apps/api` não pode viver só no `pytest` da imagem — ou ele se pula, ou ele quebra a
    coleta.**

~~**Dívida:** a validação de verdade não roda no CI.~~ **FECHADA no dia seguinte, e o preço foi a
produção fora do ar** — ver logo abaixo. Hoje existe `.github/workflows/caddy-image.yml`, com
filtro de caminho: buildar a imagem custa ~2 min de `xcaddy` e só se paga quando `infra/caddy/**`
ou `infra/Caddyfile` mudam.

#### O container que sobe, sai com 0, e reinicia para sempre (2026-08-21)

**Declarar `ENTRYPOINT` num Dockerfile ZERA o `CMD` herdado da imagem base.** Medido com
`docker inspect`: `caddy:2-alpine` tem `CMD=["caddy","run",…]`, e a imagem do PR #170 ficou com
**`CMD=null`**. O entrypoint rodava, imprimia as duas linhas de diagnóstico, chegava no
`exec "$@"` **sem argumento nenhum**, e o script terminava. Exit **0**. O `restart: always`
reiniciava, e o ciclo não aparecia como falha em lugar nenhum — `docker ps` dizia
`Restarting (0)` e a porta 443 recusava conexão.

- ⚠️ **Os cinco cenários validados no #170 NÃO pegavam isto, e o motivo é a lição.** Todos eles
  rodavam a imagem passando um comando explícito (`sh -c 'cat > …; caddy validate …'`) — e o
  comando explícito **fornecia o `"$@"` que faltava**. O compose roda a imagem **sem argumentos**,
  e esse era o único caminho nunca exercitado. **Testar que a config adapta não é testar que o
  container SOBE**: é a família do `toContain("flex-wrap")` do §5.1, agora em Docker.
- ⚠️ **E o comentário do Dockerfile afirmava o contrário, sem código atrás** (*"esse CMD chega ao
  script como `$@`"*) — a classe de defeito nº 1 do Epic 8, o documento que afirma sobre a camada
  de baixo e desliga quem viria conferir. Hoje o Dockerfile declara `CMD` explicitamente, com o
  aviso ao lado.
- [x] **Duas camadas, porque uma só volta a falhar em silêncio:** o `CMD` explícito **e** uma guarda
  no entrypoint que **recusa (exit 1)** quando `$#` é zero, dizendo o que fazer. Sair com 0 é o
  pior desfecho possível aqui — transforma erro de build em loop que ninguém vê.
- [x] **`caddy-image.yml` roda o container do jeito que o compose roda** (`docker run -d`, sem
  argumento) e reprova se ele não ficar `running`; mais o controle positivo da guarda e os dois
  modos de config. **Provado localmente antes de subir:** a imagem antiga sai com `exit=0`, a nova
  fica `running`.
- [x] **Gate de texto** no mesmo arquivo do #170: Dockerfile que declara `ENTRYPOINT` **precisa**
  declarar `CMD`. Barato, roda em toda mudança, e morre sob mutação (tirar o `CMD` deixa vermelho).
- **Restauração do incidente:** `command:` no `docker-compose.override.yml` da instância — a
  imagem estava boa, faltava só o comando, então `up -d` **sem `--build`** devolveu o site em
  segundos. ⚠️ **Esse `command:` precisa SAIR do override** depois deste PR chegar em produção;
  enquanto estiver lá ele mascara uma eventual reincidência.
- **Dívida:** o `docker-compose.override.yml` da AWS pode perder o bloco `caddy:` depois que isto
  for deployado — mas só **depois**, e conferindo que o wildcard segue desligado lá
  (`CLOUDFLARE_API_TOKEN` vazio de propósito). Enquanto o override existir, ele vence: monta o
  `Caddyfile.single`, que não tem o `import` e portanto ignora os opcionais — **seguro, só redundante**.

## 7. Materiais de referência (fora do repo)
- Spec mestre: `/Volumes/Extreme SSD/2026_e1p/Configuração do software.docx`
- Design Figma exportado: `/Volumes/Extreme SSD/2026_Downloads de JUNHO/crm_export/` (PNGs do "Portal")
- App jurídico existente (a migrar): `/Users/tiagoledesmamariano/lex-intelligentia-app`

## 8. Convenções
- Idioma do produto e comentários de domínio: **PT-BR**. Código/identificadores: inglês.
- Commits: Conventional Commits (`feat:`, `fix:`, `chore:`...). Branch a partir de `main`.
- Um módulo de negócio = uma pasta em `apps/api/app/modules/` + uma em `apps/web/src/features/`.

## 9. Como rodar local (e troubleshooting) — IMPORTANTE
**Topologia de dev:** o front local é o **Vite dev server** (`pnpm --filter @e1p/web dev`) em **http://localhost:5173**, que faz **proxy de `/api` → `:8000`** (ver `apps/web/vite.config.ts`). A **API** é o container `infra-api-1` em `:8000` e o **Postgres** é `infra-postgres-1` em `:5432`.
- O **container web do Docker** (`infra-web-1`) é o **build de PRODUÇÃO** (nginx estático, SEM proxy `/api` — `apps/web/nginx.conf`) e agora expõe a **porta 8081** (não a 5173), justamente para NUNCA disputar a porta do Vite. Se você acessar o 8081 as chamadas `/api` não funcionam (é estático); use-o só para inspecionar o build. **Histórico:** ele ficava em `5173:80` com `restart: unless-stopped` e voltava sozinho após reinícios do Docker, roubando a 5173 do Vite → a app "caía" (todo `/api` voltava HTML). Corrigido movendo p/ 8081.
- **Subir o stack:** `docker start infra-postgres-1 infra-api-1` (reusa containers existentes) + `pnpm --filter @e1p/web dev`. A API roda `alembic upgrade head` + seed no boot, então leva alguns segundos até o `/health` responder.
- **Bug do Docker Desktop no macOS com SSD externo + espaço no nome** ("Extreme SSD"): **recriar** containers que tenham **bind mount** desse caminho falha com `error while creating mount source path ... mkdir /host_mnt/Volumes/Extreme SSD: file exists`. Por isso o bind mount `./docker/initdb` do Postgres está **desativado (comentado)** no `infra/docker-compose.yml` — ele só servia no 1º boot (o papel RLS `e1p_app` já vive no volume nomeado `infra_postgres_data`). **Evite o botão "Start" do Docker Desktop** (recria containers e reintroduz o bug); prefira `docker start <nome>` (não recria) ou `docker compose up -d postgres api`. Dados ficam no volume nomeado — recriar o container do Postgres NÃO os apaga (só `down -v` apagaria).
  **Máquina nova / volume `infra_postgres_data` genuinamente vazio (achado 2026-07-12):** como o bind mount está desativado, o papel `e1p_app` NUNCA é criado automaticamente no 1º boot — a API sobe mas toda query falha com `password authentication failed for user "e1p_app"`. Rode uma vez, manualmente, o conteúdo de `infra/docker/initdb/01-rls-enforce.sql` contra o Postgres (`docker exec infra-postgres-1 psql -U e1puser -d e1pdb -c "CREATE ROLE e1p_app WITH LOGIN PASSWORD 'e1ppass' NOSUPERUSER; GRANT ALL PRIVILEGES ON DATABASE e1pdb TO e1p_app; GRANT ALL ON SCHEMA public TO e1p_app;"`), depois `docker restart infra-api-1`.
- A imagem do `infra-api-1` é estática (sem bind mount do código): mudanças no backend exigem **rebuild** (`docker compose build api`) — ou, para teste rápido, `docker cp` dos arquivos para dentro do container (some no rebuild).
