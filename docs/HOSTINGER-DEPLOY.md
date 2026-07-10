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
- Monitoramento/alertas (hoje não há; considerar `docker compose logs` + algo simples
  tipo Uptime Kuma, ou migrar para AWS Fase B quando o tráfego justificar).
