# Deploy em VPS Hostinger (KVM) — 1 servidor, Docker Compose

Alternativa mais barata ao plano AWS (`docs/AWS-DEPLOYMENT.md`): tudo num único VPS.
Como a app já é 100% conteinerizada (12-factor), a topologia é quase idêntica ao
`docker-compose.yml` de dev — só troca o alvo. Ver ADR 0001 (`docs/decisions/`) para o
contexto da decisão original de infra; isto documenta o caminho Hostinger como opção B.

> **VPS com Traefik compartilhado (produção real, `e1p.doroeventos.com.br`):** este guia
> assume um Caddy PRÓPRIO publicando 80/443 (`docker-compose.prod.yml`). A VPS de produção
> real já roda um **Traefik compartilhado** entre vários projetos (`/opt/infra/proxy/` no
> host — nenhum outro serviço pode publicar 80/443 lá). Nesse caso use
> `infra/docker-compose.traefik.yml` no lugar do `docker-compose.prod.yml` — mesmos
> segredos/`.env.prod`, mas sem serviço de proxy próprio (api/web só entram na rede externa
> `edge` com labels Traefik). Ver comentário de cabeçalho do arquivo para detalhes.

Escopo deste guia: **1 domínio único** (ex. `app.seudominio.com`), sem subdomínio por
tenant ainda. Quando o white-label por subdomínio (`joaosilva.e1p.com`) entrar, revisar
o Caddyfile para wildcard TLS (exige desafio DNS-01 com um provedor de DNS suportado).

## 1. Contratar e preparar a VPS
1. Plano **VPS KVM** da Hostinger — o menor (KVM 1/2) já roda Postgres+API+web+proxy
   para começar; suba de plano se o Assistente Jurídico (IA/OCR) pesar na CPU.
2. Escolha imagem **Ubuntu 24.04 LTS** no painel da Hostinger.
3. Aponte o DNS: crie um registro **A** de `app.seudominio.com` → IP da VPS (no painel
   de DNS do seu domínio, que pode ser a própria Hostinger ou outro registrador).
4. Acesse por SSH (`ssh root@<ip-da-vps>`) e instale o Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   apt-get install -y docker-compose-plugin git
   ```
5. Firewall — só exponha o essencial:
   ```bash
   ufw allow OpenSSH
   ufw allow 80/tcp
   ufw allow 443/tcp
   ufw enable
   ```
   Postgres/API **não** devem ficar acessíveis pela internet — no `docker-compose.prod.yml`
   eles não publicam porta nenhuma no host (só a rede interna do Compose).

## 2. Clonar e configurar
```bash
git clone <url-do-repo> /opt/e1p
cd /opt/e1p/infra
cp .env.prod.example .env.prod
```
Preencha `.env.prod` (gere segredos fortes):
```bash
openssl rand -base64 32   # POSTGRES_ROOT_PASSWORD / APP_DB_PASSWORD
openssl rand -hex 32      # JWT_SECRET
```
Campos obrigatórios (o backend recusa subir sem eles em produção — ver
`apps/api/app/config.py::_guard_production_secrets`): `JWT_SECRET` (≥32 chars, != default),
`ANTHROPIC_API_KEY`, `SUPER_ADMIN_PASSWORD` (!= default). Preencha também `DOMAIN` e
`FRONTEND_URL=https://app.seudominio.com`.

Campos **opcionais** de integração (vazios = o app funciona, só registra em log —
graceful degradation, mesmo padrão de `SMTP_HOST`/`GATEWAY_WEBHOOK_SECRET`):
- **WhatsApp Cloud API (Story 2.3)** — `WHATSAPP_TOKEN` e `WHATSAPP_PHONE_ID` (Meta Cloud
  API). Preenchidos, as notificações (mover card no Kanban, cobrança com IA, funil) são
  **entregues de verdade** ao telefone configurado em **Configurações → Telefone** de cada
  escritório. Vazios, as notificações ficam apenas `logged` (nada quebra). Já listados em
  `infra/.env.prod.example`.

## 3. Subir
```bash
cd /opt/e1p/infra
docker compose -f docker-compose.prod.yml up -d --build
```
Isso builda as 3 imagens, sobe Postgres (rodando `initdb-prod/01-rls-enforce.sh` no
primeiro boot — cria o papel `e1p_app` NÃO-superusuário, essencial pro RLS valer,
Regra de Ouro nº 1 do `CLAUDE.md`), roda `alembic upgrade head` + seed, e o Caddy
emite o certificado TLS automaticamente (Let's Encrypt, desafio HTTP-01 — por isso
o DNS precisa já estar apontado ANTES de subir o Caddy).

Acompanhe:
```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f caddy
```
Se o Caddy falhar ao emitir o certificado, confira se `app.seudominio.com` já resolve
pro IP da VPS (`dig +short app.seudominio.com`) e se a porta 80 está mesmo acessível.

## 4. Validar
- `https://app.seudominio.com` → tela de login.
- `https://app.seudominio.com/api/health` (ou endpoint equivalente) → 200.
- Login com `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` do `.env.prod`.
- **Segurança de credenciais (Story 1.4):**
  - Guard de segredos fracos: o boot **recusa** subir em produção com `JWT_SECRET`
    fraco/default (<32 chars), `ANTHROPIC_API_KEY` ausente ou `SUPER_ADMIN_PASSWORD`
    default (`apps/api/app/config.py::_guard_production_secrets`; coberto por 6 testes em
    `apps/api/tests/test_config.py`). Se algum estiver fraco, o container `api` **não sobe** —
    confira os logs (`docker compose -f docker-compose.prod.yml logs api`).
  - 1º login do Master força troca de senha: no primeiro acesso com a senha do `.env.prod`,
    o app exibe a `FirstAccessPage` e só libera após a troca (`must_reset_password=True` no
    Super Admin semeado; ver `apps/api/tests/test_seed.py`). Confirme que **não** consegue
    navegar antes de trocar a senha.
- **WhatsApp Cloud API (Story 2.3):**
  - **Com** `WHATSAPP_TOKEN`/`WHATSAPP_PHONE_ID` no `.env.prod`: em Configurações preencha
    o campo **Telefone** do escritório, mova um card no Kanban (ou dispare "Cobrar com IA")
    e confirme que a mensagem chega no WhatsApp configurado. Nos logs a Notification fica
    com status `sent` (`docker compose -f docker-compose.prod.yml logs api`).
  - **Sem** essas variáveis: o app **não quebra** — as notificações ficam apenas em log.
    Confirme com `docker compose -f docker-compose.prod.yml logs api | grep '[whatsapp:logged]'`
    (a Notification é gravada com status `logged`). Validação end-to-end com número real
    exige uma conta/número aprovados na Meta Cloud API (não coberto por testes automatizados).

## 5. Atualizações (deploy de uma nova versão)
> **Antes de dar `git pull` + rebuild em produção, confirme que o CI está VERDE** no
> commit/branch que será deployado (`.github/workflows/ci.yml` — jobs `test-in-prod-image`
> e `cross-tenant-rls`). O CI roda a suíte DENTRO da imagem de produção (pega drift
> venv↔produção) e valida o isolamento RLS num Postgres real (Story 3.2). O deploy em si
> continua manual (não há CD automático), mas por processo só suba versões com CI passando.

```bash
cd /opt/e1p && git pull
cd infra && docker compose -f docker-compose.prod.yml up -d --build
```
Migrations rodam automaticamente no start do container `api` (mesmo comando do dev).

## 6. Backup do Postgres (automatizado + offsite + restore testado)
Sem RDS aqui — backups são responsabilidade sua, mas agora são **automatizados, copiados
para fora da VPS e com restore testado** (Story 3.3). Os scripts vivem em `infra/scripts/`
e o passo-a-passo completo (instalação/config do `rclone`, drill de restore, evidências)
está em [`docs/RUNBOOK-BACKUP-RESTORE.md`](RUNBOOK-BACKUP-RESTORE.md).

**Resumo:**
- `infra/scripts/backup.sh` — faz `pg_dump | gzip` via `docker compose exec` (agnóstico ao
  nome do container; funciona com `docker-compose.prod.yml` e `docker-compose.traefik.yml`),
  salva em `/opt/e1p-backups`, envia a cópia **offsite** via `rclone copy` e aplica retenção
  local. Falha (dump ou upload) fica logada com exit code != 0.
- `infra/scripts/restore.sh` — restaura um dump local ou o mais recente do offsite
  (`--latest-offsite`), exige `--force` (guarda de segurança) e mira um alvo descartável/staging.

**Configuração (uma vez, na VPS):**
```bash
# Instale o rclone (host, fora do container) e configure o remote S3-compatível:
curl https://rclone.org/install.sh | sudo bash
rclone config              # crie um remote chamado "e1p-offsite" (S3/B2/Wasabi/...)
# Preencha no infra/.env.prod: BACKUP_S3_BUCKET, BACKUP_RETENTION_DAYS_LOCAL/REMOTE
```

**Cron diário (substitui o cron inline antigo):**
```bash
# /etc/cron.d/e1p-backup
0 3 * * * root /opt/e1p/infra/scripts/backup.sh >> /var/log/e1p-backup.log 2>&1
```
> A retenção **remota** é aplicada por uma *lifecycle rule* no próprio bucket do provedor
> (`BACKUP_RETENTION_DAYS_REMOTE`), não pelo script — ver o runbook.

## 6.5 Migração de Anexos para S3 (Story 3.5)

Os anexos (boletos/contratos) nasceram como bytes no Postgres (`attachments.data`, `LargeBinary`),
o que incha o banco e o dump de backup. A Story 3.5 move os bytes para um object storage
S3-compatível (`app/core/storage.py`), mantendo o isolamento por tenant também no path da chave
(`tenants/{tenant_id}/attachments/{attachment_id}/{filename}`).

**Comportamento faseável (não bloqueia o deploy):** enquanto `S3_BUCKET` estiver vazio, tudo
continua no Postgres exatamente como antes. Configurar o S3 e rodar o backfill pode ser feito
numa janela DEPOIS do go-live.

### 1) Configurar as envs (uma vez)
No `.env.prod`, preencha (ver `infra/.env.prod.example`):

```
S3_BUCKET=meu-bucket-e1p
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_REGION=auto                     # ou a região do provedor
S3_ENDPOINT_URL=https://...        # vazio p/ AWS S3 real; defina p/ MinIO/B2/Wasabi
```

Pode ser AWS S3 real OU um provedor S3-compatível mais barato (MinIO self-hosted na própria VPS,
Backblaze B2, Wasabi) — o código não muda, só a configuração. Reinicie a API (`docker compose
-f infra/docker-compose.prod.yml up -d api`). A partir daí, **anexos NOVOS** já vão direto para
o S3.

### 2) Rodar o backfill dos anexos antigos (uma vez, idempotente)
Move os anexos legados (bytes ainda no Postgres) para o bucket:

```
docker compose -f infra/docker-compose.prod.yml exec api \
  python -m app.scripts.migrate_attachments_to_s3
```

É idempotente — rodar de novo não reprocessa o que já foi migrado. Anexos NÃO migrados continuam
baixando normalmente pelo fallback (leitura resolve a origem por linha), então rodar é seguro e
não é bloqueante.

### 3) Validar (IV3 — o dump encolhe)
Compare o tamanho do `pg_dump` antes/depois do backfill:

```
docker compose -f infra/docker-compose.prod.yml exec -T postgres \
  pg_dump -U e1puser e1pdb | gzip | wc -c
```

O valor deve cair proporcionalmente ao volume de anexos migrados.

> **Nota:** a migration `0039` é só estrutural (adiciona `storage_key`, torna `data` nullable) e
> roda no boot sem tocar em rede/S3 — o backfill é este script operacional separado, rodado à
> mão. A coluna `data` é mantida de propósito (compat. de leitura de anexos não migrados);
> removê-la é limpeza futura, só depois do backfill 100% confirmado.

## 7. Diferenças em relação ao dev (`docker-compose.yml`)
| | Dev | Prod (`docker-compose.prod.yml`) |
|---|---|---|
| Segredos | hardcoded (`e1ppass`, `dev-secret...`) | `.env.prod`, gerados, nunca commitados |
| Portas expostas | 5432/8000/8081 no host | só 80/443 (Caddy); resto só na rede interna |
| TLS | nenhum | Caddy + Let's Encrypt automático |
| RLS role | `initdb/01-rls-enforce.sql` (senha fixa) | `initdb-prod/01-rls-enforce.sh` (lê `APP_DB_PASSWORD`) |
| Uploads/gerados | bind local | volumes nomeados (`uploads_data`, `generated_data`) |

## 8. Staging (validar antes de produção)

Objetivo (Story 3.1): rodar a **mesma imagem/compose de produção** num ambiente separado,
com **segredos próprios** e **dados sintéticos**, e validar cada deploy ali **antes** de
promover à produção real — sem risco ao dado real.

### 8.1 Isolamento (AC3 / IV3)
- **Preferido:** uma **VPS dedicada e barata** só para staging (ex.: o menor plano Hostinger
  KVM) — isolamento físico total de redes, volumes e segredos em relação à produção.
- **Fallback de custo (mesma VPS de produção):** suba o staging com um **nome de projeto
  Compose distinto** (`-p e1p-staging`) — o Compose prefixa redes e volumes nomeados com o
  nome do projeto, isolando-os automaticamente **sem editar o YAML**:
  ```bash
  docker compose -p e1p-staging -f docker-compose.prod.yml up -d --build
  ```
- Staging **nunca** aponta para o `DATABASE_URL`/segredos de produção. Cada ambiente tem o
  **seu próprio** `infra/.env.prod` (mesmo NOME de arquivo em disco, CONTEÚDO diferente,
  diretórios/hosts diferentes). O `DATABASE_URL` é derivado do `APP_DB_PASSWORD` local no
  próprio compose, então cada ambiente fala só com o seu Postgres.

### 8.2 Subir o staging
Num diretório/VPS **separado** do de produção:
```bash
git clone <url-do-repo> /opt/e1p-staging   # (ou outra VPS dedicada)
cd /opt/e1p-staging/infra
cp .env.staging.example .env.prod          # o arquivo em disco TEM que se chamar .env.prod
```
Preencha `.env.prod` com segredos/domínio **PRÓPRIOS de staging** (nunca os de produção).
Detalhe do porquê o arquivo se chama `.env.prod`: `docker-compose.prod.yml`/
`docker-compose.traefik.yml` têm `env_file: - .env.prod` como **string literal** — o Compose
lê esse nome tal e qual (não é interpolado por `--env-file`); então é o **conteúdo** que muda
entre staging e produção, não o nome. O `.env.staging.example` define `SEED_SYNTHETIC_DATA=true`
e `ENVIRONMENT` segue `production` (staging espelha 100% o comportamento de produção — mesmo
guard de segredos fortes; ver `docs/stories/3.1.story.md`). Suba:
```bash
docker compose -f docker-compose.prod.yml up -d --build      # VPS dedicada
# ou, se compartilhando a VPS de produção:
docker compose -p e1p-staging -f docker-compose.prod.yml up -d --build
```
No boot, o container `api` roda `alembic upgrade head` → `python -m app.seed` (Super Admin) →
`python -m app.seed_staging` (dados sintéticos, só porque `SEED_SYNTHETIC_DATA=true` aqui) →
`uvicorn`. O Postgres cria o papel não-superusuário `e1p_app` no primeiro boot (RLS válida —
IV2), igual à produção.

### 8.3 Smoke test dos módulos-chave (antes de promover)
Login com o usuário sintético de staging (semeado por `app.seed_staging`):
`owner@staging-demo.e1p.com` / senha `staging-demo-owner`. Verifique:
- **Login** funciona (o app abre sem exigir troca de senha para essa conta sintética).
- **Agenda** — a "Reunião Demo (staging)" aparece no calendário (amanhã, 14h).
- **CRM / Kanban** — o "Cliente Demo" aparece no board (etapa Entrada).
- **Cockpit** — os números batem com os dados sintéticos (1 cliente, cobrança a vencer).
- **Contas a Receber** — a cobrança sintética (R$150,00, Pix, em aberto) aparece e o link
  "simular pgto" (webhook de teste) funciona.
- `https://staging.seudominio.com/api/health` → 200 (mesma topologia de dev/prod — IV1).

### 8.4 Promover para produção
Só **depois** do smoke test de staging passar, aplique o MESMO fluxo da seção
[§5 Atualizações](#5-atualizacoes-deploy-de-uma-nova-versao) no diretório/VPS de **produção**
real (`git pull` + `docker compose ... up -d --build`). Produção não semeia dados sintéticos:
lá `SEED_SYNTHETIC_DATA` fica vazio/false, então `app.seed_staging` é um no-op.

## Dívida / próximos passos
- Wildcard subdomínio por tenant (`*.seudominio.com`) — exige TLS via desafio DNS-01
  (Caddy suporta plugins de provedor de DNS; Cloudflare é o mais simples se você migrar
  o DNS pra lá). Reavaliar quando o white-label por subdomínio for pro ar.
- **CI** já existe (`.github/workflows/ci.yml`, Story 3.2): testa a imagem de produção e o
  isolamento RLS a cada push/PR na `main`. **Pendente (@devops):** habilitar branch protection
  em GitHub → Settings → Branches marcando `test-in-prod-image` e `cross-tenant-rls` como checks
  obrigatórios (transforma o workflow num gate que BLOQUEIA merge, não só um status vermelho).
  **CD (deploy automático)** ainda não existe — o deploy segue `git pull` + rebuild manual na VPS.
- Monitoramento/alertas: **implementado** na Story 3.4 com Uptime Kuma self-hosted —
  ver **§9** abaixo. (Migração para observabilidade gerenciada na AWS Fase B fica para
  quando o tráfego justificar.)

## 9. Monitoramento e alertas (Story 3.4)

Monitoramento self-hosted de disponibilidade com **Uptime Kuma** (gratuito, 1 container,
sem serviço pago — respeita o guard-rail de custo NFR3). Cobre: health da API, validade do
TLS, reinícios de container e uso de disco, com alerta acionável por **Telegram**.

> **Por que Uptime Kuma (e não Prometheus/Grafana ou SaaS pago):** já era a sugestão
> registrada aqui; é self-hosted/gratuito, roda no mesmo VPS já contratado (sem novo custo,
> NFR3), e tem monitores nativos de HTTP(s), Certificate Expiry e Docker Container — cobre
> todos os ACs sem escrever código de aplicação.

### 9.1 Subir a stack

O monitoramento fica num compose **separado** do da app (`docker-compose.monitoring.yml`),
para não acoplar o release do monitoramento ao release da aplicação (12-factor).

**Topologia A — Traefik compartilhado (produção real, `e1p.doroeventos.com.br`):**
```bash
cd /opt/e1p/infra
# DOMAIN vem do .env.prod; o painel sobe em https://monitor.<DOMAIN> via Traefik.
docker compose --env-file .env.prod -f docker-compose.monitoring.yml up -d
```
Crie um registro DNS **A** `monitor.<DOMAIN>` → IP da VPS antes de subir (o Traefik emite
o TLS Let's Encrypt via label `certresolver=letsencrypt`, como em api/web).

**Topologia B — Caddy próprio (`docker-compose.prod.yml`):** siga as instruções no cabeçalho
do `docker-compose.monitoring.yml` (troque a rede `edge` por `default`, remova as labels
Traefik e suba junto do compose da app); a rota `monitor.{$DOMAIN}` já está no `Caddyfile`.

No primeiro acesso ao painel, **crie usuário/senha** do Kuma (autenticação nativa) — não
deixe o painel sem login, pois ele expõe topologia/portas internas.

### 9.2 Configurar os monitores (na UI do Kuma)

| Monitor | Tipo | Alvo | Cobre |
|---|---|---|---|
| API health | HTTP(s) | `https://<DOMAIN>/api/health` (esperar JSON `{"status":"ok",...}`), intervalo **60s** | AC1 (uptime/health) |
| TLS | Certificate Expiry | `https://<DOMAIN>` | AC1 (validade do TLS) |
| Containers | Docker Container | `api`, `web`, `postgres`, proxy — via `docker.sock` (montado `:ro`) | AC2 (reinícios) |
| Disco | Push | URL única gerada pelo Kuma, alimentada pelo `disk-check.sh` | AC2 (disco) |

O intervalo de **60s** no HTTP(s) mantém o check leve (IV1): `/health` não toca o banco
(`apps/api/app/main.py`), então não introduz carga perceptível.

**Monitor de disco (Push):** ao criar o monitor tipo Push, copie a Push URL para
`KUMA_PUSH_URL_DISK` (ver `infra/.env.monitoring.example`) e agende o script no cron do host
(mesmo padrão do backup em §6):
```bash
# /etc/cron.d/e1p-disk-monitor
*/5 * * * * root KUMA_PUSH_URL="https://monitor.<DOMAIN>/api/push/XXXXXXXX" \
  DISK_THRESHOLD=85 CHECK_PATH=/var/lib/docker \
  /opt/e1p/infra/scripts/monitoring/disk-check.sh
```
**Limiar de disco: 85%** de uso aciona alerta — valor conservador que deixa margem para
picos de backup/geração de PDF antes de o disco encher. Ajuste via `DISK_THRESHOLD` se
necessário.

### 9.3 Canal de alerta (Telegram)

Em **Settings → Notifications** do Kuma, adicione um canal **Telegram** (bot token do
`@BotFather` + chat id) e **vincule-o a todos os monitores** acima. Guarde os valores em
`infra/.env.monitoring` (copiado de `.env.monitoring.example`, nunca commitado).

> Telegram foi escolhido por ser gratuito e não depender de SMTP (`SMTP_HOST` vazio hoje)
> nem da WhatsApp Cloud API (integração ainda PENDENTE). O canal WhatsApp da app
> (`apps/api/app/core/whatsapp.py`) é do **produto para o cliente do tenant** e **não** deve
> ser reaproveitado para este alerta operacional (domínios diferentes: infra vs. tenant).

### 9.4 Teste de queda simulada (IV2)

Procedimento reproduzível para provar que o alerta funciona ponta a ponta:
```bash
docker stop $(docker ps -qf "name=api")     # derruba a API
# → no Kuma, os monitores "API health" (HTTP) e "Containers/api" viram DOWN
# → confirmar a chegada do alerta no Telegram
docker start $(docker ps -qf "name=api")    # restaura
# → monitores voltam a UP; opcionalmente confirmar o alerta de recuperação
```

### 9.5 Validação e custo

- **IV1 (checks leves):** HTTP a cada 60s em `/health` (sem query ao banco) — carga
  desprezível.
- **IV3 (custo, NFR3):** Uptime Kuma é gratuito/self-hosted e roda no mesmo VPS já
  contratado — **nenhum serviço pago novo** foi introduzido.
- **Sintaxe do compose:** valide antes de subir com
  `docker compose -f docker-compose.monitoring.yml config`.
