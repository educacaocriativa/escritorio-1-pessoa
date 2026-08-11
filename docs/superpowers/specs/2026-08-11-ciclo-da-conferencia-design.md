# O ciclo da conferência — o instrumento que torna `|divergencia_cents|` legível

> Epic 8, frente de instrumentação. Sai depois da Onda 3 (PR #104) e **antes** de qualquer leitura
> do gate. Não é uma onda: é o que falta para as ondas seguintes poderem ser decididas.

## 1. Por que existe

Com P1 e P2 fechados na Onda 2, P3 na 2b-i e P4 na Onda 3, **a obstrução para ler
`|divergencia_cents|` deixou de ser de código**. Passou a ser de dado: a produção foi zerada em
05/08/2026 e a métrica precisa de um ciclo de uso real — conta cadastrada, contas pagas informando
a conta, saldo do banco declarado.

O produto hoje sinaliza essa pré-condição **pela ausência de notas**: `reconciliation_report`
acrescenta uma nota quando P1+P2 ≠ 0 e outra quando P3 ≠ 0, e zero termo não-zero produz zero nota.
O sinal de *"agora pode ler"* é, literalmente, **silêncio** — e silêncio é indistinguível de *"não
medi"*. É a mesma forma do erro de 2026-07-30, uma camada acima: um artefato de decisão cujo único
consumidor é um humano num ciclo futuro, e humano não levanta `TypeError`.

Esta frente constrói o instrumento e **para**. Ela não mede, não conta até três e não decide a Onda 4.

## 2. O erro que esta frente existe para impedir

O §3.1.1 do PRD e a correção de 2026-07-30 em `docs/architecture/controle-bancario-design.md`
registram o caso: a Onda 1 media a divergência com o razão bancário vazio, e o número — grande e de
aparência sólida — teria argumentado pela liberação da onda mais cara do épico. **A regra de método
que ficou:** antes de usar um número como gate, pergunte o que ele mede quando o sistema está
incompleto.

A armadilha desta frente é a **irmã simétrica** daquela. Não é mais a incompletude do sistema: é a
**vacuidade da janela**. Um mês em que o dono não pagou nada tem P1..P4 zerados, todas as contas
avaliadas e divergência R$ 0,00. Um instrumento que dissesse *"ciclo legível"* ali estaria
afirmando, com número e verde, sobre um mês em que nada aconteceu. E o sistema **não consegue**
distinguir *conta dormente* de *tudo aconteceu e nada foi registrado* — está escrito no §4 da seção
da Onda 2 do `CLAUDE.md`.

**A saída não é recusar a janela vazia: é nunca deixar o número aparecer sem o denominador que o
produziu.** Mesmo princípio do consolidado que nunca existe sem a decomposição por conta (F3).

## 3. O ciclo

**Um ciclo é um mês de calendário no fuso do tenant.** `hoje_do_tenant(db)` é a única âncora de
"hoje" do sistema; um ciclo está **fechado** quando `end < hoje`.

Não é janela livre, e isso é decisão, não conveniência: `reconciliation_report` aceita qualquer
`start`/`end`, e um ciclo de fronteira escolhível permitiria selecionar a janela que produz o número
desejado — a régua andando junto com o que ela mede, que é exatamente o que a banda fixa da Regra 7
existe para impedir.

### 3.1 Legibilidade — quatro condições, cada uma com membro e não-membro

> **REGRA DA INSTANCIAÇÃO OBRIGATÓRIA.** Este é um critério de decisão; a regra é obrigatória aqui.
> Cada condição abaixo nasce com um membro **e** um não-membro escritos no mesmo parágrafo.

Um ciclo é **legível** quando as quatro valem na janela dele **e ele está fechado**. O fechamento não
está na lista porque não é condição da janela: é o que separa *ciclo* de *pedaço de mês*, e um mês
pela metade não tem o que declarar. `legivel` é `False` para ciclo em curso sem exceção — um `True`
provisório que vira `False` no dia seguinte é pior que um `False` honesto.

**(a) Existe ao menos uma conta bancária ativa.**
Membro: um tenant com o Itaú PJ cadastrado. Não-membro: o tenant no dia seguinte ao reset de 05/08,
sem conta nenhuma.
*Por que não é redundante:* sem conta, `contas == []`, `contas_sem_checkpoint == 0` e os três
contadores dão zero. O ciclo passaria em (b) e (c) **por vacuidade**, e o e1p diria "legível" sobre
nada. É a mesma família do 🟢 sobre razão vazio que a Story 8.20 desfez.

**(b) Toda conta ativa foi avaliada — `contas_sem_checkpoint == 0`.**
Membro: três contas, cada uma com saldo declarado num dia do mês posterior à própria abertura.
Não-membro: as mesmas três, com a Poupança BB sem saldo declarado no mês — o total já se declara
parcial (`_note_total_parcial`), e um ciclo cujo total não cobre todas as contas não decide nada.

**(c) Os quatro termos da pré-condição estão zerados.**
P1+P2 por `lancamentos_sem_conta_informada`, P3 por `rendimentos_sem_perna_bancaria`, ambos já no
relatório. P4 pela condição (d).
Membro: um mês em que toda baixa de Contas a Pagar informou a conta e todo recebimento fora do
trilho também. Não-membro: um mês com uma baixa legada corrigida com data retroativa mas sem conta —
o contador a pega e o ciclo não fecha.

**(d) A janela começa em ou depois de `PRIMEIRO_CICLO_MEDIVEL`.**
Membro: setembro/2026. Não-membro: julho/2026.
*Por que existe:* `TermosDoGate` **não conta P4**, e a justificativa escrita em `ConferenciaReport` e
em `main.py` — *"o payout só marca a solicitação como sacada"* — **morreu com a Onda 3**. A população
continua vazia, mas por construção nova (409 sem conta principal + perna bancária na mesma
transação), e só a partir do deploy. Numa janela anterior existem saques legados sem perna bancária
que o relatório reporta como **zero por omissão** — e *"zero por ausência de medição não é zero"* é a
frase que o próprio `_probe_termos_do_gate` usa para se recusar a devolver zeros.

### 3.2 `PRIMEIRO_CICLO_MEDIVEL`

Constante de módulo com o motivo escrito ao lado, no molde de `CORTE_AUTORIA`
(`vima/absences.py:47`) — a mesma forma de "a partir daqui o dado é confiável, antes não".

Valor: **o primeiro dia do primeiro mês inteiramente posterior ao deploy da Onda 3 em produção.**
Provisório: `date(2026, 9, 1)`, válido se a Onda 3 subir antes de 01/09.

⚠️ **É o único ponto desta frente que depende de um fato fora do repositório**, e ele erra em
silêncio: cravar uma data cedo demais faz o e1p declarar legível um ciclo cujo P4 nunca foi medido —
a leitura errada que já custou uma decisão de produto neste épico. Duas guardas:
- teste que reprova `PRIMEIRO_CICLO_MEDIVEL` anterior à data do merge da Onda 3 (a data do commit é
  um fato do repositório; o deploy não é, mas o merge é um piso válido);
- item explícito no runbook de deploy, junto do rebuild dos serviços.

### 3.3 O volume — o denominador que viaja junto

Dois campos novos em `ConferenciaConta`:

- `movimentos_no_periodo: int`
- `valor_movimentado_cents: int` — soma de `|amount_cents|`

Sobre `bank_transactions` com `posted_at` em `[start, end]` e **o mesmo filtro `status <> 'ignored'`
do saldo derivado** — quem consome o saldo não refiltra, e uma contagem que incluísse os ignorados
diria que houve movimento onde o saldo não viu nenhum. Query **em lote**, no padrão que
`_ignored_counts` já estabeleceu neste arquivo: a janela é a mesma para todas as contas, então não há
o risco do AC4b (nada é comparado com nada aqui).

**Por conta, e não só no consolidado**, pela razão F3: três contas, duas movimentadas e uma parada,
dão volume total saudável e escondem a conta dormente — exatamente o que a decomposição obrigatória
existe para impedir.

**Considerado e cortado:** decompor o volume em origem-sistema × origem-externa. Responde uma
pergunta que ninguém fez — os dois são o sistema aprendendo, e ambos reduzem a divergência
legitimamente.

### 3.4 O que o volume **não** faz

Ele **não** entra no predicado de legibilidade. Um mínimo de N movimentos seria determinístico e
recusaria o mês dormente — e N seria um número inventado (Artigo IV), e recusar a janela **esconde**
o número dela em vez de qualificá-lo, o inverso do princípio da Onda 0 (*suprimir a afirmação, nunca
o número*). O ciclo dormente aparece, legível, com denominador zero à vista. O zero se lê sozinho.

## 4. ANOTA, NUNCA SUBTRAI

Nenhuma linha desta frente toca `divergencia_cents`, `dentro_da_tolerancia`, `tolerancia_cents`,
`total_divergencia_cents` ou `contas_fora_da_banda`. Tudo é campo novo e leitura nova.

Isto não é observação: é a **Regra 5** com outra roupa. Se a legibilidade do ciclo pudesse alterar ou
ocultar a divergência, o instrumento passaria a corrigir o que mede, a divergência iria a zero por
construção sempre que o sistema soubesse explicar a diferença, e a métrica primária do épico morria.
A legibilidade **qualifica** o número; nunca o altera nem o esconde.

Igualmente intocada: a **banda `max(R$ 50; 0,5%)`**, fixa. Nada aqui a parametriza, a lê de
configuração ou a expõe.

## 5. O contrato de saída

### 5.1 `CicloDaConferencia` (novo, `bank/reconciliation.py`)

```
ano_mes: str                      # "2026-09"
start: date
end: date
fechado: bool                     # end < hoje_do_tenant
legivel: bool                     # (a) ∧ (b) ∧ (c) ∧ (d), e False sempre que not fechado
motivo_nao_legivel: str | None    # qual das quatro falhou, NOMEANDO o que falta
total_divergencia_cents: int | None
contas_avaliadas: int
contas_sem_checkpoint: int
movimentos_no_periodo: int
valor_movimentado_cents: int
```

`legivel` é `False` para ciclo em curso **sem exceção**: um mês pela metade não tem o que declarar, e
um `True` provisório que vira `False` no dia seguinte é pior que um `False` honesto.

`motivo_nao_legivel` **nomeia**, nunca resume: *"a Poupança BB não teve saldo informado neste mês"*,
não *"conferência incompleta"*. É a lição do UX-001 e das notas por conta — um motivo genérico manda
o dono procurar o que já se sabe qual é.

**Quando mais de uma condição falha, a precedência é fixa e é `(d) → (a) → (b) → (c)`**, e a ordem é
pela **acionabilidade**: (d) e (a) não têm ação possível naquele mês (o período é anterior ao corte;
não havia conta cadastrada), então dizer *"falta o saldo da Poupança"* sobre um mês de julho mandaria
o dono a um ato que não resolve. (b) vem antes de (c) porque declarar o saldo é um ato por conta e
corrigir lançamento legado é um ato por lançamento — a frase pede primeiro o barato. Um campo só, uma
frase só: uma lista de motivos aqui reconstruiria o ruído que a Regra 7 existe para evitar.

### 5.2 `GET /bank/reconciliation-cycles`

**Derivado na leitura, nunca gravado.** Roda `reconciliation_report` uma vez por mês, do mês da conta
ativa mais antiga (`min(opening_date)`) até o mês corrente, **teto de 6 meses**.

**Sem conta ativa, a lista sai vazia** — e vazia, não com um ciclo em curso de conteúdo nulo. A tela
diz *"nenhuma conta bancária cadastrada"*, que é a frase verdadeira, e é a mesma que o Diagnóstico já
emite como 🟡 para todos os tenants sem opt-in nem dispensa. Um ciclo em curso montado sobre zero
conta seria a condição (a) violada pela porta dos fundos, na camada de exibição.

*Por que 6:* é o dobro da janela de observação sugerida pelo PRD, o bastante para enxergar
estabilidade. É **teto de exibição**, não regra, e está escrito assim no docstring — o PRD marca "3
ciclos" como `[SUPOSIÇÃO DO @PM]`, e transformá-lo em constante de produto seria codificar suposição.

**A alternativa persistida foi rejeitada por motivo concreto, não por pureza:** um lançamento
retroativo muda legitimamente a leitura de um ciclo passado, e um valor congelado passaria a
discordar do recalculado — segunda verdade sobre a mesma divergência, a forma exata do bug que a
Onda 0 desfez. Também é a Regra 3 do Epic 5 (*análise não escreve*).

**Custo:** 6 relatórios × (1 probe + N contas × 2 queries + 2 batches). Com 3 contas, ~54 queries por
chamada. Aceitável na escala de uma empresa de 1 pessoa, e registrado aqui para não ser descoberto
como surpresa.

## 6. As superfícies

### 6.1 Conferência — a qualificação colada à frase

Uma linha nova **imediatamente abaixo** de `fraseConferencia`, montada por uma função pura irmã
`fraseDoCiclo`, testada, no padrão que `conferencia.ts` já estabelece (a frase não se monta dentro do
`.tsx`).

- em curso: *"Este ciclo fecha em 30/09. Até lá, o e1p ainda não tem como conferir setembro por inteiro."*
- fechado e legível: *"Setembro fechou conferido: 3 contas, 14 movimentos, R$ 18.402,00 movimentados."*
- fechado e não legível: *"Setembro fechou sem o saldo da Poupança BB — sem ele o e1p não consegue conferir o mês inteiro."*

**Colada, e não num bloco no rodapé.** Elemento separado da afirmação que ele qualifica é elemento
que não é lido — o épico pagou dois PRs de campo (#56, #58) por essa exata classe, e a 8.13 escreveu
a regra de co-localização por ancestral comum.

O **histórico** — o consult deliberado — fica **abaixo da tabela por conta**, como `<ul>`, **nunca
`<table>`, com teste que reprova a tabela**. A lição da 2b-ii: em 360px uma tabela de 3 colunas não
cabe, e a saída não é rolar melhor, é não precisar de rolagem. O histórico de saques da Onda 3 já
carrega esse teste; ele se repete aqui.

Cada linha: o mês, o veredito **em frase**, a divergência quando há, **e o volume sempre** —
inclusive zero, com o mesmo peso visual do número, nunca como rodapé. Ciclo anterior a
`PRIMEIRO_CICLO_MEDIVEL` aparece com o motivo dito: *"o saque da Carteira ainda não escrevia
movimento bancário neste período"*. Escondê-lo seria suprimir o número.

**No dia 1 a tela funciona.** Hoje não existe nenhum ciclo fechado — a produção foi zerada em 05/08 e
agosto só fecha em 31/08. A tela diz isso e mostra o ciclo em curso, marcado. Mesma disciplina da
Ausência do Vima, que nasce completa sem backfill.

#### Vocabulário

**Nenhum substantivo novo na tela.** "Legível" é termo de domínio: vive no código, nas docstrings e na
entrada do `CLAUDE.md`, e **não aparece para o dono**. Na tela é frase.

Não é preciosismo — é evitar a terceira cobrança da mesma colisão: `completo` colidiria com a
**completude** do Diagnóstico, e `comparável` já está tomado no nível da conta pela Story 8.20
(*"declarado, porém não comparável"*). A divergência D-6/UX-001 já foi paga duas vezes para separar
sentidos que dividiam a mesma palavra.

Continuam proibidas nesta tela: a string `"no banco"` (pertence à parcela da Projeção, com outro
sentido) e qualquer sinônimo locacional. E a tela **não** escreve "gate", "Onda 4", "métrica" nem
conta até três: ela diz o que é verdade em cada ciclo. A decisão é do dono, com os ciclos lado a lado.

### 6.2 Vima — uma família de Ausência, sem limiar novo

`module="financeiro"`, `kind="financeiro.conferencia.saldo_do_mes"`, sob o `pode_ver(user,
"financeiro")` que já existe (o filtro decide quais **regras rodam**, não quais resultados aparecem).

**Dispara** quando o mês fechado mais recente não tem checkpoint numa conta **ativa**. `dias` = dias
desde o fechamento, e a cadência sai de graça do `_proximo_marco`: `0 → 1 → 2 → 4 → 8 → 16`.

**Sem limiar, e isso é a decisão.** Um limiar exigiria a 8ª pergunta de Calibração
(`test_todo_limiar_tem_pergunta` reprova limiar sem pergunta) e ela seria um número sem evidência —
Artigo IV. A declaração retroativa existe (`reference_date` aceita data passada; redeclarar o mesmo
dia corrige com 200, não 409), então avisar **depois** do fechamento não perde nada: o dono abre o
extrato e informa o saldo de 30/09 no dia 03/10.

**`subject_id = "{account_id}:{YYYY-MM}"`**, e o mês no sujeito não é decoração: com o id da conta
sozinho, o marco do mês anterior sobreviveria à virada, `dias` voltaria a `0` e `_calada` engoliria o
aviso do mês novo. É o silêncio permanente que a correção de 2026-08-09 acabou de desfazer no eixo do
dinheiro.

**Uma por conta, nomeando só o ciclo fechado mais recente.** Lacunas mais antigas vivem na
Conferência: o briefing pede **um ato por vez**, mesma filosofia do "uma pergunta por gancho por dia".

Membro: Itaú PJ ativo, setembro fechado, nenhum checkpoint em setembro.
Não-membro: a Poupança BB **arquivada** (fora de `list_accounts`), e o Itaú PJ cujo saldo de 30/09 já
foi declarado.

`absences.py` passa a importar `bank.models` — permitido: a Regra dos Planos proíbe `bank` alcançar o
plano da plataforma, não o Vima ler o plano do banco. O módulo continua sem ler relógio (`hoje` é
parâmetro), como o gate AST de `test_fuso_do_tenant.py` exige.

## 7. No escopo, porque o resto depende disso

**As duas docstrings vencidas sobre P4** — `ConferenciaReport` e `main.py:154` afirmam que a população
é vazia *"porque o payout só marca a solicitação como sacada"*. A frase descreve um módulo que mudou.
É a classe §1 da Onda 2 (o documento que afirma sobre a camada de baixo, e desliga quem viria
conferir), e a condição (d) se apoia exatamente nela: deixá-la de pé é escrever a próxima armadilha
enquanto se conserta esta.

**O aceite em ~360px, medido, com screenshot** — Vite + `page.route` + `boundingBox`, sem backend, o
caminho que a 2b-ii e a Onda 3 já provaram barato. Esta frente **não** abre a quarta dívida de 360px
da fila (8.13 AC9, 8.21, 2b-i).

**A entrada no `CLAUDE.md`** — AC obrigatório de toda story (§5, passo 4).

## 8. Gates e testes

| Gate | O que reprova | Controle positivo |
|---|---|---|
| `test_legibilidade_exige_conta_ativa` | ciclo legível com `contas == []` | tenant com conta e ciclo legível |
| `test_legibilidade_exige_todas_avaliadas` | legível com `contas_sem_checkpoint > 0` | o mesmo mês com a lacuna preenchida |
| `test_legibilidade_recusa_janela_pre_onda_3` | legível com `start < PRIMEIRO_CICLO_MEDIVEL` | o mês seguinte, legível |
| `test_primeiro_ciclo_medivel_nao_antecede_a_onda_3` | constante cravada antes do merge da Onda 3 | — |
| `test_volume_nao_altera_a_divergencia` | qualquer mudança em divergência/tolerância/total/fora-da-banda | snapshot campo a campo, antes e depois |
| `test_volume_exclui_ignorados` | contar movimento `ignored` | movimento normal, contado |
| `test_ciclo_em_curso_nunca_e_legivel` | `legivel=True` com `fechado=False` | o mesmo mês, depois de fechar |
| `test_historico_do_ciclo_nao_e_tabela` | `<table>` no histórico | `<ul>` presente |
| `test_conferencia_nao_usa_o_rotulo_da_projecao` | a string proibida na tela nova | (o teste irmão já existe em `ConferenciaPage`) |
| `test_ausencia_do_saldo_do_mes_tem_o_mes_no_sujeito` | `subject_id` sem o `YYYY-MM` | dois meses seguidos, os dois ditos |
| `test_nenhum_limiar_novo` | chave nova em `LIMIARES_PADRAO` sem pergunta | (gate existente, herdado) |

O `test_volume_nao_altera_a_divergencia` é o gate central desta frente: ele é a Regra 5 mecanizada
para esta mudança. Congela os campos cuja invariância **é** a garantia e dá controle positivo aos
campos que **devem** mudar — a lição do `test_cockpit_e_carteira_intactos` na Onda 3, onde um teste
que congelava o agregado inteiro reprovou a funcionalidade correta.

## 9. Fora de escopo, declarado

- **SIG-001** (a virada de mês apagando uma conferência recente e bem-sucedida). É **vizinho** — quem
  lê o bloco 4 esbarra nele — e fica de fora pelo mesmo argumento que o manteve fora da 8.16: fundir
  correção de regra existente com regra nova tira do gate a capacidade de julgar qual mudança quebrou
  o quê.
- **Contar P4 de verdade.** A condição (d) compra a honestidade sem cruzar a Regra dos Planos.
- O estouro horizontal de 15px do `AppShell` (`app/AppShell.tsx:209`).
- O índice irmão de `charges.bank_account_id`.
- A unicidade de `bank_accounts.name` por tenant (o débito suspeito casa conta por nome).
- O drift de `packages/shared-types/src/generated.ts`.
- **Medir a divergência e decidir a Onda 4.** Esta frente constrói o instrumento e para.

## 10. Riscos

1. **`PRIMEIRO_CICLO_MEDIVEL` cravado cedo demais** — falha silenciosa, e a pior possível: o e1p
   declara legível um ciclo cujo P4 não foi medido. Mitigado por teste de piso + item de runbook, não
   eliminado.
2. **O dono não declara o saldo mensal** e nenhum ciclo fica legível. A Ausência do Vima é o
   mecanismo; se ela não bastar, o problema é de produto, não de instrumento, e o instrumento vai
   dizê-lo com clareza em vez de fingir um número.
3. **Custo da rota** (~54 queries com 3 contas). Registrado; sem otimização prematura.
4. **A conta arquivada some do histórico.** `list_accounts` esconde arquivadas, então um ciclo passado
   em que ela existia é recalculado sem ela. Divergência do passado pode mudar de valor ao arquivar
   uma conta hoje — consequência aceita do histórico derivado, e o preço de não congelar um número que
   pode legitimamente mudar.
