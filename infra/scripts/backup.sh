#!/usr/bin/env bash
#
# backup.sh — dump diário do Postgres de produção (gzip) + cópia offsite (rclone).
# Story 3.3 (Backups automatizados + offsite + restore testado).
#
# Substitui o cron inline do docs/HOSTINGER-DEPLOY.md §6. Usa `docker compose exec`
# (agnóstico ao nome do container/projeto) em vez de `docker ps -qf "name=..."`, então
# funciona tanto com docker-compose.prod.yml (Caddy próprio) quanto com
# docker-compose.traefik.yml (Traefik compartilhado da VPS de produção real).
#
# Uso (cron ou ad-hoc):
#   /opt/e1p/infra/scripts/backup.sh
#
# Variáveis (via ambiente ou infra/.env.prod — ver .env.prod.example):
#   COMPOSE_FILE                caminho do compose de produção
#                               (default: infra/docker-compose.traefik.yml)
#   ENV_FILE                    .env.prod usado para interpolar o compose
#                               (default: infra/.env.prod)
#   BACKUP_DIR                  diretório local dos dumps (default: /opt/e1p-backups)
#   BACKUP_S3_BUCKET            path no remote rclone (ex.: nome-do-bucket/e1p)
#   BACKUP_RETENTION_DAYS_LOCAL apaga dumps locais mais antigos que N dias (default: 7)
#   RCLONE_REMOTE               nome do remote rclone (default: e1p-offsite)
#
# Falha (dump OU upload) => log com timestamp + exit code != 0 (terreno p/ o alerta da
# Story 3.4). O dump local NUNCA é apagado por falha de upload (o operador reenvia manual).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Configuração (env > default) --------------------------------------------
COMPOSE_FILE="${COMPOSE_FILE:-$INFRA_DIR/docker-compose.traefik.yml}"
ENV_FILE="${ENV_FILE:-$INFRA_DIR/.env.prod}"
BACKUP_DIR="${BACKUP_DIR:-/opt/e1p-backups}"
BACKUP_RETENTION_DAYS_LOCAL="${BACKUP_RETENTION_DAYS_LOCAL:-7}"
RCLONE_REMOTE="${RCLONE_REMOTE:-e1p-offsite}"
DB_NAME="${POSTGRES_DB:-e1pdb}"
DB_SUPERUSER="${POSTGRES_USER:-e1p_root}"

# Carrega o .env.prod (BACKUP_S3_BUCKET etc.) se existir — sem falhar se ausente.
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

TS="$(date +%F_%H%M%S)"
LOCAL_FILE="$BACKUP_DIR/${DB_NAME}-${TS}.sql.gz"

log() {
  # Log estruturado (timestamp ISO + nível + mensagem) — vai pro stdout, que o cron
  # redireciona pra /var/log/e1p-backup.log (ver docs/HOSTINGER-DEPLOY.md §6).
  printf '%s [%s] %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)" "$1" "$2"
}

fail() {
  log "ERROR" "$1"
  exit 1
}

# --- 1. Dump ------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"
log "INFO" "Iniciando backup: compose=$COMPOSE_FILE db=$DB_NAME destino=$LOCAL_FILE"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

# pg_dump lógico via snapshot MVCC — NÃO interrompe a app nem trava a escrita (IV1).
# `set -o pipefail` garante que uma falha do pg_dump derrube o pipe (não mascarada pelo gzip).
if ! compose exec -T postgres pg_dump -U "$DB_SUPERUSER" "$DB_NAME" | gzip > "$LOCAL_FILE"; then
  rm -f "$LOCAL_FILE"
  fail "pg_dump falhou — nenhum dump gerado."
fi

if [ ! -s "$LOCAL_FILE" ]; then
  rm -f "$LOCAL_FILE"
  fail "dump gerado está vazio — abortando."
fi
log "INFO" "Dump local OK: $LOCAL_FILE ($(du -h "$LOCAL_FILE" | cut -f1))"

# --- 2. Cópia offsite (rclone) ------------------------------------------------
if [ -z "${BACKUP_S3_BUCKET:-}" ]; then
  log "WARN" "BACKUP_S3_BUCKET não definido — pulando cópia offsite (dump local mantido)."
elif ! command -v rclone >/dev/null 2>&1; then
  # Falha real: offsite é requisito do AC2. Dump local preservado p/ reenvio manual.
  fail "rclone não instalado — cópia offsite falhou (dump local preservado em $LOCAL_FILE)."
else
  log "INFO" "Enviando p/ offsite: ${RCLONE_REMOTE}:${BACKUP_S3_BUCKET}/"
  if ! rclone copy "$LOCAL_FILE" "${RCLONE_REMOTE}:${BACKUP_S3_BUCKET}/"; then
    # Não apaga o dump local: o operador ainda tem o arquivo p/ reenviar manualmente.
    fail "rclone copy falhou — dump local preservado em $LOCAL_FILE (reenvie manual)."
  fi
  log "INFO" "Cópia offsite OK."
fi

# --- 3. Retenção local --------------------------------------------------------
# A retenção REMOTA (BACKUP_RETENTION_DAYS_REMOTE) é aplicada via lifecycle rule do
# bucket, configurada no provedor — ver docs/RUNBOOK-BACKUP-RESTORE.md.
DELETED="$(find "$BACKUP_DIR" -name '*.sql.gz' -mtime +"$BACKUP_RETENTION_DAYS_LOCAL" -print -delete 2>/dev/null | wc -l | tr -d ' ')"
log "INFO" "Retenção local: removidos $DELETED dump(s) > ${BACKUP_RETENTION_DAYS_LOCAL} dia(s)."

log "INFO" "Backup concluído com sucesso."
