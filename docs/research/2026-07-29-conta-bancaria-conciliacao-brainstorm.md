# Conta bancária e conciliação no e1p — estudo de brainstorm

> ⚠️ **RECOMENDAÇÃO SUPERADA (2026-07-29).** O founder rejeitou a recomendação B→E→F→G: o alvo certo é **contas a pagar** (não receber), o objetivo é **conferência para achar furos** (não escrituração), e agregadores de Open Finance estão eliminados por restrição de arquitetura ("não podemos contar com serviços de terceiros"). A decisão é **construir**.
> **Vale agora:** [`2026-07-29-controle-bancario-requisitos-e-viabilidade.md`](./2026-07-29-controle-bancario-requisitos-e-viabilidade.md) — requisitos REQ-1..32, viabilidade de OFX banco a banco e transferência entre contas próprias.
> **Este documento permanece** como registro do raciocínio e da análise de código (§2.1 sobre `projection.py:177` segue válida e é pré-requisito).

> **Data:** 2026-07-29
> **Facilitador:** Atlas (@analyst) — sessão estruturada, modo autônomo/YOLO (sem elicitação interativa)
> **Pergunta do fundador (verbatim):** *"quero que agente abra um estudo de brainstorm para ver se a ideia de controlar a conta bancária faz sentido neste tipo de produto, pois vejo que se a pessoa não controlar e não conciliar, pode ser que esqueça de fazer lançamento. Isto faz sentido? Ou temos outra forma de deixar simples e claro a empresa de 1 pessoa só."*
> **Tipo:** estudo/decisão. **Não é** implementação, spec, story ou migration.
> **Regra de honestidade:** todo número é marcado como `[CONFIRMADO]` (com fonte e data) ou `[ESTIMATIVA]` (com a base do palpite). Constitution Art. IV — No Invention.

---

## 0. Resposta curta, antes de tudo

**Sim, o problema é real — mas você diagnosticou o sintoma errado.**

O "lançamento esquecido" existe e degrada os relatórios. Só que, ao ler o código, encontrei algo pior e mais imediato: **a Projeção de Caixa e o Runway do e1p já estão errados hoje, com ZERO lançamentos esquecidos**, porque o `saldo_inicial` é lido de um número que não é — e nunca foi — saldo de caixa. Isso é um bug de semântica, não uma feature faltando, e nenhuma quantidade de conciliação bancária conserta enquanto essa linha existir.

**E conta bancária + conciliação NÃO é a resposta certa agora.** É a resposta de um ERP contábil para um usuário que não é contador. Existe um caminho ~90% mais barato que entrega o mesmo valor de decisão: **um único número de divergência ("faltam R$ X em lançamentos") a partir de um saldo declarado pelo usuário** — sem banco, sem OFX, sem Open Finance, sem conciliar linha a linha.

E há um ângulo que a pergunta não cobriu e que muda a prioridade: **lançamento esquecido não é só um problema de relatório do usuário — é um vazamento de receita da própria e1p** (split de 30% que nunca é retido quando o cliente paga fora do trilho). Detalhes na seção 2.4.

---

## 1. Contexto — o que existe hoje (validado no repositório, não presumido)

### 1.1 O que o e1p já tem

Módulos financeiros em `apps/api/app/modules/`: `wallet/`, `receivables/`, `payables/` (+ `payables/receipts.py`, a bandeja de comprovantes), `chart_of_accounts/`, `cost_centers/`, `investments/`, `financial_intelligence/` (`dre.py`, `profitability.py`, `projection.py`, `engine.py`, `diagnostics.py`, `ai_narrator.py`), `cockpit/`.

Regras duras já fixadas no código:
- Dinheiro sempre em **centavos inteiros** (`BigInteger`).
- **Fluxo de caixa usa `paid_at`; DRE/lucratividade usam `competence_date`. Nunca inverter.** (`apps/api/app/modules/payables/models.py:6-9`)
- Isolamento por **RLS**, nunca filtro manual de `tenant_id`.
- Padrão de integração externa: **adapter + graceful degradation** (`apps/api/app/core/payment_gateway.py`, ADR `docs/decisions/0002-gateway-pagamento.md`).

### 1.2 O que NÃO existe (confirmado por busca em todo `apps/`)

Não há nenhuma entidade de conta bancária, nenhum import de extrato (OFX/CSV/CNAB), nenhum Open Finance/agregador (Pluggy/Belvo/Klavi), nenhuma conciliação. A única ocorrência de "conciliação" fora do módulo jurídico é comentário conceitual em `receivables/service.py:48` e `:693` e a decisão explicitamente reservada ao fundador em `investments/service.py:27-37`.

`wallet.request_payout` (`wallet/service.py:227`) apenas marca `withdrawn` — não existe integração bancária nem KYC. `core/boleto.py` é layout-stub sem registro bancário.

### 1.3 Os três "planos de dinheiro" — e o que está confundido

Este é o vocabulário que o resto do documento usa. Recomendo adotá-lo no projeto: a confusão que gera todos os bugs desta área vem de não ter esses nomes.

| Plano | O que é | Onde vive hoje |
|---|---|---|
| **1. Plano da plataforma** | Dinheiro que passou pelo trilho e1p, com split 40/30/20 aplicado. Estados: `pending` (cartão a liberar) / `available` (liberado, ainda na plataforma) / `withdrawn` (marcado como sacado) | `wallet.transactions` |
| **2. Plano do negócio** | Direitos e obrigações do escritório: o que vou receber, o que devo pagar, classificado por plano de contas, em competência e em caixa | `charges` + `payables` + `chart_accounts` |
| **3. Plano bancário** | O extrato real da conta do advogado. A única verdade sobre quanto dinheiro existe | **NÃO EXISTE no e1p** |

O plano 3 não existe — e o código está usando um número do **plano 1** como se fosse do **plano 3**. É daí que sai a seção 2.

---

## 2. Validação do problema — o dano é real e maior do que a pergunta supôs

### 2.1 Achado #1 (o mais grave): a Projeção de Caixa parte de um saldo que não é caixa

`apps/api/app/modules/financial_intelligence/projection.py:177`

```python
saldo_inicial = int(wallet_service.wallet_summary(db)["available_cents"])
```

E `available_cents` é (`wallet/service.py:171-176, 191`):

```python
def _sum_net(db, status):  # soma net_cents das transações com aquele status
    ...
"available_cents": _sum_net(db, STATUS_AVAILABLE),
```

Ou seja: **a soma do valor líquido de todas as transações que já foram reconhecidas como pagas e ainda não foram marcadas como "sacadas"**. Isso não é o saldo da conta do advogado. É o passivo da plataforma com ele. Duas consequências, ambas ruins, e elas se contradizem:

**(a) Se o usuário nunca clica em "sacar":** `available_cents` acumula *todo* o faturamento líquido histórico e **nunca diminui quando ele paga uma conta** — porque `payables` explicitamente não toca a Carteira (`payables/models.py:4`: *"NÃO mexe na Carteira (é saída, não receita)"*). A projeção então parte de "todo o dinheiro que já entrei na vida" e subtrai apenas as contas **futuras em aberto**. O saldo projetado fica sistematicamente inflado, e o `runway` (`projection.py:202`: `saldo_inicial / burn_rate`) fica absurdamente otimista.

**(b) Se o usuário saca tudo (comportamento esperado — ele quer o dinheiro na conta dele):** `available_cents` vai a zero, a projeção diz saldo inicial R$ 0 e o runway despenca — enquanto o dinheiro está tranquilamente sentado na conta do banco dele.

**Não há configuração de uso em que esse número esteja certo.** Ele oscila entre "inflado demais" e "zerado" conforme o usuário clica ou não num botão que não tem nada a ver com caixa.

O próprio docstring assume a premissa errada com boa fé (`projection.py:12-15`): *"É o dinheiro que já está disponível na Carteira (histórico consolidado)"* — corretíssimo como descrição do plano 1; simplesmente não é o insumo que uma projeção de caixa pede.

> **Isso é um bug, não uma lacuna de feature.** Precede toda esta discussão de conciliação e deve ser corrigido independentemente da decisão sobre conta bancária. Ver Onda 0 na seção 7.

### 2.2 Achado #2: o lançamento esquecido quebra os relatórios de formas assimétricas

Assumindo o cenário do fundador — o advogado paga o contador por Pix e não lança, ou o cliente paga direto na chave Pix pessoal dele:

| Relatório | Arquivo | Como quebra | Direção do erro |
|---|---|---|---|
| **DRE** | `financial_intelligence/dre.py` | Agrega `charges` e `payables` por `chart_account_id` + `competence_date`. Despesa não lançada simplesmente não existe | **Lucro inflado.** Ele acha que sobrou dinheiro que já foi embora |
| **Lucratividade por contrato** | `profitability.py` | Custo direto não lançado não entra na margem de contribuição do contrato | **Margem inflada.** Ele repete a precificação errada no próximo contrato — o dano composta |
| **Projeção de Caixa** | `projection.py:141-147` | Conta a pagar não lançada nunca aparece como saída futura | **Caixa futuro otimista** — exatamente quando ele mais precisa da verdade |
| **Diagnóstico 🟢🟡🔴** | `engine.py` + `diagnostics.py` | Consome margem (5.4), rentabilidade (5.6) e projeção (5.7). Entrada corrompida ⇒ sinal verde falso | **Falso verde.** O pior modo de falha possível: o produto afirma ativamente que está tudo bem |

**Assimetria que importa:** despesa esquecida é muito mais provável que receita esquecida, porque a receita tem um cobrador natural (o webhook do gateway, `receivables/webhook`) e a despesa não tem ninguém do outro lado querendo que ela seja registrada. Logo **o erro tem viés sistemático para "otimista"**. Um relatório com ruído aleatório ainda é útil. Um relatório com viés conhecido numa direção é pior que não ter relatório, porque induz o comportamento errado com confiança.

### 2.3 Achado #3: a cobrança paga fora do trilho fica em aberto para sempre

Decisão do @architect documentada em `projection.py:26-35`: itens vencidos e em aberto contam como caixa esperado **imediato, em todas as janelas**. É a decisão certa para inadimplência real. Mas combinada com "cliente pagou por fora e ninguém deu baixa", ela produz um fantasma permanente: **uma entrada de caixa que nunca vai chegar, contada em 30/60/90 dias, para sempre.** O campo `overdue_inflow_cents` existe justamente para dar transparência disso — mas ele não distingue "cliente caloteiro" de "já pagou, ninguém registrou". São situações opostas e o produto trata igual.

### 2.4 Achado #4 — o que a pergunta não cobriu: isso é vazamento de receita da e1p

O split (40/30/20) só é retido quando a `Transaction` nasce, e a `Transaction` só nasce em `wallet.build_transaction`, chamada apenas por `receivables.mark_paid` (documentado em `investments/service.py:12-15`). Traduzindo:

**Todo real que o cliente paga direto na chave Pix pessoal do advogado é 100% dele e 0% da e1p.**

Não é uma falha de relatório — é o modelo de negócio da plataforma vazando. E o incentivo está invertido: o advogado que quer economizar os 30% tem um caminho trivial, silencioso e sem atrito para isso. Nesse enquadramento, "garantir que todo recebimento passe pelo trilho" deixa de ser higiene contábil do usuário e vira **controle de receita da plataforma**.

Isso reordena as prioridades. Um mecanismo que detecta "entrou dinheiro na conta que o sistema não conhece" tem valor duplo: honestidade do relatório **e** defesa do split. É o argumento mais forte a favor de investir aqui — e não estava na pergunta original.

### 2.5 Quantificando o dano em decisão (não em bug)

Não vou inventar números de mercado. Vou usar a persona que o próprio spawn definiu — advogado autônomo faturando R$ 20–40k/mês — e a aritmética do dano:

- **[ESTIMATIVA]** Base: uma empresa de 1 pessoa desse porte tem tipicamente entre 8 e 20 saídas/mês (pró-labore, contador, aluguel/coworking, OAB, software, energia/internet, correspondente jurídico, custas, marketing). Base do palpite: a estrutura de categorias do próprio `chart_of_accounts` do e1p (CUSTO_DIRETO / DESPESA_FIXA / TRIBUTOS / FINANCEIRO) e o desenho da Fila de Pagamentos, que pressupõe volume de "hoje/7/30 dias" administrável a mão.
- **Aritmética do dano (não é estimativa, é consequência direta):** esquecer **uma única** despesa de R$ 2.000 num mês de R$ 25.000 de receita e R$ 15.000 de custo real muda o lucro reportado de R$ 10.000 para R$ 12.000 — **erro de +20% no lucro**. Numa decisão de "posso contratar um estagiário / posso pegar uma sala?", 20% é a diferença entre certo e errado.
- **Composição:** a distorção não é pontual, é acumulativa em `profitability.py` — a margem errada de um contrato vira a referência de precificação do próximo. O produto ensina o usuário a errar.

### 2.6 Veredito da validação

| Pergunta | Resposta |
|---|---|
| O lançamento esquecido é real? | **Sim** — e com viés sistemático para otimista |
| É material? | **Sim** — 1 despesa esquecida ⇒ ~20% de erro no lucro `[aritmética]`, e a distorção composta via lucratividade por contrato |
| Ele invalida os relatórios? | **Parcialmente.** DRE e Lucratividade degradam proporcionalmente ao que falta. **Projeção e Runway já estão inválidos por outro motivo (§2.1), independente de esquecimento** |
| Conciliação bancária é a resposta? | **Não agora.** É a resposta certa para uma pergunta que o e1p ainda não fez. Ver §5 e §6 |

---

## 3. Técnicas aplicadas — ideias geradas, por técnica

> Seis técnicas de `.aiox-core/product/data/brainstorming-techniques.md`. Cada bloco declara qual técnica gerou quais ideias.

### 3.1 Técnica: First Principles Thinking (#4)

**Pergunta:** "Do que um relatório financeiro precisa para ser confiável? Quais são os fundamentos irredutíveis?"

Decompondo, um número financeiro é confiável se e somente se três propriedades valem:

1. **Completude** — todo evento econômico que aconteceu está registrado. *(É a propriedade que falta no e1p.)*
2. **Correção** — cada evento registrado tem valor, data e classificação certos. *(Parcialmente resolvida: plano de contas + 3 datas + centavos inteiros.)*
3. **Não-duplicação** — nenhum evento está registrado duas vezes. *(Bem resolvida: `FOR UPDATE`, idempotência do webhook, `external_ref` excluído da DRE.)*

**Ideias geradas:**

- **I-1.** O e1p investiu pesado em (2) e (3) e **zero** em (1). Todo o Epic 5 é sofisticação de correção sobre uma base cuja completude nunca é medida. É o desequilíbrio central do produto.
- **I-2.** Completude é **mensurável sem conciliar**. Se eu conheço o saldo real em T0 e em T1, e conheço os movimentos que registrei entre T0 e T1, então `(saldo_real_T1 − saldo_real_T0) − movimentos_registrados = o que falta`. Um número. **Conciliação linha a linha é uma técnica para *localizar* o que falta — não é necessária para *saber que* falta.** Esta é a ideia mais importante da sessão inteira.
- **I-3.** Conciliação bancária responde "*qual* lançamento falta?". Saldo declarado responde "*quanto* falta?". Para uma empresa de 1 pessoa, "quanto" já dispara a ação certa (ele mesmo sabe o que esqueceu — a memória dele é o índice) e custa ~1/20 do esforço.
- **I-4.** Confiança de relatório não é binária, é uma barra de progresso. O e1p hoje apresenta DRE e Projeção como se fossem verdade absoluta. **Nenhuma tela declara sua própria incerteza.** Um selo de completude por relatório ("baseado em 47 lançamentos; divergência de R$ 340 não explicada") muda a relação do usuário com o número, sem mudar o número.
- **I-5.** A verdade sobre "quanto dinheiro existe" é *sempre* externa ao e1p. O e1p pode conhecê-la por (a) o usuário digitar, (b) um arquivo, (c) uma API. São só três portas. Toda opção da seção 4 é uma dessas três.

### 3.2 Técnica: Five Whys (#11)

**Pergunta de partida:** *"Por que o lançamento é esquecido?"*

- **Por quê 1?** Porque lançar é um ato separado, posterior e voluntário em relação ao gasto.
- **Por quê 2?** Porque no momento do gasto o usuário está no app do banco / no WhatsApp / na maquininha — **nunca no e1p**.
- **Por quê 3?** Porque o e1p só sabe do dinheiro quando alguém o informa, e a única fonte automática que ele tem é o webhook do gateway — que cobre **apenas** o subconjunto de recebimentos que passou pelo trilho da plataforma. Zero cobertura em saídas.
- **Por quê 4?** Porque o e1p foi desenhado como **sistema de origem** (ele *cria* a cobrança, *cria* o boleto, *recebe* o pagamento) e não como **sistema de registro** (que observa e classifica o que aconteceu em qualquer lugar). São arquiteturas de produto diferentes.
- **Por quê 5 — causa-raiz:** **o e1p só enxerga o dinheiro que ele mesmo originou.** Tudo que nasce fora dele é invisível por construção. Não é descuido do usuário; é o limite do desenho.

**Ideias geradas:**

- **I-6.** Se a causa-raiz é "o e1p não vê o que não originou", então há exatamente dois remédios estruturais: **(a) ampliar o que ele origina** (fazer todo dinheiro nascer no trilho) ou **(b) dar a ele olhos externos** (extrato). Conciliação bancária é (b). O trilho Pix único é (a). **(a) é mais barato, mais alinhado ao modelo de negócio e ninguém está discutindo.**
- **I-7.** Culpar o usuário ("ele esqueceu") é diagnosticar errado. O gasto acontece **fora** do e1p; a taxa de esquecimento é uma propriedade do desenho, não da disciplina dele. Qualquer solução que dependa de disciplina falha na mesma taxa.
- **I-8.** A `receipts inbox` (`payables/receipts.py`) já é uma prova de conceito exata da resposta (a): ela move o ponto de captura para **onde o usuário já está** (o share sheet do app do banco). O comentário no topo do arquivo já antecipa isto — *"qualquer porta de entrada nova (WhatsApp, e-mail) só precisa gravar um Attachment com esse owner_type"*. **O caminho certo já está desenhado no repositório e ninguém percebeu que ele é a resposta a esta pergunta.**
- **I-9.** O único momento em que lançar tem custo cognitivo ~zero é **imediatamente após pagar**, com o comprovante na tela. O share sheet acerta esse momento. Uma tela de conciliação, 30 dias depois, é o pior momento possível: o contexto evaporou.

### 3.3 Técnica: Provocação (PO) + Assumption Reversal (#13, #15)

Provocações deliberadamente absurdas, para extrair o útil.

**PO-1: "E se o e1p não tivesse nenhum campo de valor? Só fotos de comprovante."**
→ **I-10.** A IA lê o comprovante e cria o lançamento inteiro. O usuário nunca digita um número. Isso é *mais* preciso que digitação manual (elimina erro de digitação, que é uma classe de erro que o e1p hoje não trata) e infinitamente mais rápido. O e1p já tem `core/extract.py` (pdfplumber/python-docx/pytesseract, usado no módulo jurídico), já tem `core/ai`, já tem a bandeja. **As peças estão todas no repositório, desconectadas.** OCR de boleto está listado como dívida em Contas a Pagar desde a Fase 2 e nunca foi feito.

**PO-2: "E se o e1p PROIBISSE receber fora dele?"**
→ **I-11.** Não dá para proibir. Mas dá para tornar o trilho o caminho de menor resistência: se toda cobrança já nasce com Pix copia-e-cola registrado (o gateway Asaas já faz — `GET /payments/{id}/pixQrCode`, validado em sandbox conforme ADR 0002), o advogado manda *esse* código em vez da chave pessoal dele, porque é o botão que está na frente dele. **Design de atrito, não regra.** Resolve completude de receita E o vazamento de split (§2.4) simultaneamente.
→ **I-12.** Corolário incômodo: se o advogado *quiser* fugir do split, nenhuma solução técnica o impede. Conciliação bancária inclusive **piora** a relação — vira vigilância ("por que você recebeu R$ 5.000 que não passaram pela plataforma?"). Vale registrar: **conciliação bancária num produto que retém split tem uma leitura de fiscalização que o usuário vai sentir.** Isso é risco de produto, não detalhe.

**PO-3: "E se o relatório se recusasse a existir enquanto a divergência estivesse aberta?"**
→ **I-13.** Radical demais como default, mas a versão fraca é excelente: **o Diagnóstico (5.8) ganha uma regra de completude como sinal 🔴 de primeira classe** — "não confio nos outros sinais até você fechar isto". Encaixa perfeitamente no motor puro existente (`engine.py`), que é o lugar mais barato e mais correto para essa regra viver. Custo: uma regra nova num arquivo sem I/O + um campo em `EngineInput`.

**Assumption Reversal — "o usuário quer controle financeiro":**
→ **I-14.** Ele **não** quer. Ele quer *não ser pego de surpresa*. Controle é o meio que ferramentas contábeis vendem; o fim é dormir tranquilo. Isso muda o produto: em vez de "concilie suas 43 transações", entrega-se "**está tudo batendo**" ou "**faltam R$ 340 e eu acho que é o contador**". Uma frase, não uma planilha.

**Assumption Reversal — "conciliação é sobre precisão":**
→ **I-15.** Conciliação é sobre **confiança**, e confiança não requer precisão de centavo. Uma divergência de R$ 3,50 num mês de R$ 25.000 é ruído — o produto deveria ignorá-la ativamente (banda de tolerância) em vez de exibir um alerta vermelho. Ferramentas contábeis não podem fazer isso (o contador precisa fechar em zero). **O e1p pode, porque não é uma ferramenta contábil — e essa é uma vantagem competitiva real, não uma limitação.**

### 3.4 Técnica: Analogical Thinking (#2)

Como outros resolveram, e o que cada um ensina.

| Referência | O que faz | O que o e1p aprende |
|---|---|---|
| **Conta Azul** | ERP contábil PJ. Conciliação via **OFX manual** e integração bancária. Mantém [artigo público de suporte](https://ajuda.contaazul.com/hc/pt-br/articles/7500681010445) listando quais bancos oferecem OFX `[CONFIRMADO 2026-07-29]` | O OFX é infra estabelecida e *documentada como problema* — a existência de um artigo de suporte por banco denuncia o atrito. Público-alvo é o contador, não o dono |
| **QuickBooks Self-Employed** | Bank feed automático + swipe para categorizar. **Descontinuado (mar/2024), substituído pelo Solopreneur a US$ 20/mês** `[CONFIRMADO 2026-07-29]` | O produto de referência mundial para autônomo com bank feed **foi encerrado e reposicionado**. Não é evidência de que bank feed não funciona, mas é forte evidência de que **bank feed sozinho não sustenta um produto para autônomo** |
| **Organizze / Mobills** | Finanças pessoais BR, importação OFX e (nos planos pagos) Open Finance | Provam que existe demanda por sincronia bancária no BR. Mas o modelo deles é **assinatura barata com muitos usuários** — e o custo do Open Finance é fixo alto (§4), o que só fecha com escala |
| **Nubank PJ / Cora / Stone / Ton** | **O banco vira o sistema de gestão.** Cobrança, extrato e conciliação nascem no mesmo lugar — completude é automática por construção | Esta é a **ameaça competitiva real** e o insight mais desconfortável: eles não têm o problema do e1p porque *são* o plano 3. O e1p nunca vai vencê-los em conciliação. Precisa vencer em outra coisa (IA + jurídico + contratos + propostas + funil) |
| **Contador do Simples / advogado** | O CFC (ITG 2000) exige escrituração; o Livro Caixa deve registrar toda a movimentação financeira e bancária e **bater com o extrato**; a documentação bancária vai mensalmente para a contabilidade `[CONFIRMADO 2026-07-29]` | **Ponto crítico: a conciliação formal já é obrigação de alguém, e esse alguém é o contador — que já recebe o extrato todo mês.** Se o e1p fizer conciliação bancária completa, ele está **duplicando um trabalho que já é feito e pago** |

**Ideias geradas:**

- **I-16.** O e1p é o **quarto** ator a olhar para o mesmo extrato (banco, contador, e1p, usuário). Duplicar o trabalho do contador é a definição de esforço desperdiçado. O que **ninguém** faz hoje é o que o e1p pode fazer sozinho: cruzar o extrato com **contratos, propostas, funil e agenda** — dimensões que nenhum banco e nenhum contador têm.
- **I-17.** **Analogia mais útil da sessão: o velocímetro, não a caixa-preta.** Ninguém audita o velocímetro; confia-se nele porque ele está sempre certo o suficiente. A caixa-preta (conciliação linha a linha) existe para investigar acidentes. **O e1p precisa de velocímetro. Ele está construindo caixa-preta.**
- **I-18.** Todo produto contábil que oferece conciliação a autônomos apresenta o mesmo padrão de abandono na literatura de produto: o usuário concilia com entusiasmo no mês 1, parcialmente no mês 2, e nunca mais. `[ESTIMATIVA — padrão qualitativo amplamente relatado; não achei estudo quantitativo brasileiro; tratar como hipótese a validar, não como fato]`

### 3.5 Técnica: Role Playing (#16)

**Persona: Dr. Rafael, 38 anos, advogado autônomo, ~R$ 28k/mês, 11 contratos ativos, sem secretária, usa o e1p há 4 meses.**

Terça-feira, 19h40, entre uma audiência e o jantar. Ele abre o e1p:

> *"Projeção de caixa 30 dias: R$ 84.300."* — **"Isso está errado. Eu tenho R$ 19 mil no Itaú. De onde saiu 84?"**
>
> *(Se ele investigar, descobre que é a soma de tudo que faturou desde que entrou na plataforma — §2.1. Se não investigar — e ele não vai — ele decide alugar uma sala.)*
>
> Aparece um botão **"Conciliar conta bancária"**. Ele abre. Uma tela com 43 linhas de extrato à esquerda, 12 lançamentos à direita, e caixas de seleção.
>
> **"Não. Eu não vou fazer isso hoje. Nem amanhã."**
>
> Ele fecha. Não volta na aba nunca mais. `[ESTIMATIVA de comportamento — base: a persona definida no briefing (advogado, não contador, sem apoio administrativo) e o fato de que a tarefa exige um bloco contínuo de 20–40 min que o dia dele não tem]`

Contra-cenário, mesma terça, mesma hora:

> *"⚠️ Seu saldo declarado (R$ 19.000) está R$ 2.340 abaixo do que eu calculei. Provavelmente faltam lançamentos. Quer me contar o que foi?"*
>
> **"Ah — o contador (R$ 890) e o correspondente de Campinas (R$ 1.450)."** Dois toques. **Fechado.** 40 segundos.

**Ideias geradas:**

- **I-19.** A unidade de tempo do Dr. Rafael é **o intervalo entre dois compromissos**. Qualquer fluxo que não caiba em ~2 minutos não acontece. Isso é um requisito não-funcional duro, não uma preferência de UX.
- **I-20.** Ele **sabe** o que esqueceu quando confrontado com o valor. A memória dele é o índice — o sistema não precisa localizar, precisa **perguntar**. Isso demole boa parte do valor do match automático linha a linha para esta persona.
- **I-21.** Ele já usa o app do banco todo dia. **Pedir o saldo é pedir um número que está a 5 segundos do polegar dele.** Zero integração, zero consentimento, zero custo.
- **I-22.** O que ele quer ver ao abrir o app não é DRE nem conciliação: é *"posso gastar?"* e *"vou quebrar?"*. Toda a inteligência financeira do Epic 5 responde a isso — **desde que o saldo inicial seja verdadeiro**. Consertar §2.1 entrega mais valor a ele do que qualquer feature nova desta sessão.
- **I-23.** Sinal de alerta de posicionamento: se a tela de conciliação aparecer no menu, ela comunica *"este software é para quem gosta de contabilidade"*. Dr. Rafael contratou um contador exatamente para não fazer isso. **A presença da feature muda a percepção do produto mesmo para quem não a usa.**

### 3.6 Técnica: Resource Constraints (#18)

**Pergunta:** *"E se você tivesse R$ 0 de custo recorrente e 1 semana de desenvolvimento?"*

- **I-24.** Um campo de saldo + uma subtração + uma frase. `[ESTIMATIVA: cabe em 1 semana — base: escopo comparável ao módulo `cost_centers`, que é uma tabela com `tenant_id`+RLS, CRUD e uma migration aditiva; aqui é ainda menor, pois não há tela de gestão, só um formulário e um número]` Custo recorrente: **R$ 0**.
- **I-25.** Com R$ 0, Open Finance está **fora por definição** (piso de R$ 2.500/mês, §4).
- **I-26.** O corte revela a assimetria brutal: **~80% do valor de decisão está em ~5% do esforço.** A parte cara (localizar *qual* lançamento falta) é a parte que o usuário já resolve de graça com a própria memória (I-20).
- **I-27.** Segunda ordem: com R$ 0 e mais 1 semana, a IA lendo o comprovante que **já está na bandeja** vale mais que qualquer integração bancária — porque ataca a causa (§3.2) em vez do sintoma.

---

## 4. Contexto brasileiro concreto — Open Finance, OFX e o que isso custa de verdade

### 4.1 Preços de agregadores (pesquisa de 2026-07-29)

| Provedor | Preço | Status | Fonte |
|---|---|---|---|
| **Pluggy — Dados** | **A partir de R$ 2.500/mês** (mínimo mensal com volume incluído; excedente por requisição) | `[CONFIRMADO — página oficial de preços, lida em 2026-07-29]` | [pluggy.ai/precos](https://www.pluggy.ai/precos) |
| **Pluggy — Pagamentos (Pix)** | A partir de R$ 500/mês | `[CONFIRMADO — mesma página]` | [pluggy.ai/precos](https://www.pluggy.ai/precos) |
| **Pluggy — trial** | 14 dias grátis, ambiente de produção, sem cartão. Após o trial as conexões **pausam** | `[CONFIRMADO]` | [pluggy.ai/precos](https://www.pluggy.ai/precos) |
| **Belvo** | ~R$ 6.000/mês | `[NÃO CONFIRMADO EM FONTE OFICIAL — relato de desenvolvedor em fórum público (TabNews, ~mai/2026). Belvo não publica preço. Tratar como ordem de grandeza]` | [TabNews](https://www.tabnews.com.br/GuilhermeVieira/estou-desenvolvendo-um-app-de-financas-pessoais-e-nao-consigo-pagar-o-open-finance-pluggy-r2-5k-mes-belvo-r6k-mes-tecnospeed-r1-5k-de-entrada-r540) |
| **Tecnospeed** | ~R$ 1.500 de adesão + R$ 540/mês | `[NÃO CONFIRMADO EM FONTE OFICIAL — mesmo relato de fórum]` | [TabNews](https://www.tabnews.com.br/GuilhermeVieira/estou-desenvolvendo-um-app-de-financas-pessoais-e-nao-consigo-pagar-o-open-finance-pluggy-r2-5k-mes-belvo-r6k-mes-tecnospeed-r1-5k-de-entrada-r540) |
| **Klavi, Celcoin** | Preço não público | `[NÃO CONFIRMADO]` — exigem contato comercial | — |

> **Nota metodológica:** os preços de Belvo e Tecnospeed vêm de um único relato de desenvolvedor num fórum público, não de fonte oficial. Estão aqui porque a **ordem de grandeza é consistente** com o piso confirmado da Pluggy, e a conclusão desta seção não depende do número exato. Se o fundador decidir avançar para a opção (D), **cotar diretamente** é obrigatório.

### 4.2 O que esse custo significa para o e1p

O modelo de cobrança é **por conta conectada/mês** com **mínimo mensal**. O mínimo é o problema, não o unitário:

- **`[ESTIMATIVA]`** Com o piso confirmado de R$ 2.500/mês da Pluggy: para o custo do Open Finance representar 5% da receita do módulo, o e1p precisaria de R$ 50.000/mês de receita atribuível. Base: aritmética direta sobre o piso confirmado — **não** uma projeção de mercado.
- **Regra de Ouro nº 4 do `CLAUDE.md`:** *"Estamos otimizando para AWS barato. Não introduzir serviço pago sem justificar."* Um custo fixo de R$ 2.500/mês, incorrido **antes do primeiro usuário conectar uma conta**, é a antítese literal dessa regra. O ADR 0001 e o ADR 0002 escolheram a arquitetura toda em torno de "sem custo parado".
- Comparação de escala honesta: **um único piso mensal da Pluggy é ~R$ 30.000/ano.** É provavelmente mais que o custo de infra inteiro do e1p hoje.

### 4.3 Exigência regulatória — a e1p precisa ser regulada?

`[CONFIRMADO 2026-07-29]` **Não, desde que use um agregador.** Mas o enquadramento correto importa:

- Somente instituições autorizadas pelo BCB participam do Open Finance; **uma empresa não pode se cadastrar diretamente no BCB** para consumir as APIs do ecossistema. ([Pluggy — Regulação do Open Finance](https://www.pluggy.ai/en/blog/regula%C3%A7%C3%A3o-open-finance))
- A **Pluggy Brasil Instituição de Pagamento LTDA** é autorizada pelo BCB como **Iniciadora de Transação de Pagamento (ITP)**, sob a Resolução BCB nº 80/2021. É ela quem participa do ecossistema; a e1p seria cliente dela. ([Pluggy](https://www.pluggy.ai/precos))
- Uma empresa não regulada integra-se a uma plataforma já regulada, e **a responsabilidade regulatória permanece com o provedor**.
- **Mas não é isenção total.** O dado recebido não vira "da e1p": há direito de uso limitado, vinculado à finalidade do consentimento e do contrato. Na prática isso significa **LGPD com finalidade estrita** — extrato bancário é dado financeiro sensível de PF/PJ, entra no escopo do anonimizador (Regra de Ouro nº 2) se algum dia tocar a IA, e o contrato com o agregador impõe obrigações repassadas. **Não é "só plugar uma API".**

### 4.4 Consentimento — a informação que mais circula está desatualizada

`[CONFIRMADO 2026-07-29 — CORREÇÃO IMPORTANTE]` **O limite de 12 meses para consentimento não existe mais.**

A **Resolução Conjunta CMN/BCB nº 7** eliminou o prazo máximo de 12 meses; o prazo máximo passou a ser definido em acordo entre as partes. E a renovação foi simplificada: antes exigia repetir todas as etapas da autorização inicial; agora basta o cliente acessar o ambiente da instituição receptora e confirmar. ([Agência Gov](https://agenciagov.ebc.com.br/noticias/202310/bc-simplifica-renovacao-de-consentimentos-no-open-finance-e-amplia-prazo-de-validade-do-compartilhamento), [Finsiders](https://finsidersbrasil.com.br/regulamentacao/bc-acaba-com-limite-de-12-meses-para-compartilhamento-de-dados-no-open-finance/))

**Consequência para esta decisão:** o argumento "o consentimento expira em 12 meses e o atrito de renovação mata a feature" — que era o contra-argumento clássico contra Open Finance — **enfraqueceu bastante**. O bloqueio real hoje é **econômico (§4.2), não regulatório nem de UX de consentimento.** Isso é uma boa notícia para o futuro: se o custo cair (ou a escala do e1p subir), a opção (D) fica materialmente mais atraente do que era há dois anos. Vale reavaliar periodicamente.

### 4.5 OFX / CSV — a alternativa manual

`[CONFIRMADO 2026-07-29]`

- Bancos que oferecem OFX incluem **Bradesco, Itaú, Nubank (PJ), Santander, Safra, Caixa, Inter, Sicoob, Sicredi e Stone**. ([Conta Azul](https://ajuda.contaazul.com/hc/pt-br/articles/7500681010445), [Facilite](https://www.facilite.co/como-exportar-arquivo-ofx-dos-principais-bancos))
- **Nubank só oferece OFX para conta PJ** — relevante, porque muito advogado autônomo opera em conta PF. ([Conta Azul — Nubank](https://ajuda.contaazul.com/hc/pt-br/articles/360052656371))
- **Limitação séria e pouco divulgada: os bancos geralmente disponibilizam apenas os últimos 60 dias de extrato.** Isso mata qualquer ambição de carga histórica e força uma cadência de importação regular (o que reintroduz exatamente o problema de disciplina do §3.2).
- Custo recorrente: **R$ 0**. Custo do usuário: ~5 minutos por importação, mais o atrito de lembrar de fazer.
- Riscos técnicos: OFX é SGML pré-XML com dialetos por banco; encoding (Latin-1 vs UTF-8) e formato de data variam. `[ESTIMATIVA]` esperar **2–3 rodadas de correção por banco novo suportado**, com base no padrão histórico do projeto (as duas rodadas de fix de campo do comprovante mobile, PRs #56 e #58, registradas no `CLAUDE.md`, são o precedente).

---

## 5. As opções — de "quase nada" a "conciliação completa"

> **Convenção de esforço:** `[ESTIMATIVA]` em **ondas de trabalho**, calibradas contra o que já foi entregue no repositório (referência explícita em cada linha). Não há estimativa em horas porque não tenho velocity histórica confiável — usar horas seria inventar número.

---

### Opção A — Não fazer nada estrutural; reforçar só o Diagnóstico

**O que é.** Manter cobranças + contas a pagar + bandeja de comprovantes. Adicionar ao motor de diagnóstico (`engine.py`) regras que detectem *sintomas indiretos* de dados faltando: mês sem nenhuma despesa lançada em categoria recorrente que existia nos 3 meses anteriores; contrato com receita e zero custo direto; margem >85% (implausível para serviço); nenhuma saída lançada em 15 dias.

**Resolve.** Detecta os casos grosseiros com custo quase zero. Encaixa exatamente no motor puro (`engine.py` não faz I/O — a regra vira função pura testável). Zero custo recorrente, zero complexidade percebida, zero risco.

**NÃO resolve.** Não mede completude — **infere**. Falso-negativo abundante: quem esquece R$ 890 do contador todo mês, todo mês, tem um padrão *consistente* e passa despercebido. E não conserta §2.1.

**Esforço.** `[ESTIMATIVA]` **~0,5 onda.** Base: uma regra nova no `engine.py` (arquivo puro, sem I/O) tem escopo comparável às regras de margem/runway já existentes ali, que são ~30 linhas + teste unitário sem banco.

**Complexidade percebida.** **Nenhuma.** O usuário só vê um alerta a mais numa tela que já existe.

**Risco.** Baixo. O risco real é **falsa sensação de cobertura** — achar que o problema foi resolvido quando só foi mascarado.

---

### Opção B — "Saldo declarado": um número, uma divergência, zero conciliação ⭐

**O que é.** Uma vez por período (mês, ou quando quiser), o usuário informa o saldo real da conta. O sistema compara com o saldo que ele calcula a partir dos lançamentos em regime de caixa e mostra **uma frase**:

> *"Seu saldo real está R$ 2.340 abaixo do que eu calculei. Provavelmente faltam lançamentos de saída."*

Sem tela de extrato. Sem match. Sem banco. Sem checkbox.

**Mecânica (a matemática de I-2).**
`divergência = (saldo_declarado_hoje − saldo_declarado_anterior) − (entradas_pagas − saídas_pagas no intervalo)`

Ambos os termos usam `paid_at` — **regime de caixa, coerente com a regra dura do projeto**. Não inverte nada. Não precisa de `bank_accounts`: para uma empresa de 1 pessoa é **uma posição de caixa por tenant**, não um cadastro bancário.

**Resolve.**
- Mede completude **diretamente**, não por inferência (I-2).
- Dá ao Dr. Rafael o gatilho de memória que ele precisa, em ~40 segundos (I-20, §3.5).
- **Conserta §2.1 de quebra**: passa a existir um saldo de caixa verdadeiro para semear `projection.saldo_inicial`. Este benefício sozinho já justifica a opção.
- Alimenta o Diagnóstico com um sinal de completude de primeira classe (I-13).
- Permite a **banda de tolerância** (I-15): divergência < R$ 50 ou < 0,5% → verde, silêncio.
- Zero custo recorrente. Zero dependência externa. Zero regulatório.

**NÃO resolve.**
- Não diz **qual** lançamento falta (mas o usuário sabe — I-20).
- Depende do usuário declarar. Se ele não declarar, volta ao estado atual — **mas com uma diferença crucial: o sistema sabe que não sabe** e pode dizer isso ("saldo não confirmado há 47 dias").
- Não pega o caso "esqueci de lançar uma entrada E uma saída de mesmo valor" (compensação). `[ESTIMATIVA: raro]`
- Não retém o split perdido (§2.4) — só **detecta** que houve.

**Esforço.** `[ESTIMATIVA]` **~1 onda.** Base: uma tabela com `tenant_id` + RLS + migration aditiva + um endpoint + um card no front. Escopo comparável ao módulo `cost_centers` (que é exatamente isso), possivelmente menor por não ter tela de gestão.

**Dependências.** Nenhuma externa. Só a regra caixa/competência já fixada.

**Complexidade percebida.** **Muito baixa.** Um campo. A frase resultante *reduz* complexidade percebida, porque converte quatro relatórios numa afirmação sobre confiabilidade.

**Risco.** Baixo. Risco real: **usuário declarar saldo de conta PF misturada com PJ**, tornando a divergência ruído permanente. Mitigação: a frase pergunta explicitamente "saldo da conta que você usa para o escritório" e o produto tolera divergência estável (aprende a linha de base).

---

### Opção C — Import de extrato OFX/CSV com match assistido por IA

**O que é.** Usuário baixa o OFX no banco, sobe no e1p. A IA cruza as linhas contra `charges`/`payables` existentes (valor + data + descrição), sugere baixas e oferece "criar lançamento" para as linhas sem par.

**Resolve.**
- **Localiza** o que falta, não só quantifica.
- Reduz o esforço de lançar para "confirmar sugestão" — o e1p já tem `core/ai` + anonimizador para isso.
- Zero custo recorrente.
- Pode dar baixa em `charges` pagas por fora → **fecha o fantasma do §2.3** e (com decisão de produto) permite reconhecer o split retroativamente.

**NÃO resolve.**
- **Depende de disciplina mensal** — exatamente o modo de falha do §3.2, causa-raiz não atacada. Só troca "esquecer de lançar" por "esquecer de importar".
- 60 dias de janela nos bancos (§4.5) — atrasou, perdeu.
- Nubank só PJ (§4.5) — parte da persona fica de fora.
- Tela de match = a tela que o Dr. Rafael fechou (§3.5).
- Dialetos de OFX = manutenção contínua e assimétrica (banco novo = trabalho novo, para sempre).

**Esforço.** `[ESTIMATIVA]` **~3–4 ondas.** Base: parser + normalização + heurística de match + camada de IA + tela de revisão + tratamento por banco. É comparável em superfície ao módulo `financial_intelligence` inteiro (que tem 6 arquivos de serviço + telas), com a diferença de que este tem uma dependência externa não-controlada (o formato do banco) — o que historicamente custa rodadas extras neste projeto.

**Dependências.** `core/ai` + anonimizador (extrato tem nome de contraparte = PII, Regra de Ouro nº 2 obrigatória). Storage para o arquivo. Idempotência de import (reimportar o mesmo OFX não pode duplicar).

**Complexidade percebida.** **Alta.** Aqui o produto cruza a fronteira "software de gestão" → "software de contabilidade".

**Risco.** Médio-alto. Match errado dá **baixa indevida** — e baixa indevida em `charge` aciona o split (§2.4) e cria receita fantasma. O `CLAUDE.md` já registra que estorno de cobrança foi **descartado antes do merge** por duplicar `PlatformEarning`. **Portanto: hoje não existe caminho de desfazer uma baixa indevida de cobrança.** Isso é bloqueante para (C) — teria que ser resolvido antes (o vínculo `platform_earnings → transaction` de origem, já identificado como pré-requisito no `CLAUDE.md`).

---

### Opção D — Open Finance real via agregador (Pluggy/Belvo), com sync automático

**O que é.** Usuário conecta a conta uma vez; o e1p recebe transações automaticamente; match e sugestão como em (C), mas contínuo.

**Resolve.** Completude quase perfeita e **sem depender de disciplina** — o único caminho que realmente elimina a causa-raiz do §3.2 pelo lado (b). Detecta em ~1 dia o recebimento fora do trilho (§2.4). Experiência premium, argumento de venda real.

**NÃO resolve.** Não resolve o custo (§4.2). Não resolve a percepção de vigilância (I-12). E ainda exige a tela de classificação — dado bruto de extrato não é lançamento classificado.

**Esforço.** `[ESTIMATIVA]` **~4–6 ondas** + negociação comercial + due diligence de LGPD/contrato. Base: superfície de (C) mais a integração autenticada, o fluxo de consentimento, e a operação contínua (renovação, reconexão, erro de instituição).

**Custo recorrente.** **A partir de R$ 2.500/mês** `[CONFIRMADO — Pluggy]`, antes do primeiro usuário conectar.

**Dependências.** Contrato comercial. Adapter obrigatório no padrão do ADR 0002 (`is_configured()` + fallback) — inegociável.

**Complexidade percebida.** **Baixa para o usuário** (é o caminho mais suave que existe) e **alta para o negócio**.

**Risco.** Alto no eixo financeiro (custo fixo antes da receita — colide frontalmente com a Regra de Ouro nº 4), médio no eixo de produto (dependência de terceiro em caminho crítico), baixo no eixo regulatório (§4.3).

---

### Opção E — Atacar a CAUSA: capturar o lançamento no instante em que ele nasce ⭐

**O que é.** Ampliar a **bandeja de comprovantes que já existe** (`payables/receipts.py`) de "staging de arquivo" para "porta de entrada de lançamento":

1. **IA lê o comprovante** já em staging (`core/extract.py` + `core/ai`) e pré-preenche fornecedor, valor, data e conta do plano de contas. O usuário confirma. É a dívida "OCR de boleto" registrada desde a Fase 2, agora com propósito claro.
2. **WhatsApp como porta de entrada** — `whatsapp_inbox` já cria `Attachment`; falta apontar o `owner_type` para a bandeja. O próprio docstring de `receipts.py` diz que isso é trivial por construção.
3. **Nota rápida por texto/áudio** — "paguei 890 pro contador" → a IA cria a conta a pagar já baixada.

**Resolve.**
- Ataca a causa-raiz identificada nos Five Whys (§3.2, I-6/I-8/I-9): move a captura para o momento e o lugar onde o usuário está.
- **Reduz a taxa de esquecimento na origem** — as opções B/C/D todas trabalham *depois* que o esquecimento aconteceu.
- Reaproveita infraestrutura já construída e validada em campo (share sheet Android, Atalho iOS, `device_tokens`, storage S3).
- Zero custo recorrente novo (`core/ai` já está no orçamento).
- **Sinergia total com B:** (E) reduz a frequência da divergência, (B) mede o que sobrou.

**NÃO resolve.** Não é auditável — se o usuário não compartilhar o comprovante, não existe. Não mede completude (não sabe o que não viu). Não pega recebimento fora do trilho (§2.4).

**Esforço.** `[ESTIMATIVA]` **~1,5–2 ondas** para (1); **~0,5 onda** para (2), *se* as credenciais da Meta existirem (o `CLAUDE.md` registra que não existem hoje — isso é bloqueante, não estimável). Base para (1): `core/extract.py` e `core/ai` já existem e são usados no módulo jurídico com wizard dinâmico; o trabalho é prompt + schema de saída + tela de confirmação + tratamento de baixa confiança.

**Dependências.** `core/extract.py` (tesseract no container — o `CLAUDE.md` marca como "validar no build de produção", ainda pendente). Anonimizador obrigatório (comprovante tem nome de contraparte).

**Complexidade percebida.** **Negativa** — o produto fica *mais* simples: menos digitação, não mais telas.

**Risco.** Médio. IA lendo valor errado cria lançamento errado — mas o erro é **visível e corrigível na hora** (o usuário está olhando o comprovante), diferente do erro silencioso do match de OFX. Exige limiar de confiança: abaixo dele, não preenche, pergunta.

---

### Opção F — Trilho único de recebimento: o Pix da plataforma como caminho de menor resistência

**O que é.** Não é conciliação — é impedir que a divergência de receita nasça. Toda cobrança criada no e1p já traz o **Pix copia-e-cola registrado do gateway** (Asaas: `GET /payments/{id}/pixQrCode`, já validado em sandbox conforme ADR 0002), exposto no botão principal em todo lugar onde ele fala com o cliente (WhatsApp, proposta pública, ficha do cliente, agenda). Enviar a chave pessoal passa a exigir esforço deliberado.

**Resolve.**
- **Completude do lado da receita, por construção** — o webhook vira fonte de verdade de fato, não só de direito.
- **Fecha o vazamento de split (§2.4)** — é a única opção da lista que protege a receita da e1p diretamente.
- **Elimina o fantasma do §2.3** (cobrança em aberto para sempre).
- Reaproveita infra já validada ponta a ponta (ADR 0002 documenta teste real em sandbox com split de 30% aplicado corretamente).

**NÃO resolve.** Nada do lado de **saídas** — e saída é onde o esquecimento é mais provável (§2.2). Não impede quem quer fugir do split (I-12). Não mede completude.

**Esforço.** `[ESTIMATIVA]` **~1 onda.** Base: o adapter, o endpoint de Pix e o webhook já existem e foram validados contra a Asaas real; o trabalho é de superfície (propagar o código para os pontos de contato e reordenar CTAs). O `CLAUDE.md` registra que "copiar código do boleto/Pix" já foi entregue na Fila de Pagamentos (PR #60) — o padrão de UI já existe.

**Complexidade percebida.** **Nenhuma** — é o mesmo fluxo com um botão melhor posicionado.

**Risco.** Baixo tecnicamente. **Risco de negócio real:** torna o split visível e inescapável. Se o advogado perceber que está pagando 30% em algo que ele conseguia fazer de graça, pode reagir. Isso não é argumento para não fazer — é argumento para **fazer junto com uma justificativa de valor clara** (cobrança automática, régua com IA, baixa automática, boleto gerado).

---

### Opção G — Fechamento mensal assistido por IA ("3 minutos e acabou")

**O que é.** Uma vez por mês, o e1p abre um ritual curto e guiado: (1) qual o saldo hoje? *(opção B)*; (2) "faltam R$ 2.340 — pelo histórico, acho que é contador (R$ 890) e correspondente (R$ 1.450). Confirma?" *(IA sobre o histórico de recorrentes já lançados)*; (3) "estas 3 cobranças estão vencidas há +30 dias — o cliente pagou por fora?" *(ataca §2.3)*; (4) fecha o mês e **carimba o DRE daquele período como "confirmado"**.

**Resolve.** Converte conciliação em **conversa**. Usa a memória do usuário como índice (I-20). Distingue calote de baixa esquecida (§2.3). Cria o conceito de **período fechado** — que hoje não existe e é o que dá confiança de verdade a um relatório histórico (o número de março não deveria mudar em julho). Encaixa no princípio da casa: regra determinística primeiro, IA narrando depois.

**NÃO resolve.** Mensal ⇒ até 30 dias de latência. Depende do ritual acontecer.

**Esforço.** `[ESTIMATIVA]` **~2 ondas sobre (B)** — não faz sentido sem (B). Base: orquestração de um wizard + prompt sobre dados já agregados; comparável ao wizard dinâmico do módulo jurídico, que já existe como padrão no repositório.

**Complexidade percebida.** **Baixa** — é um fluxo guiado, com fim, não uma tela aberta.

**Risco.** Baixo. Risco real: virar mais uma notificação ignorada. Mitigação: o gancho é a **utilidade** ("seu DRE de julho está pronto"), não a obrigação.

---

### 5.1 Tabela comparativa

| | **A** Só Diagnóstico | **B** Saldo declarado ⭐ | **C** OFX + IA | **D** Open Finance | **E** Captura na origem ⭐ | **F** Trilho Pix único | **G** Fechamento c/ IA |
|---|---|---|---|---|---|---|---|
| **Mede completude?** | Infere | **Sim, direto** | Sim | Sim | Não | Não (receita) | Sim |
| **Localiza o que falta?** | Não | Não (usuário sabe) | Sim | Sim | N/A | N/A | Sim (via IA+usuário) |
| **Ataca a causa-raiz?** | Não | Não | Não | Sim (lado b) | **Sim (lado a)** | **Sim (lado a, receita)** | Parcial |
| **Conserta o `saldo_inicial` (§2.1)?** | Não | **Sim** | Parcial | Sim | Não | Não | Sim (via B) |
| **Fecha o vazamento de split (§2.4)?** | Não | Detecta | Detecta+corrige | Detecta | Não | **Sim, previne** | Detecta |
| **Custo recorrente** | R$ 0 | **R$ 0** | R$ 0 | **≥ R$ 2.500/mês** | R$ 0 | R$ 0 | R$ 0 |
| **Esforço `[EST.]`** | ~0,5 onda | **~1 onda** | ~3–4 ondas | ~4–6 ondas + comercial | ~1,5–2 ondas | ~1 onda | ~2 ondas (sobre B) |
| **Dependência externa** | Nenhuma | **Nenhuma** | Formato de cada banco | Agregador + contrato | tesseract; Meta (p/ WhatsApp) | Asaas (já integrado) | Nenhuma |
| **Complexidade percebida** | Nenhuma | **Muito baixa** | **Alta** | Baixa (usuário) | **Negativa** | Nenhuma | Baixa |
| **Risco** | Baixo (falsa cobertura) | Baixo | **Médio-alto** (baixa indevida; bloqueado por dívida do `PlatformEarning`) | **Alto** (custo fixo vs Regra nº 4) | Médio (IA lê errado) | Baixo téc. / médio negócio | Baixo |
| **Vira ERP contábil?** | Não | **Não** | **Sim** | Sim | Não | Não | Não |
| **Depende de disciplina?** | — | Sim (leve, 1×/mês) | **Sim (alta)** | **Não** | Sim (baixa, no ato) | Não | Sim (leve) |

---

## 6. O contra-argumento honesto — onde conciliação bancária destrói este produto

Sem diplomacia, como pedido.

### 6.1 Onde ela vira um ERP que o público-alvo abandona

**Conciliação bancária é uma tarefa de contador com nome de feature.** Ela pressupõe: (a) alguém disposto a olhar linha a linha; (b) uma noção de "fechar em zero"; (c) tolerância a divergência de centavos; (d) tempo contínuo. **O advogado autônomo não tem nenhuma das quatro.** Ele contratou um contador exatamente para não precisar tê-las.

Quatro consequências concretas:

1. **Trabalho duplicado e pago duas vezes.** O contador dele **já** recebe o extrato todo mês e **já** é obrigado a conciliar (ITG 2000, Livro Caixa que deve bater com o extrato — §3.4, `[CONFIRMADO]`). O e1p entraria como quarto ator no mesmo extrato (I-16). Isso não é diferenciação, é redundância.

2. **A feature muda o posicionamento mesmo para quem não a usa (I-23).** "Conciliação bancária" no menu comunica *"software de contabilidade"*. O diferencial declarado do e1p é IA como funcionário invisível. Um funcionário invisível **não pede que você confira o extrato dele.**

3. **Padrão de abandono.** `[ESTIMATIVA, I-18]` mês 1 com entusiasmo, mês 2 parcial, mês 3 nunca mais. E uma feature de conciliação abandonada é **pior que nenhuma**, porque o produto passa a exibir um estado "última conciliação: há 94 dias" que é puro ruído de culpa — e culpa em software financeiro produz evasão, não engajamento.

4. **Vigilância (I-12).** Num produto que retém 30% de split, "conciliação bancária" tem uma leitura inevitável: *a plataforma está olhando minha conta para ver se recebi por fora*. Mesmo que a intenção seja outra. Esse risco não existe em nenhum concorrente que não retém split, e é específico do modelo de negócio da e1p.

### 6.2 Onde ela é genuinamente indispensável

Sendo justo com o outro lado:

- **Multi-conta.** No dia em que o usuário tiver 2+ contas (PJ + investimento, ou dois bancos), a divergência agregada da opção (B) perde poder diagnóstico e a conciliação por conta passa a ser necessária.
- **Volume alto de saídas.** `[ESTIMATIVA]` acima de ~40–50 saídas/mês a memória deixa de ser índice confiável (I-20 quebra) e o match automático passa a valer o custo. Base: o limiar em que uma pessoa deixa de reconstruir o mês de cabeça — ordem de grandeza, não medição.
- **Escritório com mais de uma pessoa.** Aí quem gasta ≠ quem lança, a memória não é compartilhada, e conciliação vira o único mecanismo de controle. **Mas isso deixa de ser "empresa de 1 pessoa" — é outro produto.**
- **Litígio / auditoria / fiscalização.** Se o e1p um dia produzir peça com valor probatório, conciliação vira requisito, não conveniência.

### 6.3 O teto de simplicidade deste produto

Formulando explicitamente, porque isso deveria virar princípio de produto:

> **O e1p pode pedir ao usuário que ele CONFIRME um número. Não pode pedir que ele CONSTRUA um número.**

Declarar saldo = confirmar (5 segundos, olhando o app do banco). Conciliar 43 linhas = construir (30 minutos, atenção contínua). **A fronteira entre as duas é o teto de simplicidade.** Toda feature financeira futura deveria ser avaliada contra esse único critério.

Corolário: **o e1p tem permissão para estar aproximadamente certo** (I-15). Um contador não tem — ele fecha em zero por obrigação legal. O e1p atende ao dono, cuja pergunta é "posso gastar?", não "está em conformidade com a ITG 2000?". **Aproximadamente certo e imediato vence exato e abandonado.** Essa é a vantagem estrutural do e1p sobre Conta Azul, e ela se perde no instante em que o produto tenta fechar em zero.

### 6.4 A ameaça que nenhuma opção resolve

`Nubank PJ`, `Cora`, `Stone` **são** o plano 3 (§1.3). Para eles, completude é automática — não é feature, é consequência de serem o banco. **O e1p nunca vai ganhar essa disputa e não deveria tentar.** A resposta competitiva do e1p é o que nenhum banco tem: contrato, proposta, funil, jurídico, agenda e IA — o dinheiro *conectado ao trabalho que o gerou*. Lucratividade por contrato é algo que o Nubank PJ estruturalmente não pode calcular. Investir pesado em conciliação é investir no terreno onde o e1p é mais fraco.

---

## 7. Encaixe arquitetural (se algo for adiante)

### 7.1 A distinção crítica: Wallet ≠ banco

**Precisa ser explícito no código e na UI, ou o bug do §2.1 se repete em outra forma.**

`wallet.transactions` é **dinheiro da plataforma** (plano 1): passivo da e1p com o usuário, com split já aplicado, em três estados. **Não é** saldo bancário. Uma posição de caixa declarada é **plano 3**. Os dois **nunca devem ser somados num único "saldo"** — são o mesmo dinheiro em momentos diferentes da vida dele (sacar move do plano 1 para o plano 3).

Modelo mental defensável para a UI:

```
Na plataforma (a liberar/sacar):  available_cents + pending_cents   [plano 1]
Na sua conta (declarado):          saldo_declarado                  [plano 3]
Caixa total disponível:            os dois somados, com rótulos separados e visíveis
```

Somar sem rotular = recriar exatamente a confusão que gerou §2.1.

### 7.2 Onde entraria a entidade — e por que ela provavelmente não é "conta bancária"

Para a opção (B), **não recomendo criar `bank_accounts`.** Para uma empresa de 1 pessoa, o conceito necessário é **posição de caixa declarada**, não cadastro bancário. Banco/agência/conta/chave Pix não são usados por nada e criariam um formulário de cadastro que não serve a ninguém — complexidade percebida pura.

O que faz sentido é algo como uma tabela de declarações de saldo por tenant (data de referência, valor em centavos, origem `manual|ofx|openfinance`, autor), com `tenant_id` + RLS como toda tabela de negócio, e migration aditiva. `bank_accounts` só se justifica quando (a) houver multi-conta ou (b) (C)/(D) entrarem — e aí ela nasce com propósito claro em vez de por antecipação.

Isso é consistente com o precedente do próprio repositório: `cost_centers` e `contract_id` nasceram como **dimensões nullable** que quem não usa não preenche.

### 7.3 Impacto no `saldo_inicial` da Projeção de Caixa — a mudança de maior valor

Hoje (`projection.py:177`): `saldo_inicial = available_cents` — errado (§2.1).

Direção recomendada, em ordem de preferência:

1. **Se há declaração recente:** `saldo_inicial = saldo_declarado + movimentos de caixa (paid_at) desde a data da declaração + available_cents` (dinheiro na plataforma ainda não sacado é caixa real do usuário, só não está no banco). Rotular a origem na resposta.
2. **Se não há declaração:** manter o comportamento atual **mas declarar a limitação** nas `notes` (o módulo já tem esse mecanismo — `_NOTE_CAIXA`, `_NOTE_OVERDUE` — é o lugar natural).
3. **Nunca:** somar sem rótulo, nem apresentar runway com precisão de dia sobre um saldo inicial cuja origem é desconhecida.

O campo `notes: list[str]` do `CashProjection` já existe exatamente para comunicar incerteza por transparência em vez de esconder. É o padrão da casa e resolve isso sem inventar nada.

### 7.4 Regime caixa/competência

A declaração de saldo é **estritamente regime de caixa**. A comparação usa exclusivamente `paid_at` (nunca `competence_date`). Isso **não afeta a DRE** — que continua em competência, correta e intocada. Ponto de atenção: a divergência entre declarado e calculado **não é** erro de DRE; se alguém tentar "ajustar a DRE" com base nela, inverteu a regra dura do projeto.

### 7.5 RLS e convenções

Nada de especial: `tenant_id` + RLS, sem filtro manual (Regra de Ouro nº 1); centavos `BigInteger`; migration aditiva; qualquer integração externa atrás de adapter com `is_configured()` + fallback (padrão do ADR 0002 e do `core/storage`). Para (C)/(D), o extrato contém nome de contraparte ⇒ **anonimizador obrigatório antes da IA** (Regra de Ouro nº 2, NFR2 do PRD).

### 7.6 Dívida bloqueante para a opção (C)

Registrado explicitamente porque é fácil de esquecer: o `CLAUDE.md` documenta que **estorno de Contas a Receber foi implementado e descartado antes do merge**, porque pagar→estornar→pagar duplicaria `PlatformEarning` (o ledger global não tem vínculo de volta à `Transaction` de origem). Consequência: **hoje não existe caminho seguro de desfazer uma baixa indevida de cobrança.** Match automático de OFX vai produzir baixas indevidas. **Logo, (C) exige resolver o vínculo `platform_earnings → transaction` primeiro.** Não é opcional.

---

## 8. Recomendação faseada

### Onda 0 — Consertar o `saldo_inicial` (não é opcional, é bug)

**Fazer independentemente de qualquer decisão desta sessão.** Enquanto `projection.saldo_inicial = available_cents`, a Projeção de Caixa e o Runway estão errados e o Diagnóstico pode emitir verde falso sobre eles. No mínimo: declarar a limitação em `notes`. No ideal: substituir a fonte assim que a Onda 1 existir.

**Critério de pronto:** nenhum usuário vê um runway em dias derivado de um saldo inicial cuja origem não está declarada na tela.

### Onda 1 — Opção B (saldo declarado) + Opção A (sinal de completude no motor) ⭐

**O núcleo da recomendação.** ~1,5 onda `[ESTIMATIVA]`, R$ 0 recorrente, zero dependência externa, zero complexidade percebida, e conserta a Onda 0 de quebra. Entrega o que o fundador pediu — *"deixar simples e claro"* — literalmente: **uma frase em vez de quatro relatórios sem contexto de confiança.**

Incluir desde o dia 1: banda de tolerância (I-15) e o selo de confiança por relatório (I-4).

**Sinal a observar antes de seguir:** os usuários declaram o saldo? Com que frequência? A divergência típica é grande (⇒ há problema real e material) ou ruído (⇒ o problema era menor do que se supunha)?

> **Este é o experimento mais barato que existe para medir o tamanho real do problema — e ele deveria vir antes de qualquer investimento em conciliação, porque hoje ninguém sabe o tamanho.**

### Onda 2 — Opção E (captura na origem) + Opção F (trilho Pix)

Só depois de a Onda 1 medir. (E) ataca a causa nas saídas, (F) nas entradas e no split. Juntas atacam os dois lados da causa-raiz do §3.2 sem trazer nada de contabilidade para dentro do produto.

**Critério de decisão:** avançar **se** a Onda 1 mostrar divergência média materialmente acima da banda de tolerância em ≥ ~1/3 dos usuários ativos. **Se a divergência for pequena e estável, pare aqui** — o problema estava resolvido e o resto é over-engineering.

### Onda 3 — Opção G (fechamento mensal com IA)

Amplifica a Onda 1 e cria o conceito de período fechado. **Critério:** avançar se os usuários estiverem declarando saldo mas **não agindo** sobre a divergência — sinal de que falta o ritual guiado, não a informação.

### Onda 4 — Opção C (OFX), condicional

**Só avance para OFX SE, cumulativamente:**
1. A dívida `platform_earnings → transaction` estiver resolvida (§7.6) — **bloqueante absoluto**; **E**
2. As Ondas 1–3 estiverem rodando e a divergência **continuar** materialmente acima da tolerância (⇒ captura na origem não bastou); **E**
3. Houver pedido explícito e repetido de usuários pagantes por importação de extrato — **não** intuição interna; **E**
4. O perfil real de uso mostrar volume de saídas que quebra a memória como índice (`[ESTIMATIVA]` ~40+/mês, I-20).

Se qualquer um falhar, **não faça**. (C) é a opção com a pior relação valor/risco da lista: alto esforço, alta complexidade percebida, dependência de disciplina, e risco de baixa indevida.

### Onda 5 — Opção D (Open Finance), fortemente condicional

**Só avance para Open Finance SE, cumulativamente:**
1. Existir receita recorrente que absorva **≥ R$ 2.500/mês** `[CONFIRMADO]` sem violar a Regra de Ouro nº 4 — na prática, um plano premium **já vendido**, não projetado; **E**
2. A Onda 4 estiver em produção e a **fricção do OFX** (não a falta de dados) for o gargalo demonstrado; **E**
3. Houver decisão consciente sobre a percepção de vigilância (I-12) num produto que retém split; **E**
4. Cotação direta com ≥2 fornecedores tiver sido feita (os números de Belvo/Tecnospeed neste documento **não são oficiais**, §4.1).

**Nota positiva:** o obstáculo regulatório é menor do que se costuma dizer (§4.3) e o consentimento de 12 meses **acabou** (§4.4). O bloqueio é **puramente econômico** — e economia muda. **Reavalie a cada ~12 meses**, não uma vez para sempre.

### O que NÃO fazer, em nenhuma onda

- **Não construa uma tela de conciliação linha a linha.** É a tela que o Dr. Rafael fecha (§3.5) e a fronteira que transforma o e1p num ERP contábil (§6.1).
- **Não some saldo de plataforma com saldo bancário sem rótulo** (§7.1).
- **Não coloque "conciliação bancária" no menu** — mesmo que a capacidade exista, o rótulo é o problema (I-23).

---

## 9. Perguntas abertas — só o fundador responde, e o que cada resposta muda

**Q1. O advogado que você tem em mente já tem contador?**
→ **Se sim:** conciliação formal já é feita e paga (§3.4) ⇒ (C)/(D) perdem grande parte da justificativa, e o e1p deveria mirar em *alimentar* o contador (exportação limpa), não competir com ele. **Se não** (ele é MEI/autônomo puro sem contabilidade): a exigência do Livro Caixa recai sobre ele mesmo ⇒ (C) ganha peso real.

**Q2. Recebimento fora do trilho: você já viu isso acontecer, e você quer combater?**
→ Esta é **a pergunta mais importante da lista.** **Se é comum:** a Opção (F) sobe para prioridade #1 (é vazamento de receita direto, §2.4), e a conversa deixa de ser "qualidade do relatório do usuário" para ser "controle de receita da plataforma" — outro orçamento, outra urgência. **Se é raro/tolerado:** (F) vira melhoria de UX e a recomendação B→E permanece como está.

**Q3. `available_cents` como saldo inicial da projeção foi decisão consciente ou premissa herdada?**
→ **Se consciente:** existe um modelo mental de "carteira = caixa" que eu não capturei e que precisa ser explicitado antes de qualquer mudança. **Se herdada** (minha leitura do código): é bug, entra como Onda 0, e há um risco de que a mesma premissa esteja em outros lugares (o Cockpit usa `available + pending + withdrawn` como "faturamento líquido" em `cockpit/service.py:129-130` — o que é *correto* para faturamento, mas mostra que os dois conceitos convivem sem nomes distintos).

**Q4. Qual é o plano para o saque real (`request_payout`)?**
→ Hoje só marca `withdrawn` (`wallet/service.py:227`), sem integração bancária nem KYC. **Se saque real está no roadmap:** a e1p vai precisar dos dados bancários do usuário de qualquer forma (KYC/transferência), e aí uma entidade de conta bancária nasce por *outro* motivo, com custo já pago — o que muda a economia de (C)/(D) significativamente. **Se saque real não está no roadmap:** o dinheiro fica na plataforma indefinidamente e a distinção plano 1 vs plano 3 fica ainda mais crítica de comunicar na UI.

**Q5. Quantas contas bancárias o usuário-alvo tem, na prática?**
→ **Uma (comum em autônomo):** (B) é suficiente por muito tempo e `bank_accounts` não deve existir. **Duas ou mais (PJ + investimento):** a divergência agregada perde poder diagnóstico e a entidade de conta passa a ser necessária mais cedo (§6.2).

**Q6. Existe apetite para um plano premium pago à parte?**
→ (D) só fecha com receita dedicada (§8, Onda 5). **Se não há apetite:** Open Finance está descartado no horizonte visível e a Onda 5 pode sair do roadmap — o que simplifica o planejamento. **Se há:** vale começar a cotação agora, porque o ciclo comercial + due diligence é longo e independe do desenvolvimento.

**Q7. Qual é o preço que você aceita pagar em complexidade percebida?**
→ Formulado como escolha binária: **"o e1p pode pedir ao usuário que ele CONFIRME um número, mas nunca que ele CONSTRUA um número"** (§6.3) — você ratifica isso como princípio de produto? **Se sim:** (C) e (D) estão permanentemente fora e este documento pode ser encerrado com B→E→F→G. **Se não:** precisamos definir onde exatamente fica a linha, porque sem ela cada feature financeira futura vai renegociar o teto de simplicidade do zero.

---

## Fontes

- [Pluggy — Planos e Preços](https://www.pluggy.ai/precos) — `[CONFIRMADO 2026-07-29]` R$ 2.500/mês (Dados), R$ 500/mês (Pagamentos), trial 14 dias, ITP autorizada pelo BCB (Res. BCB nº 80/2021)
- [Pluggy — Regulação do Open Finance sem complicação](https://www.pluggy.ai/en/blog/regula%C3%A7%C3%A3o-open-finance) — empresa não regulada não se cadastra direto no BCB; integra via plataforma regulada
- [Agência Gov — BC simplifica renovação de consentimentos no Open Finance](https://agenciagov.ebc.com.br/noticias/202310/bc-simplifica-renovacao-de-consentimentos-no-open-finance-e-amplia-prazo-de-validade-do-compartilhamento) — Resolução Conjunta CMN/BCB nº 7
- [Finsiders — BC acaba com limite de 12 meses para compartilhamento de dados no Open Finance](https://finsidersbrasil.com.br/regulamentacao/bc-acaba-com-limite-de-12-meses-para-compartilhamento-de-dados-no-open-finance/)
- [TabNews — discussão pública sobre custo de Open Finance para apps pequenos](https://www.tabnews.com.br/GuilhermeVieira/estou-desenvolvendo-um-app-de-financas-pessoais-e-nao-consigo-pagar-o-open-finance-pluggy-r2-5k-mes-belvo-r6k-mes-tecnospeed-r1-5k-de-entrada-r540) — `[NÃO OFICIAL]` Belvo ~R$ 6k/mês, Tecnospeed R$ 1,5k + R$ 540/mês
- [Conta Azul — Integração bancária via OFX: quais bancos oferecem o arquivo](https://ajuda.contaazul.com/hc/pt-br/articles/7500681010445-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-quais-bancos-oferecem-o-arquivo-OFX)
- [Conta Azul — Como exportar extrato em OFX do Nubank](https://ajuda.contaazul.com/hc/pt-br/articles/360052656371-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-exportar-extrato-em-OFX-do-Nubank) — OFX só para PJ
- [Facilite — Como exportar arquivo OFX dos principais bancos](https://www.facilite.co/como-exportar-arquivo-ofx-dos-principais-bancos)
- [Fortmobile — Quais livros contábeis são obrigatórios para advogados no Simples Nacional](https://suporte.fortmobile.com.br/hc/pt-br/articles/31746902487063-Quais-livros-cont%C3%A1beis-s%C3%A3o-obrigat%C3%B3rios-para-advogados-no-Simples-Nacional)
- [CRCBA — A obrigatoriedade da escrituração contábil nas empresas do Simples Nacional](https://www.crcba.org.br/boletim/edicoes/obrigatoriedade_escrituracao_simples.htm) — ITG 2000
- [CLM Controller — A importância do extrato bancário na contabilidade](https://portaldacontabilidade.clmcontroller.com.br/a-importancia-do-extrato-bancario-na-contabilidade-da-sua-empresa/) — Livro Caixa deve bater com o extrato
- [NerdWallet — QuickBooks Solopreneur (formerly Self-Employed) Review](https://www.nerdwallet.com/business/software/learn/quickbooks-self-employed) — QBSE descontinuado mar/2024, Solopreneur US$ 20/mês

**Fontes internas (repositório, lidas em 2026-07-29):** `apps/api/app/modules/financial_intelligence/projection.py`, `.../dre.py`, `.../engine.py`, `.../diagnostics.py`; `apps/api/app/modules/wallet/service.py`; `apps/api/app/modules/payables/models.py`, `.../receipts.py`; `apps/api/app/modules/investments/service.py`; `apps/api/app/modules/cockpit/service.py`; `docs/decisions/0002-gateway-pagamento.md`; `docs/prd/prd-inteligencia-financeira.md`; `CLAUDE.md`.
