# Controle bancário no e1p — requisitos e viabilidade

> **Data:** 2026-07-29
> **Autor:** Atlas (@analyst) — 2ª rodada, modo autônomo/YOLO
> **Substitui a recomendação de:** [`2026-07-29-conta-bancaria-conciliacao-brainstorm.md`](./2026-07-29-conta-bancaria-conciliacao-brainstorm.md)
> **Tipo:** pesquisa + requisitos. **Não é** spec, story, migration ou implementação.
> **Regra de honestidade (Constitution Art. IV — No Invention):** todo prazo, número e exigência legal traz fonte com URL e data de acesso. O que é palpite meu está marcado `[EST.]` com a base declarada. O que a pesquisa não fechou está marcado **não confirmado** — e fica não confirmado.

---

## 0. Contexto e Decisão Tomada

O estudo anterior recomendou "saldo declarado em vez de conciliação". **O founder rejeitou.** Três correções dele são decisão, não hipótese:

| # | Correção do founder (verbatim ou paráfrase fiel) | Consequência para esta rodada |
|---|---|---|
| **C1** | *Receber* não se esquece — tem trilha própria (gateway Asaas, webhook, split, o dinheiro aparece). O problema é **CONTAS A PAGAR**, que não tem contraparte nenhuma: paga-se o aluguel pelo app do banco e nada no sistema protesta. | O estudo anterior mirou no lugar errado. **A assimetria é estrutural, não de disciplina do usuário.** Toda a análise aqui é do lado do pagar. |
| **C2** | *"saldo batendo é uma conferência para achar possível furos"* | Não é escrituração, não é competir com contador. **É auditoria de completude.** Muda o critério de sucesso: achar o furo > fechar em zero. |
| **C3** | *"com a entrada da nova legislação tributária, teremos que ter os dados cada vez mais fiéis de onde vem e para onde vai o dinheiro"* | Bloco 1 testa essa premissa contra a lei real. |
| **C4** | Conta de aplicação/investimento entra no processo — *"não apenas o lançamento do quanto rendeu"*, ou seja, o **movimento** (aporte e resgate) também. | Bloco 4. |
| **C5** | **RESTRIÇÃO DURA:** *"não podemos ficar contando com serviços de terceiros."* | Pluggy/Belvo/Klavi e qualquer agregador de Open Finance estão **eliminados**. A opção D do estudo anterior está morta e não é reaberta aqui. **Formato de arquivo (OFX, CSV, CNAB) não é serviço de terceiro** — é aceitável. |

**A decisão está tomada: vai construir.** Esta pesquisa dimensiona COMO e com quais requisitos.

### 0.1 O buraco confirmado no código (não é hipótese)

Dois pontos cegos verificados por leitura direta do repositório em 2026-07-29:

**(a) Transferência entre contas próprias é invisível.**
`apps/api/app/modules/investments/models.py:49` — `principal_cents` é um campo **digitado pelo usuário** (`BigInteger, default=0`). Não existe modelo de aporte nem de resgate. Quando dinheiro sai da conta corrente para a aplicação, **o e1p não registra saída nenhuma**. O único evento modelado é `register_yield`, que cria uma `Charge status=paid` sintética com `external_ref="investment:<id>"`. A docstring de `investments/service.py:27-37` marca explicitamente esse ponto como *"reservado à decisão do fundador + @architect"* e reconhece que o lançamento **hoje é somado ao "Recebido" de Contas a Receber** (`receivables.summary().paid_cents`), misturando rendimento de investimento com recebimento de cliente.

**(b) A projeção parte de um saldo que não é bancário.**
`apps/api/app/modules/financial_intelligence/projection.py:177`:
```python
saldo_inicial = int(wallet_service.wallet_summary(db)["available_cents"])
```
Isso é dinheiro da **plataforma** (passivo da e1p com o usuário, com split já aplicado), não saldo da conta bancária dele. Diagnóstico completo em §2.1 do estudo anterior — permanece válido e permanece pré-requisito.

---

## Bloco 1 — Tributário: o que a lei exige de fato

### 1.1 Onde estamos hoje (29 de julho de 2026)

`[CONFIRMADO 2026-07-29]`

| Ano | O que vale | Fonte |
|---|---|---|
| **2026 (agora)** | Ano de **teste**. CBS a 0,9% e IBS a 0,1%, alíquotas simbólicas. **O contribuinte que emitir os documentos fiscais corretamente está DISPENSADO do recolhimento** de CBS e IBS sobre fatos geradores de 2026. | [CGIBS + RFB — Orientações sobre a entrada em vigor em 1º/01/2026](https://www.cgibs.gov.br/comite-gestor-do-ibs-e-receita-federal-divulgam-orientacoes-sobre-a-entrada-em-vigor-da-cbs-e-do-ibs-em-1-de-janeiro-de-2026); [RFB — Orientações 2026](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo/orientacoes-2026) |
| **2027** | CBS integral + Imposto Seletivo. **Split payment começa — opcional e restrito a B2B.** | [Trad & Cavalcanti — Cronograma da LC 214/2025](https://www.tradecavalcanti.com.br/publicacoes/cronograma-reforma-tributaria-lei-complementar-214-2025); [Sindifisco-MS — Split payment fica para 2027, opcional e restrito ao B2B](https://www.sindifiscalms.org.br/novidade/reforma-tributaria-split-payment-fica-para-2027-e-sera-opcional-e-restrito-ao-b2b/71455) |
| **2028** | Ampliação da transição; sistema eletrônico unificado. | Trad & Cavalcanti (idem) |
| **2029–2032** | ICMS/ISS substituídos progressivamente pelo IBS. | Trad & Cavalcanti (idem) |
| **2033** | Fim da transição. ICMS, ISS, PIS, Cofins e IPI extintos. | Trad & Cavalcanti (idem) |

**A obrigação do contribuinte em 2026 é uma só, e é documental:** emitir NF-e / NFC-e / **NFS-e** / CT-e / NF3e / BP-e **com destaque de CBS e IBS, individualizados por operação**, mais as declarações de regimes específicos (DeRE) quando disponibilizadas. Advogado emite **NFS-e** — está dentro. ([RFB — Orientações 2026](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo/orientacoes-2026))

Detalhe operacional relevante: **as multas pela falta dos campos de CBS/IBS nos documentos eletrônicos foram suspensas** no início de 2026 — a obrigação legal permanece, a penalidade foi adiada. ([FENACON](https://fenacon.org.br/reforma-tributaria/multa-por-falta-de-cbs-e-ibs-em-notas-e-suspensa-no-inicio-de-2026/); [Migalhas — Receita suspende até 1º de abril multas por nota emitida sem IBS e CBS](https://www.migalhas.com.br/quentes/447209/receita-suspende-ate-1-de-abril-multas-por-nota-emitida-sem-ibs-e-cbs))

### 1.2 Split payment — a pergunta central deste bloco, respondida

**Como funciona.** O split payment foi instituído pela LC 214/2025. Quando a operação é **liquidada financeiramente** — cartão, TED, Pix, boleto — a instituição de pagamento ou credenciadora **segrega automaticamente** o valor de IBS e CBS e o remete direto ao CGIBS e à Receita Federal. A obrigação de segregar recai sobre os **prestadores de serviços de pagamento (PSPs)**, inclusive arranjos não sujeitos à regulação do BCB. ([Machado Meyer](https://www.machadomeyer.com.br/pt/inteligencia-juridica/publicacoes-ij/tributario-ij/split-payment-o-que-as-empresas-devem-fazer-agora-para-se-preparar-para-o-novo-modelo-de-arrecadacao-do-ibs-e-da-cbs) — página bloqueou fetch direto (HTTP 403); conteúdo lido via resultado de busca em 2026-07-29; [Avalara — Split Payment na LC 214/2025](https://site.avalarabrasil.com.br/reforma-tributaria/split-payment-lei-complementar-214-2025/); [SEFAZ-BA — Leal, S.C. (2025), *Split payment e arrecadação do IBS*](https://www.sefaz.ba.gov.br/docs/prt/split_payment_e_arrecadacao_do_IBS.pdf))

**Isso torna o extrato bancário MAIS ou MENOS relevante?** Depende do regime, e para a persona-alvo a resposta é a que interessa:

| Situação do contribuinte | Split payment se aplica? | Efeito no extrato |
|---|---|---|
| **Simples Nacional, DAS unificado (padrão)** — é onde vive a sociedade unipessoal de advocacia, Anexo IV | **NÃO.** IBS e CBS continuam dentro do DAS. *"Quem mantém o recolhimento unificado fica fora do split payment: você continua recebendo a nota cheia, sem segregação automática."* | **Nenhum.** O dinheiro chega inteiro na conta. O extrato continua sendo a única testemunha do que entrou e saiu. |
| **Simples Nacional com opção pelo regime regular de IBS/CBS** (regime híbrido, permitido pela LC 214/2025) | **SIM.** Passa a receber o líquido, como no Lucro Presumido. | O extrato passa a mostrar **líquido**, enquanto a NFS-e mostra **bruto**. A diferença precisa ser explicada. Isso torna a conferência **mais** necessária, não menos. |
| **Lucro Presumido / regime regular** | **SIM**, a partir de 2027 (opcional, B2B) e obrigatoriamente em fase posterior sem data confirmada. | Idem acima. |

Fontes: [Progresso Contabilidade — Split Payment e o Simples Nacional](https://blog.progressocontabilidade.com.br/split-payment-e-o-simples-nacional-na-reforma-tributaria/); [reformatributaria.com — Simples Nacional, Split Payment e impactos](https://www.reformatributaria.com/opiniao/simples-nacional-split-payment-e-impactos-da-reforma-tributaria/)

> **Resposta direta:** o split payment **não reduz** a relevância do extrato bancário para a persona-alvo. Para o advogado unipessoal no Simples/Anexo IV com DAS unificado, ele simplesmente **não se aplica** — o dinheiro chega inteiro. E para quem opta pelo regime regular, o split **cria uma divergência estrutural entre nota e extrato** (bruto vs. líquido) que só a conferência resolve. Em nenhum cenário o split payment é argumento contra ler o extrato.

**Data de obrigatoriedade plena do split payment: não confirmado.** As fontes convergem em "facultativo em 2027, restrito a B2B, obrigatório em etapa seguinte **ainda sem data marcada**". Não preencho com plausível.

### 1.3 A exigência é documento-fiscal ou movimentação financeira?

**É documento-fiscal.** Sem ambiguidade.

A obrigação acessória do contribuinte na reforma é emitir o documento fiscal eletrônico com os campos novos e transmitir as declarações de regimes específicos. **Não existe, na LC 214/2025 nem nas orientações RFB/CGIBS de 2026, obrigação de o contribuinte entregar, conciliar ou comprovar extrato bancário.** ([RFB — Orientações 2026](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo/orientacoes-2026); [CGIBS](https://www.cgibs.gov.br/comite-gestor-do-ibs-e-receita-federal-divulgam-orientacoes-sobre-a-entrada-em-vigor-da-cbs-e-do-ibs-em-1-de-janeiro-de-2026))

O crédito não-cumulativo de IBS/CBS também é **documental**: o crédito nasce do documento fiscal da aquisição, não do pagamento observado no banco.

**Nota específica e desfavorável para advocacia:** escritórios têm estrutura de custo com **baixa geração de créditos** no modelo IVA — a alíquota de referência (~26,5%) incidiria sobre receita bruta com poucas deduções. Isso é um problema de **precificação e escolha de regime**, não de rastreabilidade bancária. ([Migalhas — A reforma tributária e o impacto nos escritórios de advocacia](https://www.migalhas.com.br/depeso/446596/a-reforma-tributaria-e-o-impacto-nos-escritorios-de-advocacia); [OAB-RJ — Reforma tributária exigirá planejamento da advocacia para 2027](https://oabrj.org.br/noticias/reforma-tributaria-exigira-planejamento-advocacia-2027))

### 1.4 Onde o extrato bancário entra na obrigação — e entra por outra porta

O extrato **não** entra pela reforma. Entra por dois regimes de informação que **já existem** e que se endureceram recentemente. E, criticamente, **em ambos a obrigação é da instituição, não do contribuinte:**

**e-Financeira.** Sistema da RFB (criado em 2015) pelo qual instituições informam mensalmente valores consolidados de operações por contribuinte. A **IN RFB nº 2.278, de 28/08/2025** (em vigor desde 29/08/2025) estendeu a obrigação a **instituições de pagamento, fintechs e participantes de arranjos de pagamento** — as mesmas regras das instituições financeiras: abertura/encerramento de conta, saldos em datas-base e movimentações acima do limite. Limite reportado: movimentação/saldo mensal acima de **R$ 5.000 para pessoa física**; **R$ 15.000 para pessoa jurídica**. ([IN RFB 2.278/2025 — SPED/RFB](http://sped.rfb.gov.br/arquivo/download/7858); [Coletto Advogados](https://coletto.adv.br/in-rfb-2278-2025-mudancas-impactos/); [Advice Compliance](https://advicecompliance.com.br/in-rfb-2-278-2025-nova-norma-torna-e-financeira-obrigatoria-para-fintechs-e-ips-prazo-para-envio-31-10-25/); [Qive — e-Financeira 2025](https://qive.com.br/blog/e-financeira-2025))
> `[NÃO CONFIRMADO — divergência entre fontes]` Alguns veículos citam limites de R$ 2.000 (PF) e R$ 6.000 (PJ) especificamente para Pix em instituições de pagamento. Não achei confirmação na norma. Se o número exato importar para alguma decisão, é preciso ler a IN.

**DIMP** (Declaração de Informações de Meios de Pagamento). Obrigatória para instituições financeiras e de pagamento, que informam mensalmente as transações de PF e PJ. **A obrigação não é do contribuinte final** — é de quem intermedia o pagamento. Instituições podem, excepcionalmente **até 31/12/2026**, apresentar a DOC no lugar da DIMP. ([Prefeitura de SP — DIMP](https://prefeitura.sp.gov.br/web/fazenda/w/servicos/dimp/33131); [Dattos — DIMP 2026](https://www.dattos.com.br/en/blog/dimp))

**O que isso significa, sem retórica:** o Fisco **já tem** a movimentação bancária do contribuinte, entregue pelos bancos e pelas instituições de pagamento, sem que ele precise fazer nada. O risco dele não é *deixar de informar o extrato* — é **a divergência entre o que o extrato mostra e o que ele declarou**. Esse é um risco de malha, e é real. Mas ele é operado por cruzamento automático do Fisco, não por uma obrigação nova de conciliação.

### 1.5 Livro Caixa e ITG 1000/2000

`[CONFIRMADO 2026-07-29]` — e sem mudança pela reforma.

- Optantes do Simples podem, **opcionalmente**, adotar contabilidade simplificada (ITG 1000 / NBC TG 1000). ([CRC-BA — A obrigatoriedade da escrituração contábil nas empresas do Simples Nacional](https://www.crcba.org.br/boletim/edicoes/obrigatoriedade_escrituracao_simples.htm); [CRC-CE — O entendimento da ITG 1000 e da OTG 1000](https://www.crc-ce.org.br/crcnovo/files/CONT_ENT_ITG_1000.pdf))
- A Lei do Simples **não desobriga** do Código Civil, que impõe escrituração à pessoa jurídica. Para **sociedades de advogados**, a contabilidade formal **não é opcional**. ([CRC-BA](https://www.crcba.org.br/boletim/edicoes/obrigatoriedade_escrituracao_simples.htm))
- Apresentar Livro Diário e Razão **dispensa** o Livro Caixa (Resolução do CGSN). ([Fortmobile — Quais livros contábeis são obrigatórios para advogados no Simples Nacional](https://suporte.fortmobile.com.br/hc/pt-br/articles/31746902487063-Quais-livros-cont%C3%A1beis-s%C3%A3o-obrigat%C3%B3rios-para-advogados-no-Simples-Nacional))

**A reforma não altera nada disso.** Ela mexe em tributo sobre consumo, não em norma contábil.

### 1.6 Veredito honesto do Bloco 1

**A reforma tributária NÃO exige rastreabilidade bancária do contribuinte.** A exigência é documental — NFS-e com CBS/IBS destacados. O split payment, além de só começar em 2027 (opcional, B2B), **não se aplica** ao Simples Nacional com DAS unificado, que é exatamente o regime da persona-alvo. A justificativa tributária do C3, **como formulada**, é mais fraca do que o founder supõe.

**Mas o C3 acerta no destino por um caminho diferente do que ele descreveu**, e isso importa:

1. Pela **IN RFB 2.278/2025**, o Fisco recebe a movimentação bancária e de instituições de pagamento **automaticamente**, incluindo fintechs. Quem tem descontrole entre extrato e declaração fica exposto a cruzamento, não a uma nova obrigação.
2. Se o escritório optar pelo **regime regular de IBS/CBS** (permitido dentro do Simples), o split payment cria uma **divergência sistemática entre nota (bruto) e extrato (líquido)** — e aí conferência deixa de ser higiene e vira necessidade operacional.
3. Sociedade de advogados **já tem escrituração contábil obrigatória** por força do Código Civil, independentemente da reforma (§1.5).

**E a justificativa de conferência/controle interno (C2) se sustenta sozinha, sem apoio tributário nenhum.** Ela não depende de lei: depende de o relatório do produto estar certo. O Bloco 3 mostra que essa é a lacuna que o produto de referência mundial da categoria também tem — e como ele a resolve.

> **Consequência prática para o produto:** não vender a feature como "conformidade com a reforma tributária". Isso seria impreciso e envelheceria mal. Vender como **conferência de completude** — que é o que o founder disse que quer (C2) e o que a evidência sustenta.

---

## Bloco 2 — Viabilidade de import nativo, banco a banco

### 2.1 O formato OFX é utilizável sem terceiros?

`[CONFIRMADO 2026-07-29]` **Sim.**

- OFX é **especificação aberta**, hoje mantida pelo **OFX Work Group** dentro do consórcio **FDX** (desde 2019). Última versão funcional publicada: **2.3, outubro/2020**.
- A especificação é disponibilizada sob licença **royalty-free, mundial e perpétua**. Mais de 7.000 instituições financeiras a implementam globalmente.
- Fontes: [FDX — OFX Work Group](https://financialdataexchange.org/about-fdx/ofx-work-group/); [Wikipedia — Open Financial Exchange](https://en.wikipedia.org/wiki/Open_Financial_Exchange)

**Não há dependência de terceiro, nem contrato, nem custo recorrente.** Um arquivo OFX é um arquivo que o próprio usuário baixa no banco dele e sobe no e1p. Isso satisfaz C5 sem discussão.

### 2.2 Cobertura banco a banco (julho/2026)

| Banco | OFX? | Observações | Fonte |
|---|---|---|---|
| **Itaú** | ✅ Sim | Internet Banking → extrato → exportar | [Global Financeiro KB](https://global-financeiro.tomticket.com/kb/-integracao-bancaria/ofx-quais-sao-os-bancos-que-oferecem-esse-arquivo); [Conta Azul — Itaú](https://ajuda.contaazul.com/hc/pt-br/articles/115007756807-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-exportar-extrato-em-OFX-do-Ita%C3%BA) |
| **Bradesco** | ✅ Sim | — | [Global Financeiro KB](https://global-financeiro.tomticket.com/kb/-integracao-bancaria/ofx-quais-sao-os-bancos-que-oferecem-esse-arquivo); [Fintera](https://ajuda.fintera.com.br/article/662-bradesco-como-exportar-seu-extrato-em-ofx) |
| **Santander** | ✅ Sim | — | [Global Financeiro KB](https://global-financeiro.tomticket.com/kb/-integracao-bancaria/ofx-quais-sao-os-bancos-que-oferecem-esse-arquivo) |
| **Banco do Brasil** | ✅ Sim | — | idem |
| **Caixa** | ✅ Sim | Publica ainda um layout **CNAB 240 de Extrato Eletrônico para Conciliação Bancária** (ver §2.5) | idem; [Caixa — Manual de Leiaute CNAB 240 Extrato Eletrônico](https://www.caixa.gov.br/Downloads/extrato-eletronico-conciliacao-bancaria/Manual_de_Leiaute_CNAB_240_Extrato_Eletronico_Para_Conciliacao_Bancaria.pdf) |
| **Nubank** | ⚠️ **Só PJ** | Card da conta PJ → "Gerar Extrato" → escolher mês → recebe **OFX, CSV e PDF por e-mail**. **A conta PF não gera OFX.** | [Conta Azul — Nubank](https://ajuda.contaazul.com/hc/pt-br/articles/360052656371-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-exportar-extrato-em-OFX-do-Nubank); [Nubank — Extrato OFX/PDF conta PJ](https://blog.nubank.com.br/extrato-ofx-pdf-conta-pj-nubank/) |
| **Inter** | ✅ Sim | Também tem API (§2.6) | [Global Financeiro KB](https://global-financeiro.tomticket.com/kb/-integracao-bancaria/ofx-quais-sao-os-bancos-que-oferecem-esse-arquivo) |
| **C6 Bank** | ⚠️ **Conflitante** | Web Banking → Extrato → período (7/15/30 ou custom) → Baixar → **XLS, CSV, PDF, OFX**; limite de **6 meses por arquivo**. **Porém** há reclamação pública de que a conta **jurídica** não oferece OFX. **Não confirmado para C6 PJ.** | [Global Financeiro KB](https://global-financeiro.tomticket.com/kb/-integracao-bancaria/ofx-quais-sao-os-bancos-que-oferecem-esse-arquivo); [Reclame Aqui — C6 conta jurídica não tem extrato em formato OFX](https://www.reclameaqui.com.br/c6-bank/c6-conta-juridica-nao-tem-extrato-em-formato-ofx_ImI4qyqo50Rm6kNm/) |
| **Cora** | ✅ Sim | App → "Ver extrato" → ícone superior direito → período (mês anterior / atual / personalizado) → recebe por **e-mail** em **CSV, PDF e OFX** | [Cora — Extrato automático](https://www.cora.com.br/blog/extrato-automatico-cora/); [Nimbly — Como obter o Extrato OFX do Cora](https://blog.nimbly.com.br/internet-banking/como-obter-o-extrato-ofx-do-cora) |
| **Stone** | ✅ Sim | App → Extrato → filtrar período/tipo → Baixar extrato → **PDF, OFX, XLS ou CSV** | [Stone — Central de Ajuda / Extrato](https://ajuda.stone.com.br/-extrato); [Conta Azul — Stone](https://ajuda.contaazul.com/hc/pt-br/articles/26631121251085-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-exportar-extrato-da-Stone) |
| **Asaas** ⭐ | ✅ Sim | Filtrar período → Exportar extrato → **PDF, Excel (xlsx), CSV, OFX e CNAB 240 (v10.3)**. **Já é o gateway integrado do e1p.** | [Asaas — Quais os formatos de extrato disponíveis](https://central.ajuda.asaas.com/hc/pt-br/articles/32058137017371-Quais-os-formatos-de-extrato-dispon%C3%ADveis) (fetch direto retornou HTTP 403; conteúdo lido via resultado de busca em 2026-07-29) |
| Outros com OFX | Banco de Brasília, Safra, Mercado Pago, Mercantil, PagBank, Sicoob, Sicredi | — | [Global Financeiro KB](https://global-financeiro.tomticket.com/kb/-integracao-bancaria/ofx-quais-sao-os-bancos-que-oferecem-esse-arquivo) |

**Limitação transversal, confirmada e importante:** *"os bancos disponibilizam apenas o extrato dos últimos 60 dias"*. ([Nomus](https://www.nomus.com.br/blog-industrial/como-exportar-o-extrato-bancario-em-arquivo-ofx/)) Isso mata carga histórica retroativa e força cadência de importação. **C6 é a exceção conhecida (6 meses por arquivo).**

**Cobertura resumida:** dos 11 bancos/instituições verificados, **9 confirmadamente exportam OFX**, 1 exporta só na conta PJ (Nubank) e 1 tem informação conflitante (C6 PJ). **A cobertura é alta o bastante para o projeto ser viável.**

### 2.3 Biblioteca Python — e um risco de licença que precisa ser decidido

| Biblioteca | Licença | OFX 1.x (SGML) | OFX 2.x (XML) | Manutenção | Requisitos |
|---|---|---|---|---|---|
| **`ofxparse`** | **MIT** ✅ | ✅ | ✅ | **Inativa** — sem release novo no PyPI nos últimos 12 meses; Snyk classifica como potencialmente descontinuada | — |
| **`ofxtools`** | **GPL-3.0-only** 🚩 | ✅ | ✅ | **Inativa** (mesma classificação Snyk) | Python 3.10+, **zero dependências além da stdlib** |

Fontes: [Snyk — ofxparse](https://snyk.io/advisor/python/ofxparse); [Snyk — ofxtools](https://snyk.io/advisor/python/ofxtools); [GitHub — jseutter/ofxparse](https://github.com/jseutter/ofxparse); [GitHub — csingley/ofxtools](https://github.com/csingley/ofxtools); [ofxtools docs](https://ofxtools.readthedocs.io/en/latest/)

> 🚩 **Achado que ninguém pediu e que muda a escolha: `ofxtools` é GPL-3.0-only.** O e1p é um SaaS proprietário multi-tenant. Vincular uma biblioteca GPL-3.0 ao backend levanta questão de copyleft que **precisa de decisão consciente** (não sou advogado; a análise jurídica exata de GPL em SaaS está fora do meu escopo e **não confirmo** qual o efeito prático). `ofxparse` é **MIT** e não tem esse problema.
>
> **Recomendação de engenharia:** `ofxparse` (MIT) como referência, ou parser próprio. Ambas as libs estão inativas, então em qualquer cenário o e1p **vai manter código de parsing**. Dado que OFX 1.x é SGML simples e a spec é aberta e royalty-free (§2.1), um parser mínimo próprio é defensável — e elimina de vez a discussão de licença e de manutenção abandonada. `[EST.]` — base: a superfície necessária é `<STMTTRN>` (tipo, data, valor, memo, FITID) e `<LEDGERBAL>`, não a spec inteira.

**Riscos técnicos reais do OFX brasileiro** (herdados do estudo anterior, `[EST.]` mantidos):
- OFX 1.x é **SGML pré-XML**, com dialetos por banco.
- **Encoding** varia (Latin-1 vs UTF-8) e formato de data varia.
- O Conta Azul mantém artigo de suporte específico para o erro *"Arquivo OFX fora de padrão"*, causado por tag `<TRNTYPE>` ausente ou incorreta — evidência direta de que bancos produzem OFX fora da spec. ([Conta Azul — Como corrigir o OFX importado](https://ajuda.contaazul.com/hc/pt-br/articles/7979561804941-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-corrigir-o-OFX-importado))
- `[EST.]` esperar **2–3 rodadas de correção por banco novo suportado**. Base: precedente do próprio repositório (PRs #56 e #58 foram duas rodadas de fix de campo do comprovante mobile).

### 2.4 CSV por banco — o custo escondido

Este é o item que mais engana no planejamento.

**Não existe padrão de CSV bancário.** Cada instituição define colunas, ordem, separador (`,` vs `;`), formato de data, formato decimal (`.` vs `,`) e encoding por conta própria. Os bancos verificados que oferecem CSV são pelo menos: Nubank PJ, C6, Cora, Stone, Asaas — **cinco layouts distintos**, `[EST.]` sem contar variações por versão do próprio banco.

**Consequência de planejamento:** OFX tem **um** parser para *n* bancos. CSV tem **n** parsers para *n* bancos, e cada mudança de layout do banco quebra um deles silenciosamente. **O custo do CSV não é o primeiro parser — é o enésimo, para sempre.**

> **Recomendação:** OFX como formato de primeira classe. CSV **apenas** como fallback para o caso irrecuperável (Nubank PF, C6 PJ se confirmada a ausência), e mesmo assim com mapeamento de colunas explícito pelo usuário em vez de detecção automática por banco. **Nunca** manter uma tabela de "layouts conhecidos por banco" — é dívida composta.

### 2.5 CNAB 240/400 — faz sentido aqui?

**Existe extrato em CNAB.** A Caixa publica o *"Manual de Leiaute CNAB 240 — Extrato Eletrônico Para Conciliação Bancária"*, e o layout padrão FEBRABAN CNAB 240 é público. O Asaas exporta CNAB 240 v10.3. ([Caixa](https://www.caixa.gov.br/Downloads/extrato-eletronico-conciliacao-bancaria/Manual_de_Leiaute_CNAB_240_Extrato_Eletronico_Para_Conciliacao_Bancaria.pdf); [FEBRABAN — Layout padrão CNAB240 v10.11](https://cmsarquivos.febraban.org.br/Arquivos/documentos/PDF/Layout%20padrao%20CNAB240%20V%2010%2011%20-%2021_08_2023.pdf))

**Mas é overkill para este caso.** CNAB 240 é layout posicional de larga escala, desenhado para remessa/retorno de cobrança e pagamento em lote, e é o formato que empresas com contrato de conciliação bancária negociam com o banco. Para uma empresa de 1 pessoa que baixa o extrato do próprio app, **OFX é estritamente mais simples, mais disponível e mais barato de manter**.

> **Veredito:** CNAB fora do escopo inicial. Reavaliar só se surgir um caso concreto em que o banco do usuário oferece CNAB e não oferece OFX — **não encontrei nenhum**.

### 2.6 API do próprio banco — e a distinção que o founder precisa decidir

Existem APIs de extrato acessíveis **com as credenciais do próprio correntista**, sem agregador no meio:

**Banco Inter (API Banking).** Só para conta **PJ** — PF e MEI não têm acesso. O próprio correntista entra no Internet Banking PJ → "Soluções para Empresas > Nova Integração", gera a **aplicação**, obtém `client_id` + `client_secret` e o **par de chaves do certificado** (mTLS). Oferece **Saldo, Extrato e Pagamentos** (boleto e Pix). **O certificado vale 12 meses e precisa ser renovado.** ([Inter — API Banking Empresas](https://inter.co/empresas/api-banking/); [Inter — O Inter disponibiliza alguma API para minha Conta Digital PJ?](https://ajuda.bancointer.com.br/pt-BR/articles/4257003-o-inter-disponibiliza-alguma-api-para-minha-conta-digital-pj); [Conta Azul — Integração bancária automática com Inter](https://ajuda.contaazul.com/hc/pt-br/articles/9044458910093-Integra%C3%A7%C3%A3o-banc%C3%A1ria-autom%C3%A1tica-com-Inter-cadastrar-uma-nova-API); [Omie — Extrato via API do Banco Inter](https://ajuda.omie.com.br/pt-BR/articles/11386318-configurando-a-integracao-com-o-banco-inter-extrato-via-api))

**Asaas.** `GET /v3/financialTransactions` — "Recuperar extrato", permissão `FINANCIAL_TRANSACTION:READ`; e "Recuperar saldo da conta". ([docs.asaas.com — Recuperar extrato](https://docs.asaas.com/reference/recuperar-extrato))

**Cora.** **Não confirmado** se oferece API pública de extrato para o próprio correntista. Confirmei apenas a exportação manual OFX/CSV/PDF por e-mail (§2.2).

**A distinção que só o founder decide — coloco crua:**

| Critério | Agregador (Pluggy/Belvo) | API do próprio banco (Inter/Asaas) | Arquivo OFX |
|---|---|---|---|
| Empresa intermediária entre e1p e banco | **Sim** | **Não** — e1p ↔ banco, direto | Não |
| Custo recorrente para a e1p | **≥ R$ 2.500/mês** (Pluggy, conforme estudo anterior) | **R$ 0** | R$ 0 |
| Credencial de quem | Consentimento Open Finance intermediado | **Do próprio usuário**, gerada por ele no banco dele | N/A |
| Contrato comercial obrigatório | **Sim** | Não (é serviço do banco que o usuário já contratou) | Não |
| Se o fornecedor sumir | e1p perde a feature | e1p perde **aquele banco** | Nada acontece |
| Cobertura | Ampla | **1 banco por integração** | Ampla |

> **Meu argumento, para o founder decidir:** o Asaas **já é** dependência aceita do produto (ADR 0002). Ler o extrato da conta Asaas do usuário via a API que a e1p já autentica **não adiciona terceiro nenhum** — é a mesma integração, um endpoint a mais. Isso é qualitativamente diferente de contratar a Pluggy.
>
> A API do Inter é mais ambígua: não há intermediário e não há custo, mas há **acoplamento a um banco específico**, com certificado mTLS que **expira a cada 12 meses** e vira suporte recorrente. `[EST.]` a renovação anual de certificado por usuário é o tipo de tarefa que degrada silenciosamente e gera ticket — base: é o mesmo padrão de falha das credenciais de WhatsApp/SMTP que o `CLAUDE.md` já registra como pendências não entregues.
>
> **Proponho a linha:** *"terceiro" = empresa que a e1p precisa contratar e pagar para o produto funcionar.* Por essa régua, agregador **viola**; API do banco que o usuário já contratou **não viola**; arquivo **não viola**. Mas a decisão é do founder, e ela deve ser registrada, porque toda integração futura vai ser julgada contra ela.

### 2.7 Pix no extrato — isto é ouro, e está confirmado

`[CONFIRMADO 2026-07-29]` O manual de *Requisitos Mínimos para a Experiência do Usuário* do Banco Central determina que as instituições disponibilizem comprovante a pagador e recebedor contendo, **no mínimo**:

- **nome** dos usuários pagador e recebedor;
- **CPF (mascarado ou não) / CNPJ** de ambos;
- nome do PSP de ambos;
- campo **"Descrição"** quando preenchido;
- **valor** e **ID da transação** (E2E ID — 32 caracteres alfanuméricos, identificador único no sistema do BCB);
- hora/minuto/segundo (horário de Brasília) da liquidação.

O extrato Pix apresenta, para cada transação, nome, CPF/CNPJ **ou a chave Pix** do pagador e do recebedor. ([RecargaPay — Extrato Pix](https://recargapay.com.br/pix/extrato-pix); [Kamino — Comprovante Pix](https://kamino.com.br/blog/recibo-e-comprovante-de-pagamento-comprovante-pix/); [Bradesco — Layout Recebimentos PIX](https://wspf.banco.bradesco/wsValidadorUniversal/Content/Pdf/Layout_Recebimentos_Pix.pdf))

**Duas ressalvas honestas:**
1. O que está regulado é o **comprovante**, não o campo `<MEMO>` do OFX. **Não confirmei** que todo banco transporta nome+CPF/CNPJ da contraparte para dentro do OFX — muitos colocam texto livre no `MEMO` com qualidade variável. **Isto precisa ser verificado empiricamente com arquivos reais antes de qualquer promessa de auto-classificação.**
2. O CPF pode vir **mascarado**. Casamento exato por documento não é garantido.

**Por que importa mesmo assim:** o e1p já tem clientes e fornecedores cadastrados com `document`. Se o `MEMO` trouxer o nome da contraparte, o casamento por **nome + valor + data** é de altíssima precisão — e é exatamente o insumo de "de onde vem e para onde vai o dinheiro" que o founder pediu no C3. Não é a lei que entrega isso; é o Pix.

### 2.8 Veredito do Bloco 2

**Import nativo é viável, sem terceiros, com custo recorrente zero.** OFX é spec aberta e royalty-free (FDX), e **9 de 11** instituições verificadas exportam OFX — incluindo os digitais que a persona usa (Nubank PJ, Inter, Cora, Stone) e **o Asaas, que já é integração existente do produto e ainda exporta CNAB 240**.

Os custos reais não são o parser — são: **(a)** a janela de 60 dias, que impõe cadência e mata carga histórica; **(b)** os dialetos de OFX por banco, com precedente documentado no suporte do Conta Azul; **(c)** a escolha de biblioteca, onde `ofxtools` é **GPL-3.0** e portanto arriscada para SaaS proprietário, e `ofxparse` (MIT) está **inativa**; **(d)** o CSV, que é *n* parsers para sempre e deve ser contido como fallback, não promovido a caminho principal.

Lacunas honestas: **C6 PJ não confirmado**; **Cora API não confirmada**; **conteúdo do MEMO de Pix no OFX não verificado empiricamente**.

---

## Bloco 3 — Como produtos comparáveis resolvem o lado do PAGAR

Sem repetir a análise de recebimento do estudo anterior.

### 3.1 O achado mais forte: o líder mundial da categoria não resolve

**QuickBooks Solopreneur** — sucessor do QuickBooks Self-Employed, US$ 20/mês, o produto de referência global para dono solo:

> *"QuickBooks Solopreneur lacks dedicated billing and A/P features, and you cannot record or manage unpaid bills. There's no vendor management, no bill scheduling, and no reports for tracking outstanding payables."*
> — [TechRepublic — QuickBooks Online vs Solopreneur](https://www.techrepublic.com/article/quickbooks-online-vs-self-employed/)

Confirmado por outra fonte: *"limited to a single user and lacks bill management"* ([Mission Accounting](https://missionaccountinghelp.com/planning/business-planning/quickbooks-solopreneur)). Para ter contas a pagar é preciso subir para o QuickBooks Online.

**Como ele sabe, então, que uma despesa aconteceu?** Pelo **bank feed automático** — *"automatic bank transaction downloads"* — e por categorização das transações que chegam pelo feed ([QuickBooks — Solopreneur](https://quickbooks.intuit.com/solopreneur/)). A captura de recibo pelo app existe e anexa a transações, mas com fluxo diferente do QuickBooks principal, e há relato de usuário na comunidade Intuit de **não conseguir subir foto de recibo no Solopreneur**, sendo orientado a categorizar o que chega pelo feed ([Expensent — QuickBooks Receipt Capture: 10 Methods Compared (2026)](https://www.expensent.com/guides/quickbooks-receipt-capture-methods); [Intuit Community](https://quickbooks.intuit.com/learn-support/en-us/reports-and-accounting/are-you-able-to-upload-expense-receipts-photos-into-a/00/1419337)).

> **Isto valida o founder frontalmente.** O produto mais maduro do mundo para empresa de 1 pessoa **abre mão de contas a pagar** e aposta **inteiramente** no extrato como fonte de verdade das saídas. A assimetria que o founder descreveu (C1) não é peculiaridade do e1p — **é a assimetria estrutural da categoria**, e o líder a resolve exatamente pelo caminho que ele quer seguir.
>
> Diferença que joga a favor do e1p: o e1p **já tem** contas a pagar, plano de contas, centro de custo e lucratividade por contrato. O extrato entraria como **conferência** sobre um modelo que já existe — não como substituto dele. Isso é uma posição melhor que a do Solopreneur, não pior.

### 3.2 O mercado brasileiro trata conferência de saldo como o produto

**Conta Azul** vende conciliação bancária como funcionalidade nomeada, com integração automática **e** import OFX, e mantém artigo de suporte intitulado *"Conciliação bancária: manual completo para **bater saldo**"* — a linguagem é literalmente a do founder (C2). Também mantém artigo específico para **corrigir OFX fora do padrão** e outro para **resolver falhas na integração automática**. ([Conta Azul — Conciliação bancária automática para PMEs](https://contaazul.com/funcionalidades/conciliacao-bancaria/); [Conta Azul — Manual completo para bater saldo](https://ajuda.contaazul.com/hc/pt-br/articles/7452788480141-Concilia%C3%A7%C3%A3o-banc%C3%A1ria-como-fazer); [Conta Azul — Como corrigir o OFX importado](https://ajuda.contaazul.com/hc/pt-br/articles/7979561804941-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-corrigir-o-OFX-importado); [Conta Azul — Resolver falhas na integração automática](https://ajuda.contaazul.com/hc/pt-br/articles/44330635640461-Concilia%C3%A7%C3%A3o-como-resolver-falhas-na-integra%C3%A7%C3%A3o-autom%C3%A1tica-banc%C3%A1ria))

**Nibo** automatiza a conciliação com Open Finance (20+ instituições) importando diariamente e **sugerindo conciliações**; e importa **extrato em PDF** com reconhecimento automático por IA. Posicionamento explícito: nasceu para escritórios de contabilidade. ([Nibo — Conciliador Open Finance](https://ajuda.nibo.com.br/pt-BR/articles/10185495-saiba-tudo-sobre-o-nibo-conciliador-open-finance); [Nibo — Conciliação bancária](https://ajuda.nibo.com.br/pt-BR/articles/6884846-conciliacao-bancaria))

Comparativo independente é direto sobre para quem cada um serve: *"Nibo vale a pena quando o seu contador já usa Nibo do lado dele e você tem fluxo financeiro denso; fora desse cenário, a maior parte do valor da ferramenta se perde."* ([Manio — Conta Azul, Omie, Nibo ou Planilha?](https://manio.app/pt/blog/conta-azul-omie-nibo-ou-planilha))

**Organizze / Mobills** (finanças pessoais, mas mesmo mecanismo): as reclamações se concentram em **sincronização bancária instável em bancos menores** e **problemas de importação de OFX no Organizze**. O Mobills é o app financeiro mais baixado do Brasil (6M+ downloads). ([ZapGastos — Mobills ou Organizze](https://zapgastos.com/blog/mobills-ou-organizze/))

### 3.3 O que funciona e o que os usuários abandonam

Padrões que a evidência sustenta:

| Funciona | Evidência |
|---|---|
| **Sugerir o match, não pedir que o usuário o construa** | Nibo "sugerindo conciliações de forma inteligente"; QuickBooks categorizando o que chega pelo feed |
| **Importação recorrente e automática** (diária) em vez de ritual mensal | Nibo importa diariamente; QuickBooks tem feed contínuo |
| **Extrato como fonte primária das saídas**, não como auditoria de um cadastro manual | QuickBooks Solopreneur, que nem tem cadastro manual |
| **Reconhecimento por IA de documento** (PDF de extrato, recibo) | Nibo importa extrato em PDF com IA |

| Abandonam / frustra | Evidência |
|---|---|
| **Arquivo fora do padrão** | Conta Azul precisa de artigo dedicado a corrigir OFX (`<TRNTYPE>` ausente) |
| **Duplicidade quando há duas fontes** | Conta Azul documenta duplicidade quando OFX e integração automática divergem em descrição/data |
| **Sync instável em banco menor** | Reclamações recorrentes em Organizze/Mobills |
| **Ferramenta desenhada para o contador, usada pelo dono** | Manio: valor do Nibo "se perde" fora do cenário contador+fluxo denso |

`[EST.]` A tese do estudo anterior de que "o usuário concilia no mês 1, parcial no mês 2, nunca mais" **continua sem estudo quantitativo brasileiro que a confirme.** Mantenho como hipótese, não fato. **Porém**, ela agora tem um contrapeso: o QuickBooks Solopreneur não pede que o usuário concilie — o feed chega sozinho e ele só categoriza. **Se a importação for recorrente e o match for sugerido, o modo de falha "abandono do ritual" é substancialmente mitigado.** Esse é o desenho a copiar.

### 3.4 A lição de produto, destilada

Nenhum produto da categoria resolve despesa esquecida **pedindo ao usuário que lance melhor.** Todos resolvem **observando o dinheiro sair**. A diferença entre eles é só a porta: bank feed (QuickBooks, Nibo), OFX (Conta Azul), PDF+IA (Nibo).

O e1p, sob a restrição C5, tem a porta do **arquivo**. É a mais barata, a mais duradoura e a que menos depende de terceiro. É também a que **exige uma ação do usuário** — e por isso o desenho tem que gastar seu orçamento de esforço em **reduzir a fricção dessa ação** (lembrete no vencimento do ciclo, aceitar o arquivo pelo share sheet que já existe, aceitar e-mail do banco), não em sofisticar a tela de match.

---

## Bloco 4 — Transferência entre contas próprias

### 4.1 A prática consolidada

`[CONFIRMADO 2026-07-29]` A modelagem padrão em sistemas de gestão brasileiros é **um evento, dois lançamentos, tipo próprio**:

- **Uma transferência gera duas pernas**: saída na conta de origem, entrada na conta de destino.
- **Não representa receita nem despesa.** Fonte literal do Conta Azul: *"este tipo de lançamento não representa receita nem despesa"*.
- **Não aparece em DRE / relatório de receitas e despesas.**
- É um **tipo de transação distinto**, acessado por função dedicada ("Transferência"), separado de contas a pagar e contas a receber.
- **Na conciliação, transferências criadas são baixadas automaticamente e não ficam em aberto** — não exigem match manual.

Fontes: [Conta Azul — Lançamentos financeiros: como lançar transferência entre contas](https://ajuda.contaazul.com/hc/pt-br/articles/7454909121165-Lan%C3%A7amentos-financeiros-como-lan%C3%A7ar-transfer%C3%AAncia-entre-contas); [Meu Dinheiro — Conceitos e operações de controle financeiro](https://docs.meudinheiroweb.com.br/perguntas-frequentes/conceitos-e-operacoes-de-controle-financeiro); [Finbits — Transferência entre contas](https://www.finbits.com.br/central-de-ajuda/transferencia-entre-contas); [IXC Soft — Transferência entre contas](https://wiki-erp.ixcsoft.com.br/documentacao/menu-sistema/financeiro/transferencia-entre-contas/transferencia-entre-contas.html)

**Isto é partida dobrada simplificada, não contabilidade completa.** Não exige plano de contas contábil, não exige débito/crédito explícito na UI, não exige conta de trânsito. **Conta de trânsito só é necessária quando as duas pernas ocorrem em datas diferentes** (ex.: resgate pedido dia 1, liquidado dia 3 — cotização + liquidação). Fonte sobre o descasamento de prazos: [Nexoos — resgate de investimento](https://www.nexoos.com.br/blog/resgate-de-investimento/).

### 4.2 O lado contábil do aporte e do resgate

Prática contábil clássica: ao aplicar, **debita-se a conta de aplicação e credita-se "Bancos"**. ([Dominando a Contabilidade — Lançamento contábil de aplicações financeiras](https://dominandoacontabilidade.com/como-fazer-lancamento-contabil-de-aplicacoes-financeiras/); [IXC Soft — Lançar resgate, aplicação ou investimento pela conciliação bancária](https://wiki.ixcsoft.com.br/pt-br/Financeiro/Comolan%C3%A7aresgateaplica%C3%A7%C3%A3oouinvestimentoatrav%C3%A9sdaconcilia%C3%A7%C3%A3obanc%C3%A1ria))

Traduzido para o vocabulário do e1p, **sem virar ERP contábil**:

| Evento | Modelagem | Efeito na DRE | Efeito no saldo |
|---|---|---|---|
| **Aporte** (corrente → aplicação) | Transferência: perna de saída na conta corrente, perna de entrada na conta de aplicação. `principal_cents` da `InvestmentAccount` deixa de ser digitado e passa a ser **derivado** da soma dos aportes menos resgates de principal. | **Zero.** Não é despesa. | Corrente −X, aplicação +X. Total inalterado. |
| **Rendimento** | Continua exatamente como está: `register_yield` → `Charge status=paid`, grupo **FINANCEIRO**, `external_ref="investment:<id>"`. **Não mexer nisto.** | **Receita financeira.** Correto hoje. | Aumenta o saldo da aplicação. |
| **Resgate** (aplicação → corrente) | Transferência: perna de saída na aplicação, perna de entrada na corrente. | **Zero.** Não é receita. | Aplicação −X, corrente +X. Total inalterado. |

### 4.3 A armadilha do resgate — e como não cair nela

**O resgate bruto que aparece no extrato é `principal devolvido + rendimento`.** Se o valor cheio do resgate for lançado como transferência, o rendimento embutido nunca vira receita financeira — some da DRE. Se for lançado como receita, vira **receita fantasma** e infla o resultado.

**A regra que evita ambos:** o rendimento é reconhecido por `register_yield` **no momento em que é competência**, e o resgate movimenta **apenas o valor**, decomposto contra o saldo já reconhecido da conta de aplicação. O saldo da aplicação deve ser sempre:

```
saldo_aplicação = Σ aportes − Σ resgates + accrued_yield_cents
```

Se o resgate levar valor maior que `Σ aportes − Σ resgates`, a diferença é rendimento sendo realizado — e ele **já foi reconhecido** por `register_yield`, então não pode ser reconhecido de novo. Se **não** foi reconhecido, o sistema deve **pedir** o `register_yield` antes de fechar o resgate, não inventar o número.

> **Esta é a parte que precisa de decisão do @architect, não minha.** Eu registro a regra; a implementação (validação, ordem das operações, o que fazer com resgate total) é design de domínio.

### 4.4 Dívida existente que este bloco reabre

A docstring de `investments/service.py:27-37` já registra, como ponto reservado ao founder + @architect, que a `Charge` de rendimento **hoje é somada ao "Recebido" de Contas a Receber** (`receivables.summary().paid_cents`) e listada por `list_charges`. A mitigação já está desenhada lá (filtrar `external_ref LIKE 'investment:%'`).

**Enquanto isso não for decidido, qualquer conferência de saldo que use "Recebido" como insumo vai contar rendimento de investimento como recebimento de cliente.** É pré-requisito, não detalhe. E note que, se o aporte/resgate entrar como transferência, o problema **piora**: passariam a existir três coisas diferentes na mesma tela (cobrança de cliente, rendimento, movimento de aplicação).

---

## Requisitos Consolidados

Cada REQ é rastreável a uma fonte (com link) ou a uma fala do founder (C1–C5). **Isto é lista de requisitos, não backlog priorizado** — priorização é do @pm.

### Grupo A — Fundação de contas e saldo

**REQ-1.** O e1p deve modelar **conta financeira própria do usuário** como entidade de primeira classe, com pelo menos os tipos `corrente` e `aplicação`, `tenant_id` + RLS, valores em centavos `BigInteger`.
→ *Rastreio:* C4 (founder: conta de aplicação entra no processo) + §4.1 (todo sistema comparável tem conta como entidade para poder ter transferência entre elas).
→ *Nota:* isto **contraria** a recomendação §7.2 do estudo anterior ("não criar `bank_accounts`"). C4 e C1 tornam a entidade necessária.

**REQ-2.** Toda conta deve manter **saldo derivado dos movimentos**, nunca um saldo digitado.
→ *Rastreio:* §0.1(a) — `principal_cents` digitado é a origem do ponto cego confirmado em `investments/models.py:49`.

**REQ-3.** O `saldo_inicial` da Projeção de Caixa (`projection.py:177`) deve deixar de ser `wallet_summary()["available_cents"]` e passar a derivar de saldo de conta bancária, com a origem **rotulada** na resposta.
→ *Rastreio:* §0.1(b), confirmado por leitura de código; estudo anterior §2.1 e §7.3.
→ *Bloqueante:* qualquer conferência de completude que rode sobre a projeção atual mede contra um número errado.

**REQ-4.** Saldo de plataforma (`wallet`) e saldo bancário **nunca** podem ser somados sem rótulo distinto na UI.
→ *Rastreio:* estudo anterior §7.1; `wallet/service.py` — `available_cents` é passivo da plataforma, não caixa.

### Grupo B — Import de extrato

**REQ-5.** O formato de primeira classe de importação é **OFX**, suportando OFX 1.x (SGML) e 2.x (XML).
→ *Rastreio:* §2.1 (spec aberta, royalty-free, FDX) + §2.2 (9 de 11 instituições verificadas exportam OFX) + C5 (arquivo não é serviço de terceiro).

**REQ-6.** A escolha de biblioteca de parsing deve considerar licença explicitamente: **`ofxtools` é GPL-3.0-only** e `ofxparse` é MIT; **ambas estão inativas**.
→ *Rastreio:* §2.3, [Snyk/ofxtools](https://snyk.io/advisor/python/ofxtools), [Snyk/ofxparse](https://snyk.io/advisor/python/ofxparse).
→ *Requer decisão registrada* (ADR) antes de qualquer linha de código.

**REQ-7.** A importação deve ser **idempotente**: reimportar o mesmo arquivo, ou arquivos com sobreposição de período, não pode duplicar movimentos. Chave natural mínima: `FITID` do OFX + conta.
→ *Rastreio:* §3.3 — o Conta Azul documenta duplicidade quando duas fontes divergem em descrição/data.

**REQ-8.** O sistema deve tolerar e reportar OFX fora do padrão (tag `<TRNTYPE>` ausente/incorreta, encoding Latin-1 vs UTF-8, formatos de data variantes) com mensagem acionável ao usuário — nunca falhar silenciosamente.
→ *Rastreio:* §2.3, [Conta Azul — Como corrigir o OFX importado](https://ajuda.contaazul.com/hc/pt-br/articles/7979561804941-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-corrigir-o-OFX-importado).

**REQ-9.** O produto deve assumir **janela de 60 dias** como limite típico de extrato disponível e desenhar a cadência de importação em torno disso (lembrete recorrente), sem prometer carga histórica.
→ *Rastreio:* §2.2, [Nomus](https://www.nomus.com.br/blog-industrial/como-exportar-o-extrato-bancario-em-arquivo-ofx/).

**REQ-10.** CSV é **fallback**, não caminho principal, e deve exigir mapeamento explícito de colunas pelo usuário — proibido manter tabela de "layouts conhecidos por banco".
→ *Rastreio:* §2.4 — *n* parsers para *n* bancos é dívida composta.

**REQ-11.** CNAB 240/400 fica **fora do escopo** até que apareça um banco concreto que ofereça CNAB e não ofereça OFX.
→ *Rastreio:* §2.5.

**REQ-12.** A importação de extrato deve reaproveitar a porta de entrada de arquivo que já existe (share sheet / bandeja de comprovantes, `payables/receipts.py`), não criar um fluxo de upload paralelo.
→ *Rastreio:* `CLAUDE.md` (bandeja de staging via `Attachment` com `owner_type="receipt_inbox"`); §3.4 (o orçamento de esforço deve ir para reduzir fricção da ação, não para sofisticar o match).

### Grupo C — Conferência (o objetivo do founder)

**REQ-13.** O objetivo declarado do módulo é **conferência para achar furos**, não escrituração. O critério de sucesso é *"quantos lançamentos faltantes foram encontrados"*, não *"fechou em zero"*.
→ *Rastreio:* C2, verbatim do founder.

**REQ-14.** O foco primário é **contas a PAGAR**. Movimentos de saída no extrato sem `Payable` correspondente são o achado de maior valor do sistema.
→ *Rastreio:* C1 (founder) + §3.1 (QuickBooks Solopreneur não tem A/P e depende inteiramente do feed para saber que a despesa ocorreu).

**REQ-15.** O sistema deve **sugerir** o vínculo entre linha de extrato e lançamento existente (valor + data + descrição), e **oferecer criar o lançamento** quando não houver par. O usuário confirma; nunca constrói o match do zero.
→ *Rastreio:* §3.3 (Nibo sugere; QuickBooks categoriza o que chega) + estudo anterior §6.3 (*"pode pedir que CONFIRME um número, não que CONSTRUA"*).

**REQ-16.** Deve existir **banda de tolerância** configurável abaixo da qual a divergência é ignorada ativamente (sem alerta vermelho).
→ *Rastreio:* C2 (conferência, não fechamento contábil) + estudo anterior I-15.

**REQ-17.** Dar baixa automática em `Charge` a partir de linha de extrato é **bloqueado** enquanto não existir o vínculo `platform_earnings → transaction`.
→ *Rastreio:* `CLAUDE.md` — estorno de Contas a Receber foi implementado e **descartado antes do merge** porque pagar→estornar→pagar duplicaria `PlatformEarning`. Hoje não há caminho seguro de desfazer baixa indevida de cobrança.
→ *Nota:* isto **não bloqueia** o lado do pagar (REQ-14), que é o foco. `Payable` nunca move dinheiro pela Carteira e já tem estorno seguro (`POST /payables/bills/{id}/reverse`).

**REQ-18.** O extrato contém nome e documento de contraparte (PII). O **anonimizador é obrigatório** antes de qualquer chamada à IA.
→ *Rastreio:* `CLAUDE.md` Regra de Ouro nº 2; §2.7 (Bacen exige nome + CPF/CNPJ no comprovante Pix).

**REQ-19.** O match automático deve tentar usar a identificação de contraparte do Pix (nome / CPF / CNPJ) contra `clients` e fornecedores já cadastrados — **mas o conteúdo real do campo `MEMO` no OFX de cada banco precisa ser verificado empiricamente antes de qualquer promessa de funcionalidade.**
→ *Rastreio:* §2.7 — regulado no comprovante ([Bacen, via RecargaPay/Kamino](https://recargapay.com.br/pix/extrato-pix)); **não confirmado** no OFX.

### Grupo D — Transferência entre contas próprias

**REQ-20.** Transferência entre contas próprias é um **tipo de lançamento distinto**, com **duas pernas** (saída na origem, entrada no destino), que **não é receita nem despesa**.
→ *Rastreio:* §4.1, [Conta Azul](https://ajuda.contaazul.com/hc/pt-br/articles/7454909121165-Lan%C3%A7amentos-financeiros-como-lan%C3%A7ar-transfer%C3%AAncia-entre-contas), [Meu Dinheiro](https://docs.meudinheiroweb.com.br/perguntas-frequentes/conceitos-e-operacoes-de-controle-financeiro), [Finbits](https://www.finbits.com.br/central-de-ajuda/transferencia-entre-contas).

**REQ-21.** Transferência **não aparece na DRE** nem em nenhum relatório de receitas/despesas, e **não entra** em lucratividade por contrato nem em burn rate.
→ *Rastreio:* §4.1 — *"não representa receita nem despesa"*; se entrasse, os relatórios ficariam incorretos.

**REQ-22.** Transferência criada no e1p já nasce **conciliada** — não fica em aberto esperando match.
→ *Rastreio:* §4.1, Conta Azul: *"todas as transferências criadas serão baixadas automaticamente e não ficarão em aberto"*.

**REQ-23.** **Aporte** = transferência corrente → aplicação. **Resgate** = transferência aplicação → corrente. `principal_cents` da `InvestmentAccount` passa a ser **derivado** (Σ aportes − Σ resgates de principal), deixando de ser campo digitado.
→ *Rastreio:* C4 (founder) + §0.1(a) (`investments/models.py:49`) + §4.2.

**REQ-24.** **`register_yield` não muda.** Rendimento continua sendo receita financeira no grupo FINANCEIRO, via `Charge status=paid` com `external_ref="investment:<id>"`.
→ *Rastreio:* `investments/service.py:9-25`, decisão já validada com teste explícito (não cria `Transaction`/`PlatformEarning`); founder confirmou que o rendimento já está certo (C4: *"não apenas o lançamento do quanto rendeu"*).

**REQ-25.** O resgate **não pode gerar receita**. Se o valor resgatado exceder `Σ aportes − Σ resgates`, a diferença é rendimento já reconhecido — se **não** foi reconhecido, o sistema deve **pedir** o `register_yield` antes de fechar o resgate, nunca inferir o valor.
→ *Rastreio:* §4.3 (regra derivada) + Constitution Art. IV (não inventar número).

**REQ-26.** Duas pernas de uma transferência podem ocorrer em **datas diferentes** (cotização + liquidação de resgate). O modelo deve suportar isso sem produzir saldo negativo temporário incorreto.
→ *Rastreio:* §4.1, [Nexoos — prazo de resgate](https://www.nexoos.com.br/blog/resgate-de-investimento/).

**REQ-27.** A ambiguidade documentada em `investments/service.py:27-37` — a `Charge` de rendimento ser somada ao "Recebido" de Contas a Receber — precisa de **decisão do founder + @architect antes** de aporte/resgate entrarem, sob pena de a tela passar a misturar três coisas distintas.
→ *Rastreio:* leitura direta de `investments/service.py:27-37`, que reserva explicitamente esse ponto.

### Grupo E — Posicionamento e restrição

**REQ-28.** A feature **não pode** ser comunicada como "conformidade com a reforma tributária". A obrigação da reforma é **documental** (NFS-e com CBS/IBS destacados), não bancária.
→ *Rastreio:* §1.3, [RFB — Orientações 2026](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo/orientacoes-2026), [CGIBS](https://www.cgibs.gov.br/comite-gestor-do-ibs-e-receita-federal-divulgam-orientacoes-sobre-a-entrada-em-vigor-da-cbs-e-do-ibs-em-1-de-janeiro-de-2026).

**REQ-29.** Nenhum agregador de Open Finance (Pluggy, Belvo, Klavi, Tecnospeed, Celcoin) pode entrar no caminho crítico.
→ *Rastreio:* C5, verbatim do founder.

**REQ-30.** A definição operacional de "serviço de terceiro" deve ser **registrada em ADR**. Proposta a ratificar: *terceiro = empresa que a e1p precisa contratar e pagar para o produto funcionar.* Por essa régua, agregador viola; API de banco que o **usuário** já contratou não viola; arquivo não viola.
→ *Rastreio:* C5 + §2.6 — sem essa linha escrita, cada integração futura renegocia a restrição do zero.

**REQ-31.** Se API de banco for admitida (REQ-30), qualquer integração desse tipo segue o padrão do ADR 0002: **adapter com `is_configured()` + graceful degradation**, e o produto funciona por arquivo se a API não estiver configurada.
→ *Rastreio:* `CLAUDE.md` / `core/payment_gateway.py` / `docs/decisions/0002-gateway-pagamento.md`; §2.6 (certificado mTLS do Inter expira a cada 12 meses — o produto não pode quebrar quando isso acontecer).

**REQ-32.** O extrato do **Asaas** (`GET /v3/financialTransactions`) deve ser avaliado como primeira integração de API, por ser a única onde a e1p **já** detém a credencial e a integração.
→ *Rastreio:* §2.6, [docs.asaas.com — Recuperar extrato](https://docs.asaas.com/reference/recuperar-extrato); ADR 0002 (Asaas já é dependência aceita).

---

## Riscos à decisão

Registrados por obrigação de honestidade. **Não reabrem a decisão de construir** — informam o desenho e a comunicação.

**R1 — A justificativa tributária, como formulada pelo founder, não se sustenta.** A reforma exige documento fiscal, não extrato (§1.3). Split payment não se aplica ao Simples com DAS unificado e só começa em 2027, opcional e B2B (§1.2). **Risco concreto:** se a feature for vendida como "a reforma exige", ela envelhece mal e expõe o produto a contestação por qualquer contador. **Mitigação:** REQ-28. **Isto não invalida o projeto** — invalida um argumento de marketing.

**R2 — A justificativa de conferência (C2) é forte, mas é interna.** Ela não tem força de lei, o que significa que a urgência é escolha da e1p, não imposição externa. **Consequência de planejamento:** não há deadline regulatório. O projeto compete por prioridade em pé de igualdade com o resto do roadmap.

**R3 — Ninguém sabe o tamanho do problema.** Não existe medição de quantos lançamentos os usuários do e1p esquecem hoje. Todo dimensionamento de valor nesta pesquisa é `[EST.]`. **Risco:** construir para um problema de 5% quando se imaginava 40%. **Mitigação barata que não atrasa nada:** instrumentar, na primeira versão, quantos movimentos de extrato ficam **sem par** — esse número é a medição, e ela nasce de graça junto com a feature.

**R4 — A janela de 60 dias reintroduz dependência de disciplina.** O usuário precisa importar a cada ≤2 meses ou perde dados irrecuperavelmente (§2.2). O QuickBooks não tem esse problema porque tem feed contínuo (§3.1); o e1p, sob C5, tem. **Isto é o custo direto da restrição C5, e é preciso aceitá-lo com os olhos abertos.** Mitigação parcial: REQ-9 (lembrete), REQ-12 (share sheet), REQ-32 (Asaas via API contorna para aquela conta).

**R5 — `MEMO` do OFX não verificado.** Toda a promessa de auto-classificação por contraparte (REQ-19) repousa sobre um campo cujo conteúdo real por banco **não confirmei**. **Se o `MEMO` for pobre, o match cai para valor+data** — bem mais fraco e com mais falso-positivo. **Mitigação:** verificar empiricamente com arquivos reais de 3–4 bancos **antes** de comprometer escopo.

**R6 — Bibliotecas inativas + licença GPL.** `ofxtools` é GPL-3.0 e `ofxparse` está inativa (§2.3). Em qualquer caminho, a e1p vai manter código de parsing próprio. **Isto é custo permanente**, não pontual, e precisa entrar na conta.

**R7 — Escopo criando ERP contábil pela porta dos fundos.** Contas + transferências + conciliação + aporte/resgate é, somado, boa parte de um módulo financeiro de ERP. O contra-argumento do estudo anterior (§6.1) **não foi refutado** pelo founder — ele foi *reenquadrado* (C2: conferência, não contabilidade). **O reenquadramento só se sustenta se a UI o sustentar.** Se a tela virar grade de 43 linhas com checkbox, o reenquadramento morreu e o risco antigo volta inteiro. REQ-15 e REQ-16 são a defesa; elas precisam ser tratadas como requisito, não como polimento.

---

## Perguntas abertas

**Q1. Ratificar a definição de "serviço de terceiro" (REQ-30).** Proposta: *terceiro = empresa que a e1p precisa contratar e pagar para o produto funcionar.* → **Se sim:** API do Asaas e do Inter estão liberadas, e o Asaas vira a primeira integração (REQ-32). **Se não** (qualquer API externa viola): o produto é 100% arquivo, e o R4 (janela de 60 dias) é permanente e não mitigável.

**Q2. O usuário-alvo tem conta PJ ou PF?** → **PJ:** Nubank, Inter e C6 abrem OFX e API; cobertura excelente. **PF:** Nubank **não** gera OFX e Inter **não** dá API (só PJ). Isso corta uma fatia relevante da persona e muda a estimativa de cobertura de §2.8. *(Esta pergunta decide mais coisa que qualquer outra do Bloco 2.)*

**Q3. Quantas contas, na prática?** Corrente + aplicação já são duas (C4). Há mais? → Define se REQ-1 nasce com cadastro completo ou com duas contas fixas.

**Q4. Decisão pendente de `investments/service.py:27-37` (REQ-27):** a `Charge` de rendimento deve continuar aparecendo no "Recebido" de Contas a Receber? → **Se não:** filtrar `external_ref LIKE 'investment:%'` em `list_charges`/`summary`, como a própria docstring propõe. **Se sim:** aportes e resgates vão precisar de outra tela, ou a Contas a Receber vira três coisas ao mesmo tempo.

**Q5. Qual é a cadência aceitável de importação?** Mensal, quinzenal ou "quando lembrar"? → Define se o lembrete (REQ-9) é notificação, card no Cockpit ou sinal 🔴 no Diagnóstico. E define quanto o R4 dói.

**Q6. O escritório opta ou vai optar pelo regime regular de IBS/CBS dentro do Simples?** → **Se sim:** a partir de 2027 o extrato mostra líquido e a NFS-e mostra bruto (§1.2), e a conferência ganha uma dimensão nova (bruto × líquido × tributo retido) que **não está nos REQ desta rodada**. **Se não:** nada muda até 2029+.

**Q7. Baixa automática de `Charge` a partir do extrato entra no escopo (REQ-17)?** → **Se sim:** o vínculo `platform_earnings → transaction` vira pré-requisito bloqueante e o projeto cresce. **Se não** (só o lado do pagar, C1): o projeto fica no tamanho desta pesquisa e não toca no split. *Recomendo explicitamente "não" nesta rodada* — é coerente com C1 e evita a única dívida bloqueante conhecida.

---

## Fontes

### Tributário
- [CGIBS + RFB — Orientações sobre a entrada em vigor da CBS e do IBS em 1º/01/2026](https://www.cgibs.gov.br/comite-gestor-do-ibs-e-receita-federal-divulgam-orientacoes-sobre-a-entrada-em-vigor-da-cbs-e-do-ibs-em-1-de-janeiro-de-2026) — `[CONFIRMADO 2026-07-29]` documentos fiscais com destaque CBS/IBS; dispensa de recolhimento em 2026; PF contribuinte precisa de CNPJ a partir de julho/2026
- [Receita Federal — Orientações da Reforma Tributária para 2026](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/reforma-consumo/orientacoes-2026) — `[CONFIRMADO]` lista de documentos fiscais (inclui NFS-e); DeRE; dispensa condicionada
- [Trad & Cavalcanti — Cronograma da Reforma Tributária: LC 214/2025](https://www.tradecavalcanti.com.br/publicacoes/cronograma-reforma-tributaria-lei-complementar-214-2025) — cronograma 2026→2033
- [Sindifiscal-MS — Split payment fica para 2027 e será opcional e restrito ao B2B](https://www.sindifiscalms.org.br/novidade/reforma-tributaria-split-payment-fica-para-2027-e-sera-opcional-e-restrito-ao-b2b/71455)
- [Machado Meyer — Split payment: o que as empresas devem fazer agora](https://www.machadomeyer.com.br/pt/inteligencia-juridica/publicacoes-ij/tributario-ij/split-payment-o-que-as-empresas-devem-fazer-agora-para-se-preparar-para-o-novo-modelo-de-arrecadacao-do-ibs-e-da-cbs) — ⚠️ fetch retornou HTTP 403; lido via resultado de busca
- [SEFAZ-BA — Leal, S.C. (2025), *Split payment e arrecadação do IBS* (PDF)](https://www.sefaz.ba.gov.br/docs/prt/split_payment_e_arrecadacao_do_IBS.pdf)
- [Avalara — Split Payment na LC 214/2025](https://site.avalarabrasil.com.br/reforma-tributaria/split-payment-lei-complementar-214-2025/)
- [Progresso Contabilidade — Split Payment e o Simples Nacional](https://blog.progressocontabilidade.com.br/split-payment-e-o-simples-nacional-na-reforma-tributaria/) — `[CONFIRMADO]` DAS unificado fica **fora** do split
- [reformatributaria.com — Simples Nacional, Split Payment e impactos](https://www.reformatributaria.com/opiniao/simples-nacional-split-payment-e-impactos-da-reforma-tributaria/) — regime híbrido
- [FENACON — Multa por falta de CBS e IBS em notas é suspensa no início de 2026](https://fenacon.org.br/reforma-tributaria/multa-por-falta-de-cbs-e-ibs-em-notas-e-suspensa-no-inicio-de-2026/)
- [Migalhas — Receita suspende até 1º de abril multas por nota emitida sem IBS e CBS](https://www.migalhas.com.br/quentes/447209/receita-suspende-ate-1-de-abril-multas-por-nota-emitida-sem-ibs-e-cbs)
- [Migalhas — A reforma tributária e o impacto nos escritórios de advocacia](https://www.migalhas.com.br/depeso/446596/a-reforma-tributaria-e-o-impacto-nos-escritorios-de-advocacia)
- [OAB-RJ — Reforma tributária exigirá planejamento da advocacia para 2027](https://oabrj.org.br/noticias/reforma-tributaria-exigira-planejamento-advocacia-2027)
- [IN RFB nº 2.278, de 28/08/2025 (SPED/RFB)](http://sped.rfb.gov.br/arquivo/download/7858) — e-Financeira estendida a instituições de pagamento
- [Coletto Advogados — Mudanças introduzidas pela IN RFB 2.278/2025](https://coletto.adv.br/in-rfb-2278-2025-mudancas-impactos/)
- [Advice Compliance — IN RFB 2.278/2025: e-Financeira obrigatória para fintechs e IPs](https://advicecompliance.com.br/in-rfb-2-278-2025-nova-norma-torna-e-financeira-obrigatoria-para-fintechs-e-ips-prazo-para-envio-31-10-25/)
- [Qive — e-Financeira 2025: novos declarantes e limites](https://qive.com.br/blog/e-financeira-2025) — limites R$ 5.000 PF / R$ 15.000 PJ
- [Prefeitura de SP — DIMP](https://prefeitura.sp.gov.br/web/fazenda/w/servicos/dimp/33131) — obrigação das instituições, não do contribuinte
- [Dattos — DIMP: tudo o que você precisa saber em 2026](https://www.dattos.com.br/en/blog/dimp) — DOC no lugar da DIMP até 31/12/2026
- [CRC-BA — A obrigatoriedade da escrituração contábil nas empresas do Simples Nacional](https://www.crcba.org.br/boletim/edicoes/obrigatoriedade_escrituracao_simples.htm)
- [CRC-CE — O entendimento da ITG 1000 e da OTG 1000 (PDF)](https://www.crc-ce.org.br/crcnovo/files/CONT_ENT_ITG_1000.pdf)
- [Fortmobile — Quais livros contábeis são obrigatórios para advogados no Simples Nacional](https://suporte.fortmobile.com.br/hc/pt-br/articles/31746902487063-Quais-livros-cont%C3%A1beis-s%C3%A3o-obrigat%C3%B3rios-para-advogados-no-Simples-Nacional)
- [Omie — Guia da reforma para advogados: Simples Nacional, tabelas e limites](https://www.omie.com.br/blog/simples-nacional-para-advogados-reforma-tabela-e-limites/) — Anexo IV, 4,5% a 33%

### OFX, bancos e formatos
- [FDX — OFX Work Group](https://financialdataexchange.org/about-fdx/ofx-work-group/) — `[CONFIRMADO]` spec royalty-free, perpétua, mundial
- [Wikipedia — Open Financial Exchange](https://en.wikipedia.org/wiki/Open_Financial_Exchange) — versão 2.3 (out/2020), >7.000 IFs
- [Global Financeiro — OFX: quais são os bancos que oferecem esse arquivo](https://global-financeiro.tomticket.com/kb/-integracao-bancaria/ofx-quais-sao-os-bancos-que-oferecem-esse-arquivo) — lista de 15 instituições
- [Nomus — Como exportar o extrato bancário em arquivo OFX](https://www.nomus.com.br/blog-industrial/como-exportar-o-extrato-bancario-em-arquivo-ofx/) — `[CONFIRMADO]` janela de 60 dias
- [Conta Azul — Itaú](https://ajuda.contaazul.com/hc/pt-br/articles/115007756807-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-exportar-extrato-em-OFX-do-Ita%C3%BA) · [Nubank (só PJ)](https://ajuda.contaazul.com/hc/pt-br/articles/360052656371-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-exportar-extrato-em-OFX-do-Nubank) · [Stone](https://ajuda.contaazul.com/hc/pt-br/articles/26631121251085-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-exportar-extrato-da-Stone) · [Corrigir OFX importado](https://ajuda.contaazul.com/hc/pt-br/articles/7979561804941-Integra%C3%A7%C3%A3o-banc%C3%A1ria-via-OFX-como-corrigir-o-OFX-importado)
- [Nubank — Extrato OFX/PDF da conta PJ](https://blog.nubank.com.br/extrato-ofx-pdf-conta-pj-nubank/)
- [Reclame Aqui — C6 conta jurídica não tem extrato em formato OFX](https://www.reclameaqui.com.br/c6-bank/c6-conta-juridica-nao-tem-extrato-em-formato-ofx_ImI4qyqo50Rm6kNm/) — `[CONFLITANTE]`
- [Cora — Envie o extrato da sua conta Cora de forma automática](https://www.cora.com.br/blog/extrato-automatico-cora/) · [Nimbly — Como obter o Extrato OFX do Cora](https://blog.nimbly.com.br/internet-banking/como-obter-o-extrato-ofx-do-cora)
- [Stone — Central de Ajuda / Extrato](https://ajuda.stone.com.br/-extrato)
- [Asaas — Quais os formatos de extrato disponíveis](https://central.ajuda.asaas.com/hc/pt-br/articles/32058137017371-Quais-os-formatos-de-extrato-dispon%C3%ADveis) — ⚠️ fetch HTTP 403; lido via resultado de busca. PDF, xlsx, CSV, OFX, CNAB 240 v10.3
- [docs.asaas.com — Recuperar extrato (`GET /v3/financialTransactions`)](https://docs.asaas.com/reference/recuperar-extrato)
- [Inter — API Banking Empresas](https://inter.co/empresas/api-banking/) · [Inter — API para Conta Digital PJ](https://ajuda.bancointer.com.br/pt-BR/articles/4257003-o-inter-disponibiliza-alguma-api-para-minha-conta-digital-pj) · [Conta Azul — Cadastrar nova API do Inter](https://ajuda.contaazul.com/hc/pt-br/articles/9044458910093-Integra%C3%A7%C3%A3o-banc%C3%A1ria-autom%C3%A1tica-com-Inter-cadastrar-uma-nova-API) · [Omie — Extrato via API do Banco Inter](https://ajuda.omie.com.br/pt-BR/articles/11386318-configurando-a-integracao-com-o-banco-inter-extrato-via-api)
- [Snyk — ofxparse (MIT, inativa)](https://snyk.io/advisor/python/ofxparse) · [Snyk — ofxtools (GPL-3.0-only, inativa)](https://snyk.io/advisor/python/ofxtools) · [GitHub jseutter/ofxparse](https://github.com/jseutter/ofxparse) · [GitHub csingley/ofxtools](https://github.com/csingley/ofxtools) · [ofxtools docs](https://ofxtools.readthedocs.io/en/latest/)
- [Caixa — Manual de Leiaute CNAB 240 Extrato Eletrônico Para Conciliação Bancária (PDF)](https://www.caixa.gov.br/Downloads/extrato-eletronico-conciliacao-bancaria/Manual_de_Leiaute_CNAB_240_Extrato_Eletronico_Para_Conciliacao_Bancaria.pdf)
- [FEBRABAN — Layout padrão CNAB240 v10.11 (PDF)](https://cmsarquivos.febraban.org.br/Arquivos/documentos/PDF/Layout%20padrao%20CNAB240%20V%2010%2011%20-%2021_08_2023.pdf)

### Pix
- [RecargaPay — Extrato Pix](https://recargapay.com.br/pix/extrato-pix) — campos de identificação de pagador e recebedor
- [Kamino — Comprovante Pix](https://kamino.com.br/blog/recibo-e-comprovante-de-pagamento-comprovante-pix/) — requisitos mínimos do Bacen; E2E ID de 32 caracteres
- [Bradesco — Layout Recebimentos PIX (PDF)](https://wspf.banco.bradesco/wsValidadorUniversal/Content/Pdf/Layout_Recebimentos_Pix.pdf)

### Produtos comparáveis
- [TechRepublic — QuickBooks Online vs Solopreneur](https://www.techrepublic.com/article/quickbooks-online-vs-self-employed/) — `[CONFIRMADO]` Solopreneur **não tem** contas a pagar
- [Mission Accounting — Is QuickBooks Solopreneur Right for Your Small Business?](https://missionaccountinghelp.com/planning/business-planning/quickbooks-solopreneur)
- [QuickBooks — Solopreneur](https://quickbooks.intuit.com/solopreneur/) — bank feed automático
- [Expensent — QuickBooks Receipt Capture: 10 Methods Compared (2026)](https://www.expensent.com/guides/quickbooks-receipt-capture-methods)
- [Intuit Community — upload de recibo no Solopreneur](https://quickbooks.intuit.com/learn-support/en-us/reports-and-accounting/are-you-able-to-upload-expense-receipts-photos-into-a/00/1419337)
- [NerdWallet — QuickBooks Solopreneur (formerly Self-Employed) Review](https://www.nerdwallet.com/business/software/learn/quickbooks-self-employed)
- [Conta Azul — Conciliação bancária automática para PMEs](https://contaazul.com/funcionalidades/conciliacao-bancaria/) · [Manual completo para bater saldo](https://ajuda.contaazul.com/hc/pt-br/articles/7452788480141-Concilia%C3%A7%C3%A3o-banc%C3%A1ria-como-fazer) · [Resolver falhas na integração automática](https://ajuda.contaazul.com/hc/pt-br/articles/44330635640461-Concilia%C3%A7%C3%A3o-como-resolver-falhas-na-integra%C3%A7%C3%A3o-autom%C3%A1tica-banc%C3%A1ria)
- [Nibo — Conciliador Open Finance](https://ajuda.nibo.com.br/pt-BR/articles/10185495-saiba-tudo-sobre-o-nibo-conciliador-open-finance) · [Nibo — Conciliação bancária](https://ajuda.nibo.com.br/pt-BR/articles/6884846-conciliacao-bancaria)
- [Manio — Conta Azul, Omie, Nibo ou Planilha?](https://manio.app/pt/blog/conta-azul-omie-nibo-ou-planilha)
- [ZapGastos — Mobills ou Organizze](https://zapgastos.com/blog/mobills-ou-organizze/)

### Transferência entre contas / investimentos
- [Conta Azul — Lançamentos financeiros: como lançar transferência entre contas](https://ajuda.contaazul.com/hc/pt-br/articles/7454909121165-Lan%C3%A7amentos-financeiros-como-lan%C3%A7ar-transfer%C3%AAncia-entre-contas) — `[CONFIRMADO]` duas pernas; não é receita nem despesa; baixa automática na conciliação
- [Meu Dinheiro — Conceitos e operações de controle financeiro](https://docs.meudinheiroweb.com.br/perguntas-frequentes/conceitos-e-operacoes-de-controle-financeiro)
- [Finbits — Transferência entre contas](https://www.finbits.com.br/central-de-ajuda/transferencia-entre-contas)
- [IXC Soft — Transferência entre contas](https://wiki-erp.ixcsoft.com.br/documentacao/menu-sistema/financeiro/transferencia-entre-contas/transferencia-entre-contas.html) · [IXC — Lançar resgate, aplicação ou investimento pela conciliação bancária](https://wiki.ixcsoft.com.br/pt-br/Financeiro/Comolan%C3%A7aresgateaplica%C3%A7%C3%A3oouinvestimentoatrav%C3%A9sdaconcilia%C3%A7%C3%A3obanc%C3%A1ria)
- [Dominando a Contabilidade — Lançamento contábil de aplicações financeiras](https://dominandoacontabilidade.com/como-fazer-lancamento-contabil-de-aplicacoes-financeiras/)
- [Nexoos — Como funciona o resgate de investimento](https://www.nexoos.com.br/blog/resgate-de-investimento/) — cotização + liquidação

### Fontes internas (repositório, lidas em 2026-07-29)
`apps/api/app/modules/investments/models.py` (linhas 39-53) · `apps/api/app/modules/investments/service.py` (docstring, linhas 1-38) · `apps/api/app/modules/financial_intelligence/projection.py:177` · `apps/api/app/modules/wallet/service.py` · `apps/api/app/modules/payables/receipts.py` · `docs/decisions/0002-gateway-pagamento.md` · `CLAUDE.md` · `docs/research/2026-07-29-conta-bancaria-conciliacao-brainstorm.md`
