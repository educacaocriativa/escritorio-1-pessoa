# Vima: voz na entrada (self-chat, Evolution) — terceira fatia do caminho até o Jarbes

## Por que existe

A primeira fatia (`docs/superpowers/specs/2026-08-28-vima-pergunte-design.md`, PR #266) provou o
motor de pergunta-e-resposta em texto, dentro do app. A segunda (`docs/superpowers/specs/2026-08-28-vima-canal-whatsapp-design.md`,
PR #268) moveu esse motor para a self-chat do WhatsApp, mas só reconhece
`msg.kind == KIND_TEXT` — mensagem de voz na mesma self-chat cai no caminho normal de mídia
(silenciosa para a Vima) e o próprio comentário no call site já marcava isso como "ponto de
extensão da fatia de voz". Esta é essa fatia: o dono manda uma nota de áudio para o próprio
número conectado, a Vima transcreve e responde exatamente como responderia a texto.

**Só entrada.** A Vima continua respondendo em TEXTO. Saída por voz (TTS) fica para uma fatia
futura — depende de decisão de provedor e custo próprios, sem relação com a de transcrição.

## Escopo desta fatia

- **Canal:** self-chat no WhatsApp, exclusivamente Evolution — mesma restrição estrutural da
  fatia anterior (`from_me` só existe lá).
- **Gatilho:** mensagem de ÁUDIO (`kind == KIND_AUDIO`) na mesma self-chat que hoje só aceita
  texto. Sem palavra-chave, sem opt-in novo — mesma disciplina da fatia de texto.
- **Motor de resposta:** inalterado. A transcrição vira o `texto` que seguiria o caminho normal
  de `vima/pergunta.responder` — mesmas ferramentas, mesmo filtro de permissão, mesmo cache de
  histórico em `whatsapp_conversa.py`.
- **Novo componente:** `core/transcription.py` — ponto único de acesso à Groq (Whisper), no
  mesmo espírito de `core/ai.py` ser o ponto único de acesso à Anthropic. Isto é o SEGUNDO
  provedor de IA que o repositório passa a ter (hoje é só Anthropic).
- **Eco da transcrição:** a resposta final inclui o que a Vima entendeu ter sido perguntado,
  antes da resposta em si. Sem isso, um erro de transcrição vira resposta certa para a pergunta
  errada, e o dono não tem como saber — ele nunca vê o texto transcrito em lugar nenhum.

## Por que um provedor novo, e por que Groq

A API de mensagens da Anthropic não aceita áudio como entrada (texto, imagem, PDF — não voz).
Transcrição exige um provedor de STT (speech-to-text) dedicado. Escolhido: **Groq**, rodando o
modelo Whisper — mesma família de modelo de OpenAI/self-hosted, hospedada pela Groq (mais
barata e mais rápida que a OpenAI para este caso de uso; decisão do dono do produto).

Isto quebra a garantia implícita de `core/ai.py` ("Camada única de acesso à IA (Claude)") — a
partir desta fatia essa frase deixa de ser verdadeira para o repositório inteiro, só para o
caminho de TEXTO. `core/transcription.py` é deliberadamente um módulo IRMÃO, não uma extensão
de `core/ai.py`: são provedores diferentes, com formas de cobrança diferentes (tokens vs.
segundos de áudio), e misturar as duas API keys num módulo só criaria acoplamento sem ganho.

## Fluxo

1. Webhook da Evolution entrega a mensagem de áudio. `media_bytes`/`media_mime_type` já chegam
   decodificados no parse do provider (`core/whatsapp/providers/evolution.py`) — sem fetch
   adicional, ao contrário do caminho Meta. O processamento continua **síncrono, dentro do
   próprio webhook**, mesma decisão da fatia de texto (uma resposta atrasada mata a sensação de
   conversa).
2. `whatsapp_inbox/service.py`: a condição de self-chat (`msg.from_me and da_equipe and
   msg.kind == KIND_TEXT`) passa a aceitar também `msg.kind == KIND_AUDIO`.
3. `vima/whatsapp_conversa.responder()` ganha um parâmetro opcional para os bytes/mime de áudio.
   Quando presente, chama `transcription.transcribe(db, tenant_id=..., user_id=...,
   audio_bytes=..., mime_type=...)` **antes** de tudo o mais.
   - **Transcrição vazia ou erro da Groq:** mesma disciplina de "falha nunca fica muda" já
     documentada na fatia anterior — envia a mesma mensagem de desculpa
     ("Não consegui responder agora — tenta de novo em instantes.") pelo mesmo canal, sem
     chamar `pergunta.responder`.
   - **Transcrição OK:** o texto resultante segue o MESMO caminho que uma mensagem de texto
     seguiria — grava turno no histórico, chama `pergunta_service.responder`, grava a resposta.
4. Resposta final ecoa a pergunta entendida: `🎤 "{transcrição}" — {resposta da Vima}`.
5. `GROQ_API_KEY` ausente: degrada como o `ANTHROPIC_API_KEY` ausente degrada hoje em
   `vima/pergunta.py` — mensagens de áudio recebem a desculpa padrão; mensagens de TEXTO na
   mesma self-chat continuam funcionando normalmente (as duas chaves são independentes).

## Ledger de uso (`ai_usage`)

`AIUsage` hoje assume implicitamente um único provedor (Anthropic): `input_tokens`/
`output_tokens`/`cache_read_tokens`/`cache_creation_tokens` são conceitos de cobrança da
Anthropic, e não existe coluna `provider`. A Groq cobra por SEGUNDO de áudio, não por token —
forçar a duração num desses campos inventaria um significado que a coluna nunca teve
(Artigo IV — No Invention).

Migration nova:
- `provider: String, nullable=False, default='anthropic', server_default='anthropic'` — backfill
  automático de toda linha existente, zero mudança de comportamento para o caminho Anthropic.
- `audio_seconds: Float, nullable=True` — preenchido SÓ em linhas de transcrição; `NULL` em
  toda linha Anthropic, presente e não-nulo em toda linha Groq. Nunca os dois ao mesmo tempo.

Nova tarefa no vocabulário de `task`: `vima.transcricao`. `model` grava o nome real do modelo
que rodou na Groq (ex.: `whisper-large-v3`), na mesma disciplina de "o modelo que REALMENTE
rodou, não o configurado" que `core/ai.py` já segue. `core/transcription.transcribe` chama
`ai_usage.record` diretamente (mesma função, provider diferente) — não duplica a lógica de
`begin_nested`/best-effort que já existe lá.

`core/transcription.py` reproduz a MESMA obrigatoriedade de `core/ai.py`: `db` e `tenant_id`
são parâmetros obrigatórios da função pública, para que seja estruturalmente impossível chamar
a Groq sem contabilizar (mesmo argumento do docstring de `core/ai.py`, item 1).

## PII — decisão que precisa de aceite explícito, não herdada por analogia

A fatia de texto (2026-08-28) estende, para os RESULTADOS de ferramenta (nome de cliente,
valor, data), o risco de PII já aceito pelo fundador em 2026-07-11 para o Diagnóstico
Financeiro — mas aquilo é dado ESTRUTURADO (nome, número), que em tese poderia um dia ganhar
NER e voltar a ser mascarado.

Áudio bruto é uma categoria diferente: **não existe anonimização de voz**. A gravação inteira —
tom, sotaque, tudo que o dono disse, inclusive qualquer nome ou valor falado — sai para a Groq
sem nenhum tratamento. Isto não é uma extensão do risco de 2026-07-11; é uma decisão NOVA, e
fica registrada aqui como tal:

> ⚠️ **Decisão aceita para esta fatia:** o áudio da pergunta é enviado à Groq sem qualquer
> anonimização. A Groq processa a transcrição e (pela política padrão de provedores de STT
> comparáveis) não usa o áudio para treinar modelos, mas o dado passa por infraestrutura de
> terceiro fora do controle do e1p. Aceito porque a alternativa (self-hosted) foi descartada
> nesta fatia por custo de infraestrutura, e o valor da voz como canal justifica o risco na
> visão do dono do produto.

O ÁUDIO em si nunca é persistido — nem no banco, nem em disco, nem em cache além da chamada
síncrona à API da Groq. A TRANSCRIÇÃO (texto) segue exatamente a mesma disciplina de zero
persistência que a pergunta digitada já segue hoje.

## Fora de escopo (declarado, não esquecido)

- **Saída de voz (TTS).** A resposta da Vima continua sempre em texto. Fica para fatia futura,
  com decisão de provedor própria.
- **Ativação por palavra-chave.** Toda mensagem — texto OU áudio — na self-chat é pergunta, sem
  mudança nesta fatia.
- **Persistência de áudio ou de transcrição**, permanente ou temporária, além do cache curto em
  processo que `whatsapp_conversa.py` já mantém para o TEXTO da transcrição (mesmo TTL, mesmo
  mecanismo — a transcrição entra no histórico como se fosse um turno digitado).
- **Limite de duração/tamanho de áudio.** A API da Groq tem um teto de tamanho de arquivo; esta
  fatia não adiciona validação própria antes de enviar — um áudio acima do limite simplesmente
  falha na chamada e cai no caminho de erro já descrito (desculpa padrão).
- **Mídia fora da self-chat** (áudio de cliente, no funil normal) — comportamento inalterado,
  continua sem transcrição, como hoje.
- **Outros idiomas além de português** — sem tratamento especial; o que a Groq detectar/
  transcrever é o que segue adiante.

## Testes

- `test_vima_whatsapp_evolution.py` (ou arquivo novo dedicado): mock de `transcription.transcribe`
  — caminho feliz (áudio → texto → resposta com eco), erro da Groq (desculpa padrão, sem chamar
  `pergunta.responder`), `GROQ_API_KEY` ausente (mesmo caminho de erro).
- Teste de unidade para `core/transcription.py`: grava linha em `ai_usage` com `provider='groq'`
  e `audio_seconds` preenchido; confirma que uma chamada Anthropic concorrente continua gravando
  `provider='anthropic'` com `audio_seconds=NULL`.
- Migration: teste de que o backfill de `provider='anthropic'` não quebra nenhuma leitura
  existente de `ai_usage` (mesmo padrão de teste de migration já usado no repositório).
- RLS: sem teste novo — o caminho reusa `pergunta.responder` por inteiro, já coberto por
  `test_vima_tools_rls.py`.
