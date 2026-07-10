#!/usr/bin/env bash
#
# restore.sh — restaura um dump (.sql.gz) do Postgres num alvo DESCARTÁVEL/staging.
# Story 3.3 (Backups automatizados + offsite + restore testado) — AC3 / IV2.
#
# ATENÇÃO: o alvo do restore PRECISA ter o papel `e1p_app` já criado. O bootstrap
# `infra/docker/initdb-prod/01-rls-enforce.sh` só roda na PRIMEIRA inicialização de um
# volume vazio (docker-entrypoint-initdb.d). Portanto mire um Postgres com volume NOVO
# (staging da Story 3.1 OU um Postgres efêmero subido do mesmo compose com volume novo).
# Restaurar sobre um volume já inicializado NÃO recria o papel — ver runbook.
#
# Uso:
#   ./restore.sh --force /opt/e1p-backups/e1pdb-2026-07-10_030000.sql.gz
#   ./restore.sh --force --latest-offsite
#
# Flags:
#   --force            OBRIGATÓRIA. Guarda de segurança contra sobrescrever um banco com
#                      dados por acidente (o alvo típico é ambiente descartável/staging).
#   --latest-offsite   baixa o dump mais recente do remote rclone antes de restaurar
#                      (em vez de receber um path local).
#
# Variáveis (via ambiente ou infra/.env.prod): COMPOSE_FILE, ENV_FILE, BACKUP_DIR,
#   BACKUP_S3_BUCKET, RCLONE_REMOTE, POSTGRES_DB, POSTGRES_USER (ver backup.sh / .env.prod.example).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-$INFRA_DIR/docker-compose.traefik.yml}"
ENV_FILE="${ENV_FILE:-$INFRA_DIR/.env.prod}"
BACKUP_DIR="${BACKUP_DIR:-/opt/e1p-backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-e1p-offsite}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

DB_NAME="${POSTGRES_DB:-e1pdb}"
DB_SUPERUSER="${POSTGRES_USER:-e1p_root}"

FORCE=0
LATEST_OFFSITE=0
DUMP=""

for arg in "$@"; do
  case "$arg" in
    --force)          FORCE=1 ;;
    --latest-offsite) LATEST_OFFSITE=1 ;;
    -*)               echo "Flag desconhecida: $arg" >&2; exit 2 ;;
    *)                DUMP="$arg" ;;
  esac
done

log() { printf '%s [%s] %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)" "$1" "$2"; }
fail() { log "ERROR" "$1"; exit 1; }

if [ "$FORCE" -ne 1 ]; then
  fail "restore ABORTADO: passe --force explicitamente (guarda contra sobrescrever dados)."
fi

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# --- Origem do dump -----------------------------------------------------------
if [ "$LATEST_OFFSITE" -eq 1 ]; then
  command -v rclone >/dev/null 2>&1 || fail "rclone não instalado — não dá p/ usar --latest-offsite."
  [ -n "${BACKUP_S3_BUCKET:-}" ] || fail "BACKUP_S3_BUCKET não definido — não dá p/ localizar o dump remoto."
  mkdir -p "$BACKUP_DIR"
  log "INFO" "Procurando o dump mais recente em ${RCLONE_REMOTE}:${BACKUP_S3_BUCKET}/ ..."
  LATEST="$(rclone lsf "${RCLONE_REMOTE}:${BACKUP_S3_BUCKET}/" --include '*.sql.gz' 2>/dev/null | sort | tail -n1)"
  [ -n "$LATEST" ] || fail "nenhum *.sql.gz encontrado no offsite."
  log "INFO" "Baixando $LATEST ..."
  rclone copy "${RCLONE_REMOTE}:${BACKUP_S3_BUCKET}/${LATEST}" "$BACKUP_DIR/" || fail "download do offsite falhou."
  DUMP="$BACKUP_DIR/$LATEST"
fi

[ -n "$DUMP" ] || fail "informe um path de dump .sql.gz OU use --latest-offsite."
[ -f "$DUMP" ] || fail "dump não encontrado: $DUMP"

# --- Restore ------------------------------------------------------------------
log "INFO" "Restaurando $DUMP -> db=$DB_NAME (compose=$COMPOSE_FILE)"
# ON_ERROR_STOP=1: qualquer erro no SQL derruba o restore (não engole falhas silenciosas).
if ! gunzip -c "$DUMP" | compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$DB_SUPERUSER" -d "$DB_NAME"; then
  fail "restore falhou — verifique se o alvo tem o papel e1p_app e o volume correto (ver runbook)."
fi

log "INFO" "Restore concluído. Valide agora conforme docs/RUNBOOK-BACKUP-RESTORE.md:"
log "INFO" "  1) \\dt  -> tabelas de negócio presentes (users, tenants, agenda_events, crm_clients...)"
log "INFO" "  2) \\du  -> papel e1p_app existe (NOSUPERUSER)"
log "INFO" "  3) isolamento RLS: SET app.current_tenant_id + SELECT como e1p_app não vaza cross-tenant."
