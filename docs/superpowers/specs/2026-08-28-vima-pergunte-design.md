# Vima: perguntar e receber resposta (primeira fatia do caminho até o Jarbes)

## Por que existe

A visão de longo prazo é uma Vima quase autossuficiente, interagível por voz, que ajuda o dono a
administrar o negócio. Hoje ela só **empurra**: o briefing agendado (`vima/composer.py` +
`narrator.py`) narra fatos e ausências já calculados, numa hora fixa, e o dono não tem como
perguntar nada de volta — não existe loop de conversa em lugar nenhum do produto.

Esta fatia é o primeiro passo nessa direção, e é deliberadamente estreita: **o dono pergunta em
texto, dentro do app, e a Vima responde consultando os dados reais.** Sem voz (isso pede
speech-to-text/text-to-speech, fatia separada), sem WhatsApp (a mensagem do dono para o próprio
número conectado colide com o pipeline de conversa de CLIENTE em `whatsapp_inbox` — decidir essa
ambiguidade de roteamento é decisão própria, não deste documento), sem persistência entre sessões.

O que esta fatia prova é o mecanismo central que tudo o que vem depois depende: **a IA decidindo
qual dado consultar e narrando o resultado, nunca calculando o número ela mesma.** É a mesma
disciplina que already rege o resto do produto (Epic 8 Regra 4 — "regra determinística primeiro,
IA narrando depois"; a docstring de `vima/absences.py` — "a IA só NARRA, nunca origina número").

## Escopo desta fatia

- **Canal:** chat dentro do app (nova tela web), não WhatsApp. Decisão do fundador: WhatsApp é a
  visão final, mas hoje o número conectado do tenant já serve para conversas de CLIENTE — usar o
  mesmo canal para "o dono fala com a Vima" exige resolver essa ambiguidade de roteamento primeiro,
  e essa é uma fatia própria, futura.
- **Domínios respondíveis:** Financeiro (recebíveis, pagáveis, projeção de caixa), Agenda
  (compromissos) e CRM (clientes) — os três já têm serviço de leitura pronto e são os que o
  briefing já narra hoje.
- **Persistência:** nenhuma. O histórico da conversa vive só no estado do React enquanto a tela
  está aberta; recarregar a página começa do zero. Sem migration, sem tabela nova.
- **PII:** a pergunta do dono e os resultados das ferramentas (nome de cliente, valor, data)
  chegam à Claude **sem** anonimização de nome — extensão explícita do risco aceito pelo fundador
  em 2026-07-11 para o Diagnóstico Financeiro (ver CLAUDE.md §6.1, "Anonimizador sem NER"). PII
  **estrutural** (CPF/CNPJ/e-mail/telefone) continua passando pelo `core/anonymizer` normalmente —
  Regra de Ouro nº 2 não muda.

## Fora de escopo (declarado, não esquecido)

- Voz (entrada ou saída).
- WhatsApp como canal de pergunta.
- Histórico persistido / retomar conversa em outra sessão.
- Ações (a Vima só LÊ nesta fatia — nenhuma ferramenta escreve nada).
- Domínios fora de Financeiro/Agenda/CRM (Jurídico, Marketing, Funis, Estoque, etc.).
- Hardening do anonimizador para nome livre (NER) — dívida pré-existente, não desta fatia.

## Arquitetura

Um endpoint novo, `POST /vima/pergunta`, roda um **loop de tool-use da Anthropic**: a Claude
recebe a pergunta (+ os turnos recentes que o front reenvia, já que não há persistência) e uma
lista de ferramentas de leitura; ela escolhe quais chamar (zero, uma ou várias), o backend as
executa contra a sessão de banco **já** escopada por tenant do próprio request, devolve o
resultado, e a Claude compõe a resposta final em texto. Nenhum número é calculado pela Claude —
todo valor vem de um serviço determinístico que já existe.

```
dono digita pergunta
        │
        ▼
POST /vima/pergunta {pergunta, historico[]}
        │
        ▼
loop de tool-use (novo, vima/pergunta.py)
        │
        ├─ Claude escolhe ferramenta(s) ──► executa contra o db da request (RLS já vale)
        │                                        │
        │        ◄─── resultado da ferramenta ───┘
        │
        ▼
Claude compõe a resposta em texto
        │
        ▼
{resposta} ──► front exibe na conversa
```

## Backend

### Ferramentas (v1 — uma por domínio acordado)

| Ferramenta | Domínio | Wrapper de |
|---|---|---|
| `consultar_recebiveis` | Financeiro | `receivables` (resumo/lista: em aberto, vencido, por período) |
| `consultar_pagaveis` | Financeiro | `payables` (resumo/lista) |
| `consultar_projecao_caixa` | Financeiro | `financial_intelligence/projection.py` |
| `consultar_agenda` | Agenda | `agenda` (compromissos por dia/período) |
| `consultar_cliente` | CRM | `crm` (busca por nome) + `facts` (timeline/última interação) |

Cada ferramenta roda dentro da sessão de banco **da própria request** — a mesma que qualquer outro
endpoint já usa. Nenhuma query nova escapa da RLS; nenhum filtro manual de tenant é escrito
(Regra de Ouro nº 1 continua valendo sem exceção).

### O loop é código novo, não um reuso de `ai.complete`

`core/ai.complete` hoje é uma chamada de completude única (system + uma mensagem) — não tem noção
de turnos de ferramenta. O loop de tool-use é uma função nova, iniciada dentro de
`app/modules/vima/pergunta.py` (só promovida para `core/ai` se e quando um segundo consumidor
aparecer — desenhar a abstração compartilhada contra uma população de um é o erro que este
documento evita cometer). Ela:

1. Monta a lista de ferramentas **filtrada por `allowed_modules`** do usuário da request — a
   mesma decisão já tomada pelo briefing ("o filtro de permissão decide quais REGRAS RODAM, não
   quais resultados aparecem"). Um sub-usuário sem o módulo `financeiro` nunca vê
   `consultar_recebiveis` na lista oferecida à Claude.
2. Chama a Anthropic com a pergunta + histórico recente + ferramentas.
3. Para cada tool call que a Claude pedir: executa o wrapper correspondente, captura erro se
   houver (nunca deixa a exceção subir crua), devolve o resultado (ou o erro) como tool result.
4. Repete até a Claude parar de pedir ferramentas ou até um **teto de turnos** (5–6, no espírito
   da guarda anti-ciclo de 100 passos do motor de funis) — estourar o teto devolve a melhor
   resposta parcial com uma nota de que parou, nunca trunca em silêncio.
5. Grava no ledger `ai_usage` (mesma tabela, mesma disciplina `db`/`tenant_id`/`task`
   obrigatórios) — tokens **somados de todos os turnos** do loop, não só do último.

### Roteamento de modelo

Nova tarefa `vima.pergunta` em `MODELO_POR_TAREFA` → **`claude-sonnet-5`**. A tarefa não é só
narração (que já usa haiku em `vima.briefing`): aqui a Claude também **decide qual ferramenta
chamar**, e uma escolha errada produz uma resposta errada, não só mal escrita — o mesmo critério
("custo do erro, não tamanho do texto") que já rege o resto do arquivo.

### Anonimização

O `user_message` que sai para a Claude passa pelo `core/anonymizer` como qualquer chamada de IA do
produto (Regra de Ouro nº 2) — o que muda é só que o anonimizador **não mascara nome próprio hoje**
(dívida pré-existente, documentada em CLAUDE.md §6.1), e esta fatia estende o aceite de risco já
dado pelo fundador em 2026-07-11 em vez de inventar um novo. Nenhuma mudança no anonimizador faz
parte desta fatia.

## Frontend

Rota nova `/vima/perguntas`, dentro do `ProtectedLayout` normal (sidebar/topbar — ao contrário do
Briefing e do Núcleo do DNA, que rodam em `ProtectedBareLayout`; esta tela não é porta de entrada
do dia, é destino de navegação), com item de menu perto das entradas já existentes da Vima.

Componente: lista de mensagens + campo de texto. O estado da conversa vive só no React (`useState`
local) — sem `localStorage`, sem chamada de leitura ao abrir a tela. Cada envio manda a pergunta +
os turnos recentes da conversa atual para o backend. Indicador de carregamento enquanto o loop de
ferramentas roda no servidor (pode levar alguns segundos); estado de erro inline se a request
falhar.

**Medida em ~360px desde o primeiro PR**, como toda tela nova deste repositório: `textoForaDaTela`,
`alvosPequenos`, `controlesInalcancaveis` de `e2e/support/medidas.ts`, com fixture de pior caso
(nome de cliente comprido, valor de 6 dígitos) — nunca por classe CSS.

## Tratamento de erro e degradação

- **Sem `ANTHROPIC_API_KEY`:** mesma forma de degradação graciosa do Diagnóstico/Jurídico — a
  tela mostra que o recurso está indisponível, não quebra.
- **Ferramenta levanta exceção:** capturada, devolvida à Claude como resultado de erro; a Claude é
  instruída a dizer que não conseguiu consultar aquilo, nunca a inventar um número.
  Artigo IV (No Invention) da Constitution vale aqui como em qualquer outro lugar do produto.
- **Teto de turnos estourado:** resposta parcial + aviso de que parou, nunca truncamento silencioso
  (mesmo princípio do `limit: 500` do endpoint de agenda documentado em CLAUDE.md).

## Testes

- **Backend:** um teste por ferramenta (delega para o serviço certo, respeita o filtro de
  `allowed_modules`); o loop testado com o cliente Anthropic mockado (`lambda **kw`, mesmo padrão
  dos narradores existentes — nenhum teste deve chamar a API de verdade); um teste `rls_e2e`
  provando que uma ferramenta nunca devolve dado de outro tenant, mesmo que a Claude seja induzida
  a pedir por um id que não é dela.
- **Frontend:** vitest do componente de chat (estado de conversa, envio, erro) + o spec e2e de
  360px obrigatório de toda tela nova deste repositório.

## Dívida (declarada, não desta fatia)

- WhatsApp como canal de pergunta — pede resolver a ambiguidade de roteamento com
  `whatsapp_inbox` primeiro.
- Voz (STT/TTS) — próxima fatia depois desta e da de WhatsApp.
- Persistência de conversa entre sessões.
- Hardening do anonimizador para nome próprio (NER) — dívida pré-existente que esta fatia estende
  o aceite de risco em vez de fechar.
- Ações da Vima (hoje só lê) — quando existir, precisa do rastro de auditoria "Ação executada pela
  IA" (Regra de Ouro nº 3), que uma ferramenta só de leitura não precisa.
