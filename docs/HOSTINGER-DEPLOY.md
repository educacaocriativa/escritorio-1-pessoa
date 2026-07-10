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
- Monitoramento/alertas (hoje não há; considerar `docker compose logs` + algo simples
  tipo Uptime Kuma, ou migrar para AWS Fase B quando o tráfego justificar).
