# Vima: canal WhatsApp (self-chat, Evolution) — segunda fatia do caminho até o Jarbes

## Por que existe

A primeira fatia (`docs/superpowers/specs/2026-08-28-vima-pergunte-design.md`, PR #266) provou o
mecanismo central — a Claude escolhendo qual ferramenta consultar e narrando o resultado — mas
só dentro do app, em texto. A visão de longo prazo é voz, e voz precisa de um canal que já
existe fora do navegador. O WhatsApp é esse canal: é onde o dono já recebe o briefing hoje.

Esta fatia é o passo estrutural entre "responder no app" e "responder por voz": deixa o dono
perguntar à Vima pelo MESMO número de WhatsApp que ele já conectou via QR code (Evolution),
sem construir nenhuma peça nova do motor de resposta — reusa `vima/pergunta.responder`
integralmente. O que muda é só a porta de entrada e saída.

## Escopo desta fatia

- **Canal:** WhatsApp, exclusivamente para tenants no transporte **Evolution** (QR code). Meta
  fica de fora — ver "Por que Evolution-only" abaixo.
- **Gatilho:** self-chat — o dono manda mensagem para o próprio número conectado (o recurso
  "Mensagens para você mesmo" que o WhatsApp já oferece nativamente). Toda mensagem de TEXTO
  ali vira pergunta à Vima; não há palavra-chave de ativação.
- **Motor:** o MESMO `vima/pergunta.responder` da primeira fatia — mesmas cinco (agora nove,
  contando a fatia de domínios em paralelo) ferramentas, mesmo filtro de permissão por
  `allowed_modules`, mesma tarefa `vima.pergunta` roteada para `claude-sonnet-5`, mesma decisão
  de PII (risco aceito estendido de 2026-07-11). Nada disso muda nesta fatia.
- **Contexto entre mensagens:** cache curto em memória (minutos, não permanente) por
  `tenant_id`+telefone, para perguntas de acompanhamento ("e essa semana?") funcionarem sem
  precisar repetir tudo.
- **Sem persistência:** a conversa NUNCA toca `whatsapp_chats`/`whatsapp_messages` nem o CRM —
  consistente com a decisão da primeira fatia (zero histórico permanente), e evita por
  construção a classe de bug "o dono vira lead do próprio funil" que `_e_telefone_da_equipe`
  já existe para prevenir no caminho normal.

## Por que Evolution-only

O sinal que torna esta fatia possível — `InboundMessage.from_me`, que o Baileys popula porque
ele espelha como evento de entrada tudo que é digitado no aparelho conectado, inclusive numa
self-chat — **só existe no Evolution**. Na Meta Cloud API o campo `messages` do webhook nunca
contém as próprias mensagens enviadas pelo negócio (só `statuses`), e o dono do lado Meta
responde a partir do PRÓPRIO número pessoal, não "a mesma linha" — não existe self-chat com o
número do negócio no modelo da Meta. Não há como replicar esta UX lá sem uma abordagem
inteiramente diferente (provavelmente um comando/template específico), que fica fora desta
fatia. A produção real do fundador já está no Evolution.

## Detecção e roteamento

Dentro de `whatsapp_inbox/service.py::ingest_webhook_payload`, cada mensagem já passa por
`_e_telefone_da_equipe(db, tenant_id, msg.from_phone)` — um lookup contra `User.phone` de
qualquer usuário ativo do tenant, hoje usado para não criar contato de CRM quando quem escreve
é o próprio time. Numa self-chat, as DUAS pontas da conversa são a mesma pessoa: `from_me=True`
(escrito no aparelho conectado) E o `from_phone` (a contraparte, que numa self-chat é o próprio
número do dono) bate com um telefone cadastrado. **`from_me AND da_equipe` isola exatamente a
self-chat**, sem precisar de nenhum dado novo — as duas peças já existem, só nunca foram
combinadas para decidir roteamento de conteúdo.

Mensagem de mídia (áudio, imagem) no mesmo self-chat cai no comportamento ATUAL, inalterado —
e é o ponto de extensão natural quando a fatia de voz (entrada) chegar: trocar `kind == "text"`
por também aceitar `kind == "audio"` e transcrever antes de repassar ao mesmo
`pergunta.responder`.

Quando a condição bate: a mensagem NÃO segue o caminho normal (nada de
`_get_or_create_chat`/`_get_or_create_client`/`facts.record`). Em vez disso, resolve o `User`
que casou o telefone (precisa de uma variante de `_e_telefone_da_equipe` que devolva a linha,
não só o booleano — hoje ela só devolve `bool`), monta o `CurrentUser` equivalente a partir
dele, chama `pergunta.responder` com o histórico do cache, e manda a resposta de volta pelo
MESMO despachante que já entrega o briefing (`core/whatsapp` → provider Evolution → mesma
instância `e1p-{tenant_id}`).

**Pré-condição que fica registrada, não escondida:** a detecção só funciona se o número
conectado via QR code estiver TAMBÉM cadastrado em `User.phone` de algum usuário ativo do
tenant — hoje é o mesmo campo que já alimenta a entrega do briefing por WhatsApp, então quem
já usa aquele recurso já satisfaz a pré-condição. Quem nunca configurou o próprio telefone no
perfil simplesmente não aciona nada (a mensagem cai no comportamento atual, sem erro, sem
sinal — é uma pré-condição de configuração, não uma falha).

## Contexto de sessão e deduplicação

Um cache curto, em processo (não uma tabela nova), guarda por `tenant_id`+telefone: (a) os
últimos turnos da conversa, para perguntas de acompanhamento, com expiração de poucos minutos;
(b) os `wa_message_id` processados recentemente, porque sem gravar a mensagem em
`whatsapp_messages` perdemos de graça a proteção natural contra reentrega de webhook que
aquela tabela já dava a todo o resto do módulo — uma reentrega do Evolution não pode gerar
duas respostas.

⚠️ **Limite conhecido, aceito para esta fatia:** cache em processo não sobrevive a reiniciar o
processo nem se comporta corretamente sob múltiplas réplicas da API. Para a escala atual (um
processo, um tenant real em produção) isso é aceitável; se a escala mudar, o cache migra para
Redis (já presente na infraestrutura do Evolution) — decisão adiada até haver necessidade real
de medir, não construída especulativamente agora.

## Entrega e tratamento de erro

A resposta sai pelo MESMO caminho que o briefing (`core/whatsapp` → Evolution → mesma
instância). Processamento é **síncrono, dentro do próprio handler do webhook** — não entra na
fila do worker: uma resposta que só chega minutos depois (esperando o próximo sweep) mata a
sensação de conversa que essa fatia existe para criar. O custo aceito é que uma chamada de IA
lenta pode aproximar o timeout do webhook do Evolution; mitigado pela deduplicação acima (uma
reentrega não duplica a resposta) e pelo teto de rodadas que `ai.complete_with_tools` já impõe
desde a primeira fatia.

**Falha nunca fica muda.** O resto de `whatsapp_inbox` hoje engole erro em `except Exception`
amplo (dívida já registrada no CLAUDE.md — mídia perdida sem sinal ao dono). Esta fatia NÃO
herda esse silêncio: uma falha ao chamar `pergunta.responder` ou ao enviar a resposta é
capturada explicitamente e uma mensagem curta ("não consegui responder agora") volta ao dono —
sem isso, ele não teria como saber se a pergunta chegou.

## Fora de escopo (declarado, não esquecido)

- Meta como transporte (sem `from_me`, sem self-chat possível no modelo da Meta).
- Entrada por voz (nota de áudio) — o ponto de extensão fica marcado (`kind == "audio"`), a
  transcrição em si não é desta fatia.
- Saída por voz (resposta em nota de áudio).
- Ativação por palavra-chave (decisão: toda mensagem de texto no self-chat é pergunta).
- Persistência de qualquer tipo da conversa — nem cache permanente, nem tabela nova.
- Ações da Vima (esta fatia, como a primeira, só lê).

## Testes

- Unitário: a condição de roteamento (`from_me AND da_equipe AND kind=="text"`) isolada, com
  os quatro quadrantes (self-chat / dono respondendo cliente pelo celular / cliente comum /
  mídia em self-chat) — cada um caindo no caminho certo.
- Unitário: a variante de `_e_telefone_da_equipe` que devolve o `User`, não só o booleano —
  garantindo que o comportamento ATUAL (booleano) não muda para os call sites existentes.
- Unitário: o cache de contexto e o de deduplicação, isolados (TTL, expiração, hit/miss).
- Integração: `ingest_webhook_payload` com um payload de self-chat mockando
  `pergunta.responder` — prova que NENHUMA linha é gravada em `WhatsappChat`/`WhatsappMessage`/
  `Client`/`facts` para esse caminho, e que o texto de resposta é enviado ao número certo.
- Integração: falha no meio do caminho (responder levanta, envio falha) — prova que a mensagem
  de erro chega ao dono, nunca silêncio.
- RLS: não é necessária uma prova nova — o caminho reusa `pergunta.responder`/`tools.executar`,
  já cobertos pela prova RLS da primeira fatia; esta fatia não introduz consulta nova.
