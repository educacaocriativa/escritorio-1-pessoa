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
```bash
cd /opt/e1p && git pull
cd infra && docker compose -f docker-compose.prod.yml up -d --build
```
Migrations rodam automaticamente no start do container `api` (mesmo comando do dev).

## 6. Backup do Postgres
Sem RDS aqui — backups são responsabilidade sua. Cron diário simples:
```bash
# /etc/cron.d/e1p-backup
0 3 * * * root docker exec $(docker ps -qf "name=infra-postgres-1") \
  pg_dump -U e1p_root e1pdb | gzip > /opt/e1p-backups/e1pdb-$(date +\%F).sql.gz
```
Copie os `.sql.gz` para fora da VPS (S3, outro storage) — backup só na mesma máquina
não protege contra perda do servidor inteiro.

## 7. Diferenças em relação ao dev (`docker-compose.yml`)
| | Dev | Prod (`docker-compose.prod.yml`) |
|---|---|---|
| Segredos | hardcoded (`e1ppass`, `dev-secret...`) | `.env.prod`, gerados, nunca commitados |
| Portas expostas | 5432/8000/8081 no host | só 80/443 (Caddy); resto só na rede interna |
| TLS | nenhum | Caddy + Let's Encrypt automático |
| RLS role | `initdb/01-rls-enforce.sql` (senha fixa) | `initdb-prod/01-rls-enforce.sh` (lê `APP_DB_PASSWORD`) |
| Uploads/gerados | bind local | volumes nomeados (`uploads_data`, `generated_data`) |

## Dívida / próximos passos
- Wildcard subdomínio por tenant (`*.seudominio.com`) — exige TLS via desafio DNS-01
  (Caddy suporta plugins de provedor de DNS; Cloudflare é o mais simples se você migrar
  o DNS pra lá). Reavaliar quando o white-label por subdomínio for pro ar.
- CI/CD (hoje é `git pull` + rebuild manual na VPS).
- Monitoramento/alertas: **implementado** na Story 3.4 com Uptime Kuma self-hosted —
  ver **§8** abaixo. (Migração para observabilidade gerenciada na AWS Fase B fica para
  quando o tráfego justificar.)

## 8. Monitoramento e alertas (Story 3.4)

Monitoramento self-hosted de disponibilidade com **Uptime Kuma** (gratuito, 1 container,
sem serviço pago — respeita o guard-rail de custo NFR3). Cobre: health da API, validade do
TLS, reinícios de container e uso de disco, com alerta acionável por **Telegram**.

> **Por que Uptime Kuma (e não Prometheus/Grafana ou SaaS pago):** já era a sugestão
> registrada aqui; é self-hosted/gratuito, roda no mesmo VPS já contratado (sem novo custo,
> NFR3), e tem monitores nativos de HTTP(s), Certificate Expiry e Docker Container — cobre
> todos os ACs sem escrever código de aplicação.

### 8.1 Subir a stack

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

### 8.2 Configurar os monitores (na UI do Kuma)

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

### 8.3 Canal de alerta (Telegram)

Em **Settings → Notifications** do Kuma, adicione um canal **Telegram** (bot token do
`@BotFather` + chat id) e **vincule-o a todos os monitores** acima. Guarde os valores em
`infra/.env.monitoring` (copiado de `.env.monitoring.example`, nunca commitado).

> Telegram foi escolhido por ser gratuito e não depender de SMTP (`SMTP_HOST` vazio hoje)
> nem da WhatsApp Cloud API (integração ainda PENDENTE). O canal WhatsApp da app
> (`apps/api/app/core/whatsapp.py`) é do **produto para o cliente do tenant** e **não** deve
> ser reaproveitado para este alerta operacional (domínios diferentes: infra vs. tenant).

### 8.4 Teste de queda simulada (IV2)

Procedimento reproduzível para provar que o alerta funciona ponta a ponta:
```bash
docker stop $(docker ps -qf "name=api")     # derruba a API
# → no Kuma, os monitores "API health" (HTTP) e "Containers/api" viram DOWN
# → confirmar a chegada do alerta no Telegram
docker start $(docker ps -qf "name=api")    # restaura
# → monitores voltam a UP; opcionalmente confirmar o alerta de recuperação
```

### 8.5 Validação e custo

- **IV1 (checks leves):** HTTP a cada 60s em `/health` (sem query ao banco) — carga
  desprezível.
- **IV3 (custo, NFR3):** Uptime Kuma é gratuito/self-hosted e roda no mesmo VPS já
  contratado — **nenhum serviço pago novo** foi introduzido.
- **Sintaxe do compose:** valide antes de subir com
  `docker compose -f docker-compose.monitoring.yml config`.
