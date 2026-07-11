#!/usr/bin/env sh
# Monitor de disco do host para o Uptime Kuma via Push monitor (Story 3.4 — AC2).
#
# O Uptime Kuma não tem um tipo nativo de check de disco de HOST, então usamos um monitor
# tipo "Push": o Kuma gera uma URL única e espera receber um curl periódico; este script
# (rodando no host via cron) lê `df` e reporta up (uso < limiar) ou down (uso >= limiar).
# Se o Kuma parar de receber o push dentro do intervalo configurado, ele também alerta.
#
# Padrão de referência: o cron de backup do Postgres em docs/HOSTINGER-DEPLOY.md §6.
#
# Uso (cron do host, ex.: a cada 5 min). Exemplo em /etc/cron.d/e1p-disk-monitor:
#   */5 * * * * root KUMA_PUSH_URL="https://monitor.exemplo.com/api/push/XXXXXXXX" \
#     DISK_THRESHOLD=85 CHECK_PATH=/var/lib/docker \
#     /opt/e1p/infra/scripts/monitoring/disk-check.sh
#
# Variáveis (ver infra/.env.monitoring.example):
#   KUMA_PUSH_URL   (obrigatória) Push URL única do monitor de disco no Uptime Kuma.
#   DISK_THRESHOLD  (opcional, default 85) % de uso que aciona o alerta.
#   CHECK_PATH      (opcional, default /var/lib/docker) filesystem a inspecionar — por
#                   padrão o data dir do Docker, onde vivem os volumes nomeados
#                   (postgres_data / uploads_data / generated_data).
set -eu

KUMA_PUSH_URL="${KUMA_PUSH_URL:?defina a Push URL do monitor de disco do Uptime Kuma}"
DISK_THRESHOLD="${DISK_THRESHOLD:-85}"
CHECK_PATH="${CHECK_PATH:-/var/lib/docker}"

# `df -P` = formato POSIX portável (uma linha por filesystem); coluna 5 = uso em %.
USAGE="$(df -P "$CHECK_PATH" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"

if [ -z "${USAGE:-}" ]; then
  # Não conseguiu ler o disco — reporta down para não mascarar uma falha silenciosa.
  curl -fsS --max-time 10 \
    "${KUMA_PUSH_URL}?status=down&msg=disk-check-failed-to-read-${CHECK_PATH}" \
    >/dev/null 2>&1 || true
  echo "disk-check: falha ao ler df de ${CHECK_PATH}" >&2
  exit 1
fi

if [ "$USAGE" -ge "$DISK_THRESHOLD" ]; then
  STATUS="down"
else
  STATUS="up"
fi

# Reporta status + a % de uso como `ping` (aparece no gráfico do Kuma).
curl -fsS --max-time 10 \
  "${KUMA_PUSH_URL}?status=${STATUS}&msg=disk_${USAGE}pct_of_${DISK_THRESHOLD}pct&ping=${USAGE}" \
  >/dev/null
