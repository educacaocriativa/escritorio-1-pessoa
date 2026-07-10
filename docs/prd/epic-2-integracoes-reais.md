# Epic 2: Integrações Reais (Dinheiro & Comunicação)

> **Classificação:** BLOQUEANTE para o lançamento (WhatsApp é bloqueante-leve/fast-follow).
> **Sequenciamento:** segundo epic do go-live. **Dependência externa:** contas/aprovações (Meta, gateway) —
> iniciar cedo, pois podem atrasar. Fonte: `docs/prd.md` §7; dívida em `CLAUDE.md` §6/§6.1.

## Contexto do sistema existente (para o @sm)
O e1p foi construído com **stubs conscientes** nos pontos que exigem credenciais/infra externa:
- **Pagamento:** existe `core/boleto.py` (fpdf2) que gera um boleto **layout-stub sem registro bancário**;
  o pagamento entra por `POST /receivables/webhook` (público, protegido por `GATEWAY_WEBHOOK_SECRET`), que
  credita a Carteira com split (40/30/20) usando locks `FOR UPDATE` contra baixa dupla. Falta o gateway
  real (Asaas/Mercado Pago) gerando boleto/Pix registrado e enviando o webhook de verdade.
- **E-mail:** `core/email.py` é stub (em dev vira log; o token de reset e a senha temporária de convite
  voltam no corpo da resposta — `dev_reset_token`/`temp_password`). Recuperação de senha e convite de
  conta/funcionário dependem de entrega real.
- **WhatsApp:** `core/whatsapp.py` é stub — as notificações (cobrança com IA, funil, `crm.client.moved`,
  vencimentos) ficam apenas `logged`. Não há campo de telefone do owner (recipient usa o e-mail como
  placeholder). Precisa `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_ID` (Meta Cloud API).
Todos os stubs adotam **graceful degradation** (sem chave → log, sem quebrar a request) — comportamento a
ser preservado. A composição de mensagens por IA passa pelo **anonimizador** (Regra de Ouro nº 2).

## Epic Goal
Trocar os stubs conscientes por provedores reais para que o dinheiro entre de fato (gateway com boleto/Pix
registrado e webhook confiável creditando o split) e as mensagens sejam realmente entregues (e-mail
transacional e WhatsApp), tornando verídicas as promessas do produto — sem quebrar a graceful degradation
nem os fluxos existentes.

## Integration Requirements
Cada provedor é plugado **por trás das interfaces internas existentes** (`core/email.py`, `core/whatsapp.py`,
contrato do webhook `POST /receivables/webhook`), preservando os chamadores e testes atuais. Idempotência e
locks `FOR UPDATE` da Carteira/Contas a Receber devem permanecer intactos. Escolha específica do gateway e
do provedor de e-mail deve ser formalizada em ADR no início do epic.

---

## Story 2.1 — Provedor de e-mail transacional (SMTP/SES)
As a **profissional e seus clientes/funcionários convidados**,
I want **receber de verdade os e-mails de recuperação de senha e de convite (com a senha temporária)**,
so that **o onboarding e a recuperação de acesso funcionem em produção sem expor tokens/senhas na resposta**.

### Acceptance Criteria
1. `core/email.py` passa a enviar via provedor real (SMTP genérico ou SES), configurado por `SMTP_HOST` e credenciais em `.env.prod`/SSM; sem chave configurada, mantém o comportamento de log (graceful degradation).
2. Os fluxos existentes passam a entregar por e-mail: link de recuperação (`/auth/forgot-password`) e senha temporária de convite de conta/funcionário (`/admin/accounts`, `/admin/accounts/{tenant_id}/users`).
3. Em produção, o corpo da resposta **não** retorna mais `dev_reset_token` nem `temp_password` (só em dev).

### Integration Verification
- IV1: Os fluxos de convite/1º acesso e recuperação de senha continuam funcionando ponta a ponta (testes existentes passam; token/senha deixam de vazar no corpo em prod).
- IV2: Sem chave de e-mail configurada, os endpoints não quebram (falham fechado/log).
- IV3: Sem regressão de latência perceptível nos endpoints de auth/convite.

## Story 2.2 — Gateway de pagamento real (Asaas / Mercado Pago)
As a **dono da empresa de 1 pessoa e a plataforma**,
I want **gerar boleto/Pix registrado de verdade e receber o webhook real de compensação**,
so that **o dinheiro entre e o split (40/30/20) seja creditado na Carteira automaticamente**.

### Acceptance Criteria
1. Um gateway (Asaas ou Mercado Pago — decisão via ADR no início do épico) gera boleto/Pix **registrado** (substituindo o layout-stub do `core/boleto.py`), com linha digitável/QR válidos e vencimento correto.
2. `POST /receivables/webhook` recebe o webhook real de compensação, valida `GATEWAY_WEBHOOK_SECRET`, e credita a Carteira com o split, liberando o valor para saque no Financeiro.
3. A baixa é **idempotente** e protegida contra baixa dupla/crédito duplicado (preserva os locks `FOR UPDATE` existentes); pagamentos duplicados do gateway não geram dupla transação.
4. Cada ocorrência recorrente gera seu próprio boleto/cobrança registrado (mantém o comportamento de recorrência atual).

### Integration Verification
- IV1: O efeito dominó existente (orçamento/proposta aprovada → cobrança → contrato) e a recorrência continuam funcionando com o gateway real.
- IV2: O split e os saldos da Carteira (disponível/a receber/sacado) e o `platform_earnings` batem após a baixa real (testes de Carteira/Contas a Receber passam).
- IV3: Isolamento por tenant intacto; webhook não permite cruzar tenants nem baixar cobrança de outro tenant.

## Story 2.3 — WhatsApp Cloud API
As a **dono da empresa de 1 pessoa**,
I want **que as notificações hoje apenas `logged` (cobrança com IA, funil, mover card, vencimentos) sejam entregues por WhatsApp**,
so that **a comunicação com clientes aconteça de verdade e não seja uma promessa silenciosa**.

### Acceptance Criteria
1. `core/whatsapp.py` passa a enviar via WhatsApp Cloud API (Meta), usando `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_ID`; sem chave, mantém o log (graceful degradation).
2. É adicionado um **campo de telefone do owner/destinatário** (migration aditiva) — hoje o recipient usa o e-mail como placeholder; as notificações passam a usar o telefone real.
3. As mensagens existentes (cobrança amigável com IA, mensagens de funil, `crm.client.moved`, vencimentos) são entregues com o conteúdo já gerado, respeitando o anonimizador quando a IA compõe o texto.

### Integration Verification
- IV1: O barramento de notificações (`notifications`, `crm.client.moved`) e a "Cobrar com IA" continuam funcionando; sem chave, nada quebra (só loga).
- IV2: Nenhum PII vai para a IA sem anonimização (Regra de Ouro nº 2 preservada na composição das mensagens).
- IV3: Envio não derruba a request de origem em caso de falha do provedor (falha fechada/log; migração para fila fica no Epic 4).
