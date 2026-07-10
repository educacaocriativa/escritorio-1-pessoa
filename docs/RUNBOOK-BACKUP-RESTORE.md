# Runbook — Backup, Offsite & Restore do Postgres (VPS Hostinger)

> **Objetivo:** garantir que os dados do e1p sobrevivam à perda do servidor inteiro.
> Cobre backup diário automatizado (`pg_dump | gzip`), cópia **offsite** (rclone) e um
> procedimento de **restore testado** (drill), atendendo à Story 3.3 (Epic 3).
>
> Complementa `docs/HOSTINGER-DEPLOY.md` §6. Scripts: `infra/scripts/backup.sh` e
> `infra/scripts/restore.sh`. Variáveis: `infra/.env.prod` (ver `.env.prod.example`).

---

## 1. Pré-requisitos

| Item | Detalhe |
|------|---------|
| Stack em produção rodando | `docker-compose.traefik.yml` (VPS real `e1p.doroeventos.com.br`) ou `docker-compose.prod.yml` (Caddy próprio). O serviço `postgres` precisa estar de pé. |
| `rclone` instalado no HOST | Fora do container (é ferramenta de host). `curl https://rclone.org/install.sh \| sudo bash`. |
| Remote rclone `e1p-offsite` configurado | Provedor S3-compatível (AWS S3, Backblaze B2, Wasabi). Credenciais NUNCA no repo. |
| `infra/.env.prod` preenchido | `BACKUP_S3_BUCKET`, `BACKUP_RETENTION_DAYS_LOCAL`, `BACKUP_RETENTION_DAYS_REMOTE`. |
| Papel `e1p_app` no alvo do restore | Só existe se o Postgres foi inicializado com volume novo (ver §5.1). Crítico p/ o RLS valer (Regra de Ouro nº 1). |

### 1.1 Por que `rclone` (e não `aws-cli`)?

Binário único, multi-provedor (sem lock-in), gratuito e barato de operar — respeita o
guard-rail de custo (Regra de Ouro nº 4). Nenhum provedor offsite específico é prescrito
nos docs do projeto, então a flexibilidade de trocar de provedor sem reescrever o script
foi priorizada. Compatível com a evolução futura p/ S3 real (`docs/AWS-DEPLOYMENT.md`).

---

## 2. Configuração inicial (uma vez, na VPS)

```bash
# 1. Instalar rclone no host
curl https://rclone.org/install.sh | sudo bash

# 2. Configurar o remote offsite (interativo). Nomeie o remote como "e1p-offsite".
#    Escolha o tipo (ex.: "s3" -> Amazon/Wasabi/Backblaze) e informe key/secret/region/endpoint.
rclone config
#    Ao terminar, teste:
rclone lsd e1p-offsite:

# 3. Preencher infra/.env.prod (copie do .env.prod.example se ainda não existe):
#    BACKUP_S3_BUCKET=meu-bucket/e1p
#    BACKUP_RETENTION_DAYS_LOCAL=7
#    BACKUP_RETENTION_DAYS_REMOTE=30

# 4. Deixar o script executável
chmod +x /opt/e1p/infra/scripts/backup.sh /opt/e1p/infra/scripts/restore.sh
```

### 2.1 Retenção remota (lifecycle rule no provedor)

`BACKUP_RETENTION_DAYS_REMOTE` é **documental** — o script NÃO apaga objetos remotos. A
expiração dos dumps antigos no bucket é feita por uma **lifecycle rule** configurada no
provedor:

- **AWS S3 / Wasabi:** Console → Bucket → *Management* → *Lifecycle rules* → *Expire current
  versions of objects* após `30` dias (prefixo `e1p/`).
- **Backblaze B2:** Bucket → *Lifecycle Settings* → *Keep only the last N days*.

A retenção **local** (`BACKUP_RETENTION_DAYS_LOCAL`, default 7) é aplicada pelo próprio
`backup.sh` (`find ... -mtime +N -delete`).

---

## 3. Backup diário (cron)

Instalado via cron do host (não um container dedicado — menor superfície, alinhado ao
guard-rail de custo). Substitui o cron inline antigo do `HOSTINGER-DEPLOY.md`:

```bash
# /etc/cron.d/e1p-backup
0 3 * * * root /opt/e1p/infra/scripts/backup.sh >> /var/log/e1p-backup.log 2>&1
```

### 3.1 Backup manual (ad-hoc, fora do cron)

```bash
/opt/e1p/infra/scripts/backup.sh
# ou apontando explicitamente o compose file (ex.: caminho Caddy próprio):
COMPOSE_FILE=/opt/e1p/infra/docker-compose.prod.yml /opt/e1p/infra/scripts/backup.sh
```

O script:
1. Gera `pg_dump | gzip` -> `/opt/e1p-backups/e1pdb-<timestamp>.sql.gz`.
2. Envia via `rclone copy` p/ `e1p-offsite:${BACKUP_S3_BUCKET}/`.
3. Apaga dumps locais > `BACKUP_RETENTION_DAYS_LOCAL` dias.
4. Loga cada passo (INFO/WARN/ERROR + timestamp). Falha => exit code != 0 (terreno p/ o
   alerta acionável da Story 3.4).

> **Falha de upload não apaga o dump local** — o operador ainda tem o arquivo p/ reenviar
> manualmente (`rclone copy /opt/e1p-backups/<arquivo>.sql.gz e1p-offsite:${BACKUP_S3_BUCKET}/`).

---

## 4. Verificar o offsite (IV3)

```bash
rclone ls e1p-offsite:${BACKUP_S3_BUCKET}
# Deve listar os e1pdb-<timestamp>.sql.gz com tamanho > 0.
```

Se listar os arquivos, a cópia offsite existe e é acessível fora da VPS (IV3 satisfeita).

---

## 5. Restore (drill — AC3 / IV2)

### 5.1 Pré-requisito CRÍTICO: o alvo precisa do papel `e1p_app`

`infra/docker/initdb-prod/01-rls-enforce.sh` cria o papel `e1p_app` (NOSUPERUSER) **apenas
na primeira inicialização de um volume vazio** (`docker-entrypoint-initdb.d`). Um restore
sobre um volume já inicializado NÃO recria o papel. Portanto, mire:

- **(a)** o Postgres do **staging** da Story 3.1 (se já existir), OU
- **(b)** um Postgres **efêmero** com volume NOVO, subido do mesmo compose file.

> O AC3 (provar que o dump reconstrói um banco íntegro, com RLS/`e1p_app` preservados) não
> depende do staging da 3.1 estar pronto — um Postgres efêmero é funcionalmente equivalente
> para o drill.

### 5.2 Subir um alvo efêmero (opção b)

```bash
cd /opt/e1p/infra
# Volume NOVO, isolado, só p/ o drill (não toca o postgres_data de produção):
docker compose --env-file .env.prod -f docker-compose.traefik.yml \
  -p e1p-restore-drill up -d postgres
# (o -p usa um project name diferente => volume/rede/containers separados)
```

### 5.3 Executar o restore

```bash
# a partir de um dump local:
COMPOSE_FILE=/opt/e1p/infra/docker-compose.traefik.yml \
  /opt/e1p/infra/scripts/restore.sh --force /opt/e1p-backups/e1pdb-<timestamp>.sql.gz

# ou baixando o mais recente do offsite:
/opt/e1p/infra/scripts/restore.sh --force --latest-offsite
```

> Para mirar o project efêmero do §5.2, exporte `COMPOSE_PROJECT_NAME=e1p-restore-drill`
> antes de chamar o `restore.sh` (assim o `docker compose exec` acha o container certo).

### 5.4 Validação pós-restore (registrar evidência)

Abra um `psql` como `e1p_root` no alvo:

```bash
docker compose -p e1p-restore-drill exec -T postgres psql -U e1p_root -d e1pdb
```

**(a) Tabelas de negócio presentes:**
```sql
\dt
-- Esperado: users, tenants, agenda_events, crm_clients, crm_stages, charges, payables,
-- transactions, wallets, quotes, contracts, products, funnels, legal_documents, etc.
```

**(b) Papel `e1p_app` existe (NOSUPERUSER) com grants:**
```sql
\du e1p_app
-- Esperado: e1p_app | (sem "Superuser"); membro de nenhum papel privilegiado.
\dp users
-- Esperado: privilégios concedidos ao e1p_app nas tabelas.
```

**(c) Isolamento por tenant (RLS) — conectando como `e1p_app` (NÃO superusuário!):**
```bash
docker compose -p e1p-restore-drill exec -T postgres psql -U e1p_app -d e1pdb
```
```sql
-- Escolha uma tabela de negócio com RLS e dois tenants distintos existentes no dump.
SELECT set_config('app.current_tenant_id', '<TENANT_A_UUID>', false);
SELECT count(*) FROM crm_clients;             -- só linhas do tenant A
SELECT set_config('app.current_tenant_id', '<TENANT_B_UUID>', false);
SELECT count(*) FROM crm_clients;             -- só linhas do tenant B (nunca as do A)
SELECT set_config('app.current_tenant_id', '', false);
SELECT count(*) FROM crm_clients;             -- 0 (fail-closed sem tenant setado)
```
> ⚠️ A validação de RLS SÓ é válida conectando como `e1p_app`. Como `e1p_root`
> (superusuário) o Postgres faz **bypass** de RLS mesmo com FORCE — veria todos os tenants.
> Ver Regra de Ouro nº 1 (`CLAUDE.md`).

### 5.5 Limpar o alvo efêmero

```bash
cd /opt/e1p/infra
docker compose -p e1p-restore-drill down -v   # remove containers + volume do drill
```

---

## 6. Registro do drill de restore (evidência do AC3)

> **Preencher a cada execução REAL do drill.** Este é o comprovante objetivo de que o
> "restore testado" do AC3 aconteceu — a Story só está de fato entregue quando a primeira
> linha abaixo estiver preenchida com uma execução real na VPS/staging.

| Data | Ambiente | Origem do dump | Resultado | Executado por | Observações |
|------|----------|----------------|-----------|---------------|-------------|
| _(pendente)_ | staging / efêmero | local / offsite | ✅/❌ | @devops | preencher `\dt`, `\du`, teste RLS |

**Nota de validação (ambiente de implementação):** este runbook e os scripts foram escritos
e revisados no worktree de desenvolvimento (Windows, sem Docker/Postgres de produção nem
credenciais de provedor offsite). A execução end-to-end do drill (backup real -> offsite ->
restore -> validação RLS) exige a VPS Hostinger com a stack de pé e um remote `rclone`
configurado — deve ser feita pelo operador (@devops) e o resultado registrado na tabela acima.

---

## 7. Troubleshooting

| Sintoma | Causa provável | Ação |
|---------|----------------|------|
| `pg_dump: error: connection ... failed` | container `postgres` não está de pé | `docker compose -f <file> ps` / `up -d postgres` |
| `rclone: command not found` | rclone não instalado no host | ver §2 |
| `directory not found` no `rclone copy` | `BACKUP_S3_BUCKET` errado ou remote não configurado | `rclone lsd e1p-offsite:` |
| restore: `role "e1p_app" does not exist` | alvo com volume já inicializado (não é volume novo) | usar volume NOVO / project efêmero (§5.2) |
| restore aborta pedindo `--force` | guarda de segurança | reexecutar com `--force` (só em alvo descartável!) |
| RLS "vê" todos os tenants na validação | conectou como `e1p_root` (superusuário) | reconectar como `e1p_app` (§5.4c) |

---

## 8. Referências

- `infra/scripts/backup.sh`, `infra/scripts/restore.sh`
- `infra/.env.prod.example` (vars `BACKUP_*`)
- `docs/HOSTINGER-DEPLOY.md` §6
- `infra/docker/initdb-prod/01-rls-enforce.sh` (bootstrap do papel `e1p_app`)
- `CLAUDE.md` — Regras de Ouro nº 1 (RLS/tenant) e nº 4 (custo)
- `docs/prd/epic-3-deploy-storage-observabilidade.md` (Epic 3)
