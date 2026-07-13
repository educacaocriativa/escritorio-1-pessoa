# Checklist de Go-Live — credenciais e infra real pendentes

> Tudo que está aqui já está **implementado e testado** (com mocks/stubs) em `main`. O que falta é plugar credenciais/infra reais e validar ponta-a-ponta. Cada item referencia o runbook detalhado em `docs/HOSTINGER-DEPLOY.md`.

## 1. E-mail transacional (Story 2.1)
- [x] Contratar/gerar credenciais SMTP — **provisório**: SMTP do Gmail pessoal do fundador (`flaviokato76@gmail.com`, Senha de App), enquanto um provedor definitivo (SES, etc.) não é decidido. Limite de ~500 e-mails/dia — trocar antes de qualquer volume real.
- [x] Preencher `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` — feito no `.env` local (raiz do repo, gitignorado) e repassado a `api`/`worker` via `infra/docker-compose.yml`. **Pendente**: replicar em `infra/.env.prod` de verdade quando a VPS for provisionada (item 10 — hoje não há ambiente de staging/produção rodando para preencher esse arquivo).
- [x] Validar: `forgot-password` chega por e-mail de verdade — testado ponta a ponta em 2026-07-12 (registro real + `/auth/forgot-password` + teste direto de `core/email.send_email`), e-mails confirmados recebidos na caixa de entrada real.

## 2. Gateway de pagamento — Asaas (Story 2.2)
- [x] Criar conta Asaas (sandbox) e gerar API key — reaproveitada conta sandbox pré-existente do
  fundador ("FLAVIO KATO LTDA", já aprovada).
- [x] Preencher `PAYMENT_GATEWAY_PROVIDER=asaas`, `PAYMENT_GATEWAY_API_KEY`, `PAYMENT_GATEWAY_BASE_URL`
  (sandbox `https://api-sandbox.asaas.com/v3`) — feito no `.env` local (raiz, gitignorado) e
  repassado a `api`/`worker` via `env_file` no `infra/docker-compose.yml`. **Cuidado (achado
  2026-07-12):** a API key da Asaas tem um `$` literal — precisa estar como `$$` no `.env` (ou
  usar `env_file`, não `environment: ${VAR}`), senão o Compose interpola e o valor vira string
  vazia. **Pendente:** replicar em `infra/.env.prod` de verdade quando a VPS existir (item 10).
- [x] Configurar `GATEWAY_WEBHOOK_SECRET` e registrar a URL do webhook no painel/API Asaas —
  gerado um segredo real (48 hex chars) e configurado no `.env` local; registrado via
  `POST /v3/webhooks` contra um túnel público temporário (`cloudflared`, autorizado
  explicitamente pelo usuário, removido ao fim do teste). **Pendente:** repetir o registro contra
  a URL pública real de produção quando o item 10 (deploy) existir — a URL de túnel foi só para
  validação, não é permanente.
- [x] Revalidar contra o sandbox real: campos/endpoints exatos do payload, formato do `bankSlipUrl`
  — validado em 2026-07-12: `POST /customers`, `POST /payments` e `GET /payments/{id}/pixQrCode`
  responderam `200` reais contra `api-sandbox.asaas.com` (boleto E Pix), com `gateway_charge_id`/
  `payment_code`/`boleto_url` reais retornados pelo fluxo completo (`receivables.create_charge`).
  Resolve a pendência de No Invention registrada no ADR 0002.
- [x] Testar boleto/Pix real de ponta a ponta + confirmação de pagamento via webhook — validado em
  2026-07-12: criada cobrança Pix real (R$33,00) pelo fluxo do produto, confirmada via
  `POST /v3/sandbox/payment/{id}/confirm` (endpoint sandbox-only), webhook real da Asaas capturado
  (header `asaas-access-token` confirmado, payload `PAYMENT_RECEIVED`/`externalReference` conforme
  doc pública), cobrança marcada `paid` e split de 30% aplicado corretamente na Carteira
  (R$9,90 taxa → R$23,10 disponível). Ver ADR 0002 para os detalhes completos.

## 3. WhatsApp Cloud API (Story 2.3)
- [ ] Criar app Meta for Developers + número WhatsApp Business
- [ ] Preencher: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`
- [ ] Validar entrega real (hoje cai em log se token vazio)

## 4. Storage de anexos — S3-compatível (Story 3.5)
- [ ] Escolher provedor (AWS S3, MinIO self-hosted, Backblaze B2, Wasabi)
- [ ] Criar bucket + credenciais de acesso
- [ ] Preencher: `S3_ENDPOINT_URL` (vazio = AWS), `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`
- [ ] Rodar o backfill dos anexos legados (`docs/HOSTINGER-DEPLOY.md` §6.5)
- [ ] Validar IV3: o dump do Postgres encolhe depois do backfill

## 5. Google Calendar/Meet OAuth (Story 4.1)
- [x] Criar projeto no Google Cloud Console + ativar Calendar API — projeto do fundador, Calendar
  API habilitada, OAuth consent screen em modo "Testing" com `flaviokato76@gmail.com` como test
  user (suficiente para uso próprio; sair de "Testing" exige verificação do Google só se/quando
  precisar liberar para outras contas).
- [x] Gerar OAuth Client ID/Secret, configurar redirect URI — client Web criado, redirect URI
  `http://localhost:8000/integrations/google/callback` (dev). **Pendente:** cadastrar a URI de
  produção (`https://<domínio-real>/integrations/google/callback`) quando o item 10 existir —
  OAuth clients aceitam múltiplas redirect URIs simultâneas, então isso é aditivo, não substitui a
  de dev.
- [x] Preencher `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_OAUTH_REDIRECT_URI` — feito no
  `.env` local (raiz, gitignorado), repassado a `api`/`worker` via `env_file`.
- [x] Testar fluxo OAuth ponta-a-ponta (autorizar, criar evento com Meet real) — validado em
  2026-07-12: autorização real via navegador (conta do fundador), evento tipo "reuniao" criado via
  `/agenda/events` gerou Meet real (`meeting_url`/`google_event_id` reais, confirmados
  visualmente no Google Calendar do usuário). **Bug de produção corrigido no caminho** (achado
  neste teste): `fetch_account_email` (só para exibir "conectado como...") lançava exceção não
  capturada em `handle_callback` quando falhava (aqui: 401 por faltar o scope `userinfo.email` na
  autorização original) — isso descartava os tokens de acesso/refresh JÁ obtidos com sucesso,
  quebrando a conexão inteira por causa de um dado não-essencial. Corrigido: (1) adicionado o
  scope `userinfo.email` a `DEFAULT_SCOPE` (o recurso "mostrar e-mail conectado" já existia no
  código/schema mas nunca funcionava, para ninguém); (2) `fetch_account_email` agora é
  best-effort em `handle_callback` (captura `httpx.HTTPError`, loga, segue com e-mail vazio) —
  mesmo princípio de robustez que o resto do módulo já seguia. Teste de regressão adicionado
  (`test_callback_userinfo_failure_still_connects`). Credencial de teste desconectada
  (revogada) ao final da validação.
- [ ] Dívida conhecida sinalizada pela story (ainda não endereçada): `refresh_token` guardado em
  texto plano (endurecer antes de produção séria); reschedule/cancel ainda não sincronizam de
  volta pro Google.

## 6. Backup automatizado + offsite (Story 3.3)
- [x] Instalar/configurar `rclone` com remote S3-compatível — validado em 2026-07-12 **localmente**
  (MinIO em Docker no lugar do S3 real — sem custo/conta externa) com o binário real do rclone.
  **Pendente:** instalar `rclone` de verdade na VPS quando ela existir (item 10) — mesmo `rclone
  config`, só troca o remote (S3/B2/Wasabi real) pelo MinIO de teste.
- [x] Preencher `BACKUP_S3_BUCKET`/`BACKUP_RETENTION_DAYS_LOCAL`/`BACKUP_RETENTION_DAYS_REMOTE` —
  testado com `BACKUP_S3_BUCKET` real (bucket MinIO); retenção local exercida (0 dumps > 7 dias,
  comportamento correto pra dumps novos).
- [ ] Agendar cron (`/etc/cron.d/e1p-backup`) — só faz sentido na VPS real (item 10).
- [x] **Rodar um restore de teste de verdade (drill completo)** — validado em 2026-07-12 rodando os
  scripts REAIS (`infra/scripts/backup.sh` e `restore.sh`, sem nenhuma modificação) contra a stack
  de dev local + MinIO: `backup.sh` gerou o dump, copiou pro offsite (MinIO); `restore.sh --force
  --latest-offsite` baixou o dump mais recente e restaurou num Postgres **novo/efêmero** (volume
  vazio, papel `e1p_app` criado manualmente como o runbook exige). Confirmado pós-restore: `\dt`
  com todas as tabelas de negócio (owner `e1p_app`), `\du` sem `Superuser` em `e1p_app` (RLS
  ativa), os 9 tenants reais criados hoje durante as outras validações restaurados intactos, e
  **isolamento RLS revalidado** conectando como `e1p_app` (não superuser) e confirmando contagens
  diferentes de `clients` por tenant (0 vs. 1, sem cruzar dados). Recursos de teste (container
  MinIO, Postgres efêmero) removidos ao final.

## 7. Monitoramento e alertas — Uptime Kuma (Story 3.4)
- [ ] Subir a stack de monitoramento na VPS (`docs/HOSTINGER-DEPLOY.md` §9.1)
- [ ] Configurar os monitores na UI do Kuma (§9.2)
- [ ] Criar bot Telegram + configurar canal de alerta (§9.3)
- [ ] Rodar o teste de queda simulada (IV2, §9.4) e confirmar que o alerta chega

## 8. Wildcard de subdomínio por tenant (Story 4.4)
- [ ] DNS de `ROOT_DOMAIN` gerido pela Cloudflare (pré-requisito)
- [ ] Gerar `CLOUDFLARE_API_TOKEN` com escopo mínimo (Zone.DNS:Edit só na zona do domínio)
- [ ] Escolher topologia: Caddy próprio (§10.2) ou Traefik compartilhado (§10.3 — precisa de config extra em `/opt/infra/proxy/`)
- [ ] Validar emissão/renovação do certificado wildcard (IV3, §10.4) e isolamento entre tenants (IV1/IV2, §10.5)

## 9. CI e branch protection (Story 3.2)
- [x] CI já existe e roda de verdade (`test-in-prod-image` + `cross-tenant-rls`) — validado na PR #7
- [ ] Habilitar branch protection em GitHub → Settings → Branches → marcar os 2 checks como obrigatórios (transforma o CI num gate real, hoje só reporta status)
- [ ] (Fora do escopo atual) CD automático — deploy hoje é `git pull` + rebuild manual na VPS

## 10. Staging (Story 3.1)
- [ ] Subir o ambiente de staging isolado (`docs/HOSTINGER-DEPLOY.md` §8.2)
- [ ] Rodar o smoke test dos módulos-chave antes de promover qualquer release (§8.3)

## 11. Achados incidentais durante a implementação (não bloqueantes, mas vale investigar)
- [x] `apps/api/app/modules/funnels/service.py` — possível bug pré-existente: um caminho que deveria chamar `send_email` está chamando `whatsapp.send_text` (achado pelo @dev na Story 4.3, fora do escopo dela, não corrigido). **Corrigido** (PR #12): `run_node` despacha por `core/email.send_email` quando o canal é e-mail; `subject` do config do nó agora é propagado (builder + motor de automação).
- [x] `pnpm lint` está quebrado no repo inteiro por falta de `eslint.config.js` (pré-existente, não é regressão desta leva de stories, mas trava `scripts/check.sh` de lint no frontend). **Corrigido** (PR #12): `apps/web/eslint.config.js` (flat config) adicionado; os 2 problemas revelados (`vitest.config.ts`, `ProdutosPage.tsx`) corrigidos. `pnpm lint` limpo.

---
**Como usar:** cada item tem instruções detalhadas no `docs/HOSTINGER-DEPLOY.md` (seções indicadas). Nenhum desses itens bloqueia o deploy inicial em si — os graceful degradations (stub/log) fazem o sistema funcionar sem eles, só sem a integração real ativa.
