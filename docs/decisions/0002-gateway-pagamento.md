# ADR 0002 — Gateway de pagamento (boleto/Pix registrado + webhook)

- **Status:** Aceito
- **Data:** 2026-07-11
- **Autor:** Aria (@architect) — ratificação do quality gate do Epic 2, Story 2.2
- **Relacionado:** [ADR 0001](0001-stack-e-infra.md), `docs/stories/2.2.story.md`, `docs/prd/epic-2-integracoes-reais.md`

## Contexto

O e1p precisa gerar **boleto/Pix registrado de verdade** (hoje `core/boleto.py` é um layout-stub
sem registro bancário) e **receber o webhook real de compensação** que credita a Carteira com o
split 40/30/20. O Epic 2 exigiu explicitamente que a escolha do gateway fosse "formalizada em ADR
no início do épico".

Na implementação (modo autônomo, sem poder bloquear numa pergunta ao usuário), o @dev tomou um
`[AUTO-DECISION]` provisório escolhendo **Asaas** e desenhou a integração como *adapter atrás de
uma interface própria* (`core/payment_gateway.py`), pedindo que o @architect criasse este ADR
ratificando ou revertendo a escolha. Este documento é essa ratificação.

Restrições de contexto que pesam na decisão:
- **Custo baixo** é regra de ouro (nº 4 do CLAUDE.md) — SaaS de "empresa de 1 pessoa", margem fina.
- **Boleto + Pix registrados** num único fluxo, com CPF/CNPJ do pagador (cliente do CRM).
- **Split** é feito internamente pela Carteira (`wallet.build_transaction`), **não** delegado ao
  gateway — logo NÃO dependemos do split nativo do provedor (isso amplia o leque de escolhas e
  reduz o lock-in).
- **Isolamento de tenant** (regra de ouro nº 1): a correlação webhook→cobrança não pode introduzir
  consulta global sem RLS.
- Público-alvo: micro/pequenos negócios brasileiros (PF/PJ simples), não e-commerce de alto volume.

## Decisão

**Ratificado: Asaas** como gateway de pagamento inicial do e1p, atrás do adapter
`core/payment_gateway.py` (contrato `create_registered_charge(...) -> GatewayChargeResult`).

Racional:
1. **API única para boleto + Pix registrados.** Um único `POST /payments` com `billingType`
   BOLETO/PIX cobre os dois métodos que o produto precisa hoje, com endpoints auxiliares para a
   linha digitável (`/identificationField`) e o copia-e-cola (`/pixQrCode`). Menos superfície de
   integração que orquestrar dois produtos distintos.
2. **`externalReference` nativo** permite correlacionar a cobrança sem expor `tenant_id`/`charge_id`
   como chaves previsíveis ao provedor — encaixa exatamente na estratégia de embutir
   `f"{tenant_id}:{charge_id}"` e resolver o webhook **sem consulta global sem RLS** (regra de ouro
   nº 1). Esta é a razão arquitetural mais forte a favor: a alternativa (lookup global
   `charge_id → tenant_id`) criaria uma query fora da RLS, o padrão que mais tememos.
3. **Custo fixo baixo / sem mensalidade** e tarifa por transação competitiva para boleto/Pix —
   alinhado à regra de ouro nº 4. Não introduz custo parado (coerente com a filosofia de infra do
   ADR 0001).
4. **Não dependemos do split nativo do gateway** — o split 40/30/20 já é resolvido pela Carteira na
   baixa. Isso reduz o lock-in: o adapter só precisa de "cria cobrança registrada" + "me avisa quando
   pagou", que qualquer gateway brasileiro oferece.
5. **Sandbox disponível** (`api-sandbox.asaas.com`) para validação antes do go-live, via
   `PAYMENT_GATEWAY_BASE_URL` — sem trocar código.

## Alternativas consideradas e rejeitadas (por ora)

- **Mercado Pago:** maior marca e cobertura de meios de pagamento (cartão/carteira digital), mas a
  API de boleto/Pix registrado é mais fragmentada (produtos "Checkout"/"Payments" distintos) e o
  peso do SDK/fluxo é maior do que o e1p precisa hoje. Fica como **fallback natural**: o adapter
  isola o provedor num único módulo, então migrar é trocar `core/payment_gateway.py` +
  `payment_gateway_provider`, sem tocar em `receivables/service.py` nem no contrato do webhook.
- **Pagar.me / Stripe / gateway de adquirência direta:** Stripe tem suporte fraco/indireto a boleto
  e Pix para o público BR de micro-negócio; adquirência direta exige contratos e KYC pesados,
  desproporcionais ao estágio do produto.
- **Manter só o stub (não integrar agora):** rejeitado — o Epic 2 é justamente "dinheiro entra de
  verdade"; sem gateway registrado o boleto não é pagável no banco.

## Consequências

- **Adapter obrigatório (baixo acoplamento):** nenhuma parte de `receivables` fala com o SDK/HTTP do
  Asaas diretamente — só com `core/payment_gateway.py`. Trocar de provedor = reescrever um módulo.
  Esta propriedade é uma **precondição da ratificação**, não um detalhe: é o que torna a decisão
  reversível a baixo custo.
- **Graceful degradation inclusive em produção:** sem `PAYMENT_GATEWAY_API_KEY`, o sistema mantém o
  boleto stub (diferente de `JWT_SECRET`/`ANTHROPIC_API_KEY`, que são bloqueantes). Decisão de
  produto registrada no epic — o gateway é opcional/faseável, não bloqueia o deploy.
- **Correlação via `externalReference` = `tenant_id:charge_id`.** O webhook resolve o tenant fazendo
  o parse desse campo — nunca confia num `tenant_id` vindo solto do payload do provedor e nunca faz
  lookup global sem RLS.
- **Idempotência preservada:** o webhook reusa `mark_paid()` (SELECT ... FOR UPDATE + early-return
  em `status=PAID`), então reenvios at-least-once do Asaas não geram dupla baixa/dupla receita.
- **Segurança do webhook (dinheiro real):** ver seção abaixo — condições que DEVEM ser satisfeitas
  antes do go-live.
- **Pendências de No Invention (Article IV) — RESOLVIDO em 2026-07-12 para o lado de SAÍDA
  (criar cobrança):** validado contra o sandbox real (`api-sandbox.asaas.com`, conta "FLAVIO KATO
  LTDA") — `POST /customers`, `POST /payments` (boleto E Pix) e `GET /payments/{id}/pixQrCode`
  responderam `200` reais; header `access_token` (não `asaas-access-token`) confirmado como o
  mecanismo de auth correto para essas chamadas; `bankSlipUrl`/linha digitável/copia-e-cola
  retornados no formato esperado pelo adapter. **RESOLVIDO em 2026-07-12 também para o lado de
  ENTRADA (webhook):** com autorização explícita do usuário, exposta a API local via túnel
  temporário (`cloudflared`, `trycloudflare.com`, sem conta, encerrado ao fim do teste), registrado
  um webhook real (`POST /v3/webhooks`) apontando pro túnel, e disparado `POST
  /v3/sandbox/payment/{id}/confirm` (endpoint sandbox-only) sobre uma cobrança criada pelo fluxo
  real do produto (`receivables.create_charge`). Capturada a requisição real da Asaas: header
  **`asaas-access-token`** confirmado byte-a-byte (bate com o que o código já esperava — nenhuma
  mudança de código necessária), payload `{event: "PAYMENT_RECEIVED", payment: {externalReference,
  ...}}` confere com a doc pública. Processamento validado ponta a ponta: cobrança marcada `paid`,
  split de 30% (serviço) aplicado corretamente na Carteira (R$33,00 → R$9,90 taxa → R$23,10
  disponível). Webhook de teste e túnel removidos após a validação (não deixam rastro
  permanente). `GATEWAY_WEBHOOK_SECRET` real gerado e configurado no `.env` local para uso
  contínuo em dev.

## Segurança do webhook — condições de go-live (revisão do quality gate)

Como é **dinheiro entrando no sistema**, o gate exige que, ao configurar o provedor em produção:

1. **`GATEWAY_WEBHOOK_SECRET` DEVE ser definido em produção.** Com o segredo vazio o webhook fica
   **aberto** (comportamento de dev, para o link "simular pgto"). Em produção vazio = qualquer um
   que conheça a URL pode marcar cobranças como pagas. Recomenda-se elevar isto de convenção a
   **guard de boot** numa próxima story: se `is_production` e `payment_gateway_api_key` definido,
   então `gateway_webhook_secret` não pode ser vazio (fail-fast, mesmo espírito do
   `_guard_production_secrets`). — *item para o backlog, não bloqueia esta story.*
2. **[RESOLVIDO 2026-07-12]** Confirmar o mecanismo de autenticação real do Asaas: é o header
   `asaas-access-token` por igualdade simples (NÃO é HMAC de assinatura do corpo) — confirmado
   contra a doc pública E contra uma requisição real capturada do sandbox. Código já validava
   assim; nenhuma mudança necessária.
3. **[VALIDADO EM SANDBOX 2026-07-12, pendente para PRODUÇÃO]** Registrar o token do webhook no
   painel/API do Asaas igual ao `GATEWAY_WEBHOOK_SECRET` — feito e validado contra uma URL de
   túnel temporária (removida após o teste). Falta repetir contra a URL pública real de produção
   quando o item 10 (deploy) existir.
4. **Validar o isolamento cross-tenant no Postgres real** (RLS), não só no SQLite dos testes: um
   `externalReference` do tenant A não pode baixar cobrança sob o tenant B. O parsing já garante a
   separação; a RLS é a defesa final e precisa ser exercida no e2e (mesma lacuna de e2e já
   registrada no Epic 1).

Nenhuma dessas condições bloqueia o fechamento da Story 2.2 (código correto, degrada graciosamente,
testável com mocks); são passos manuais do operador antes de ativar o gateway em produção.

## Revisão futura

Revisitar via novo ADR se: (a) o volume justificar cartão/carteira digital com melhor cobertura
(reabre Mercado Pago/Pagar.me), (b) o Asaas mudar tarifas/contrato de forma desfavorável, ou (c)
surgir a necessidade de split nativo no provedor (hoje o split é interno, então não é gatilho).
