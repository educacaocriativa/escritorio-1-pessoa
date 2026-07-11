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

## 8. Wildcard de subdomínio por tenant (`*.${ROOT_DOMAIN}`) — Story 4.4
White-label por subdomínio (`joaosilva.e1p.com`). O certificado curinga exige TLS via
**desafio DNS-01** — o Let's Encrypt **não** emite wildcard via HTTP-01. O domínio único
(`${DOMAIN}`) continua no HTTP-01 automático, sem regressão.

### 8.1 Pré-requisitos (fora do escopo de código — exigem infra/DNS real)
1. **DNS de `${ROOT_DOMAIN}` gerido pela Cloudflare** (ou outro provedor com plugin Caddy).
   Se ainda estiver em outro registrador, migre a zona para a Cloudflare antes.
2. **Registro DNS wildcard**: um `A`/`CNAME` de `*.${ROOT_DOMAIN}` apontando pro IP da VPS.
3. **`CLOUDFLARE_API_TOKEN`** com escopo **mínimo** (menor privilégio): *Zone → DNS → Edit*
   na zona `${ROOT_DOMAIN}`. Gere em https://dash.cloudflare.com/profile/api-tokens e
   coloque no `.env.prod` (nunca commitar). `ROOT_DOMAIN=e1p.com` também no `.env.prod`.

### 8.2 Topologia A — Caddy próprio (`docker-compose.prod.yml`)
- A imagem do Caddy passa a ser **buildada localmente** (`infra/caddy/Dockerfile`, via
  `xcaddy build --with github.com/caddy-dns/cloudflare`) — a oficial `caddy:2-alpine` não
  traz módulos de DNS. O `Caddyfile` ganhou um segundo bloco `*.{$ROOT_DOMAIN}` com
  `tls { dns cloudflare {$CLOUDFLARE_API_TOKEN} }`.
- Subir: `docker compose -f docker-compose.prod.yml up -d --build` (o `--build` recompila
  a imagem do Caddy com o plugin).

### 8.3 Topologia B — Traefik compartilhado (`docker-compose.traefik.yml`, produção real)
- ⚠️ **Dependência externa (bloqueio operacional, não de código):** o Traefik compartilhado
  vive em `/opt/infra/proxy/` **fora deste repositório**. Os labels de `api`/`web` já aceitam
  o wildcard (`HostRegexp(...)`), **mas a emissão do certificado** depende de configurar, no
  repo de infra externo, um **certresolver com desafio DNS-01/Cloudflare** (mesmo provedor da
  Topologia A, para não ter dois fluxos de credencial DNS). Sem essa mudança externa o
  roteamento wildcard funciona mas fica sem cert válido. Coordene com quem opera `/opt/infra/proxy/`.

### 8.4 Runbook de validação IV3 (emissão/renovação do certificado)
1. Preencha `.env.prod` com `CLOUDFLARE_API_TOKEN` e `ROOT_DOMAIN`.
2. `docker compose -f docker-compose.prod.yml up -d --build`.
3. Acesse `https://qualquerslug.${ROOT_DOMAIN}` (o slug pode nem existir como tenant — o
   objetivo aqui é só validar o certificado, não um tenant real).
4. Confirme a cobertura do curinga:
   `echo | openssl s_client -connect qualquerslug.${ROOT_DOMAIN}:443 -servername qualquerslug.${ROOT_DOMAIN} 2>/dev/null | openssl x509 -noout -text | grep -A1 'Subject Alternative Name'`
   → deve listar `DNS:*.${ROOT_DOMAIN}`.
5. Logs da emissão via Cloudflare:
   `docker compose -f docker-compose.prod.yml logs caddy | grep -i 'cloudflare\|dns-01\|obtain'`.

### 8.5 IV1 (domínio único) e IV2 (isolamento) — validação
- **IV1:** acesse `https://${DOMAIN}` após a mudança e faça login normalmente — sem exigir
  subdomínio. O bloco do domínio único não usa DNS-01 e não foi alterado no comportamento.
- **IV2 (segurança, revisão de código obrigatória no quality gate):** confirmar que
  `app/core/subdomain.py::extract_tenant_slug`/`get_tenant_by_subdomain` **NÃO** é usado em
  nenhum ponto que sete a GUC `app.current_tenant_id` nem substitua `get_tenant_db`/
  `tenant_session`. O isolamento continua 100% no JWT+RLS — o `Host` (controlável pelo
  cliente) só serve para branding/UX em rotas públicas. Ver Regra de Ouro nº 1 (CLAUDE.md §3.1).

## Dívida / próximos passos
- **Wildcard na Topologia B (Traefik compartilhado):** a emissão real do cert depende de
  config externa em `/opt/infra/proxy/` (certresolver DNS-01) — ver §8.3.
- CI/CD (hoje é `git pull` + rebuild manual na VPS).
- Monitoramento/alertas (hoje não há; considerar `docker compose logs` + algo simples
  tipo Uptime Kuma, ou migrar para AWS Fase B quando o tráfego justificar).
