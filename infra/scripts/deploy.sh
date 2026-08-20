#!/usr/bin/env bash
# deploy.sh — sobe uma nova versao do e1p no ambiente em que ESTE host roda.
#
# O ambiente NAO e passado por flag: ele e detectado a partir do compose file com que a stack
# em pe foi criada (o mesmo label que o runbook manda conferir a mao). Escolher o compose errado
# no host errado e o modo de errar mais caro daqui, e ele deixa de existir quando ninguem escolhe.
#
#   ./infra/scripts/deploy.sh                 # deploya origin/main
#   ./infra/scripts/deploy.sh --ref <sha>     # deploya uma versao especifica
#   ./infra/scripts/deploy.sh --dry-run       # imprime o plano e sai, sem tocar em nada
#   ./infra/scripts/deploy.sh --skip-ci       # pula o gate de CI (grita ao fazer)
#
# Roda SEMPRE no servidor. Da sua maquina, em uma linha:
#   ssh -t <host> "cd /opt/e1p && ./infra/scripts/deploy.sh"
#   (o -t aloca terminal; sem ele a confirmacao de producao nao funciona)
set -euo pipefail

REPO_GH="educacaocriativa/escritorio-1-pessoa"
JOBS_EXIGIDOS=(secret-scan frontend test-in-prod-image cross-tenant-rls)
# Normalmente a raiz e deduzida da posicao do proprio script. E1P_RAIZ existe para rodar uma
# copia de fora do checkout (validar uma versao do script antes de ela estar mergeada, p.ex.).
RAIZ="${E1P_RAIZ:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

REF="main"
DRY_RUN=0
PULA_CI=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) REF="${2:?--ref exige um valor}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --skip-ci) PULA_CI=1; shift ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}" | cut -c3-; exit 0 ;;
    *) echo "flag desconhecida: $1" >&2; exit 2 ;;
  esac
done

titulo() { printf '\n=== %s ===\n' "$*"; }
ok()     { printf '  OK   %s\n' "$*"; }
aviso()  { printf '  !    %s\n' "$*"; }
morre()  { printf '\nABORTADO: %s\n' "$*" >&2; exit 1; }

cd "$RAIZ"

# --- 1. Qual ambiente e este? -------------------------------------------------
titulo "Ambiente"

LABEL_CHAVE='{{index .Config.Labels "com.docker.compose.project.config_files"}}'
LABELS="$(docker inspect infra-api-1 --format "$LABEL_CHAVE" 2>/dev/null || true)"
[[ -n "$LABELS" ]] || morre "nao achei o container infra-api-1. A stack esta de pe neste host?"

tem_traefik=0
tem_prod=0
[[ "$LABELS" == *docker-compose.traefik.yml* ]] && tem_traefik=1
[[ "$LABELS" == *docker-compose.prod.yml* ]] && tem_prod=1
(( tem_traefik + tem_prod == 1 )) || morre "nao identifiquei o ambiente a partir de: $LABELS"

if (( tem_traefik )); then
  PERFIL="hostinger"
  COMPOSE_ARQ="docker-compose.traefik.yml"
  # o .traefik.yml usa ${VAR:?}; sem --env-file o compose nem consegue listar os servicos
  COMPOSE_FLAGS=(--env-file .env.prod)
  DOMINIO="e1p.doroeventos.com.br"
  EH_PROD=0
  PAPEL="desenvolvimento/teste"
else
  PERFIL="aws"
  COMPOSE_ARQ="docker-compose.prod.yml"
  # este resolve o env por env_file: interno, nao precisa da flag
  COMPOSE_FLAGS=()
  DOMINIO="e1p.criativaeduca.com.br"
  EH_PROD=1
  PAPEL="PRODUCAO"
fi
ok "perfil $PERFIL ($PAPEL) - $COMPOSE_ARQ - https://$DOMINIO"

# O superusuario do Postgres nao e "postgres" aqui; perguntar ao container evita chutar.
PG_USER="$(docker exec infra-postgres-1 printenv POSTGRES_USER)"
PG_DB="$(docker exec infra-postgres-1 printenv POSTGRES_DB)"
psql_() { docker exec infra-postgres-1 psql -U "$PG_USER" -d "$PG_DB" -tAc "$1"; }
compose_() { (cd "$RAIZ/infra" && docker compose "${COMPOSE_FLAGS[@]}" -f "$COMPOSE_ARQ" "$@"); }
bundle_servido() {
  curl -sS --max-time 20 "https://$DOMINIO/" 2>/dev/null \
    | grep -oE '/assets/index-[A-Za-z0-9_-]+[.]js' | head -1 || true
}

# --- 2. O checkout esta limpo? ------------------------------------------------
[[ -z "$(git status --porcelain)" ]] || morre "ha mudancas nao commitadas em $RAIZ - resolva antes de deployar"

git fetch origin --quiet
SHA_ANTES="$(git rev-parse HEAD)"
SHA_ALVO="$(git rev-parse "origin/$REF" 2>/dev/null || git rev-parse "$REF" 2>/dev/null || true)"
[[ -n "$SHA_ALVO" ]] || morre "nao consegui resolver a ref '$REF'"

if [[ "$SHA_ANTES" == "$SHA_ALVO" ]]; then
  ok "ja esta em $(git log --oneline -1 "$SHA_ALVO")"
  printf '\nNada a fazer.\n'
  exit 0
fi

titulo "O que vai subir"
echo "  de:   $(git log --oneline -1 "$SHA_ANTES")"
echo "  para: $(git log --oneline -1 "$SHA_ALVO")"
echo "  ($(git rev-list --count "$SHA_ANTES..$SHA_ALVO") commits)"

MIGRATION=0
FRONT=0
git diff --name-only "$SHA_ANTES..$SHA_ALVO" -- apps/api/migrations/versions | grep -q . && MIGRATION=1
git diff --name-only "$SHA_ANTES..$SHA_ALVO" -- apps/web packages | grep -q . && FRONT=1
if (( MIGRATION )); then aviso "traz migration - backup obrigatorio"; else ok "sem migration"; fi
if (( FRONT )); then ok "mexe no front - o bundle DEVE mudar"; else ok "nao mexe no front - o bundle deve permanecer igual"; fi

# --- 3. O CI passou nessa versao? ---------------------------------------------
titulo "CI"
if (( PULA_CI )); then
  aviso "GATE DE CI PULADO por --skip-ci. Voce esta subindo codigo nao verificado."
else
  # check-runs, NAO /status: o endpoint legado devolve "pending" num commit inteiramente verde,
  # porque este repo reporta por check-runs. Usar /status bloquearia todo deploy.
  CI_URL="https://api.github.com/repos/$REPO_GH/commits/$SHA_ALVO/check-runs"
  CI_JSON="$(curl -sS --max-time 30 "$CI_URL" 2>/dev/null || true)"
  [[ -n "$CI_JSON" ]] || morre "nao consegui consultar o CI (rede?). Use --skip-ci se souber o que esta fazendo."
  FILTRO='[.check_runs[]? | select(.name==$n)] | last | .conclusion // "ausente"'
  for job in "${JOBS_EXIGIDOS[@]}"; do
    concl="$(printf '%s' "$CI_JSON" | jq -r --arg n "$job" "$FILTRO")"
    [[ "$concl" == "success" ]] || morre "o job $job esta '$concl' em ${SHA_ALVO:0:7} - so subimos versao com CI verde."
    ok "$job"
  done
fi

# --- 4. Retrato do "antes" ----------------------------------------------------
titulo "Antes"
ALEMBIC_ANTES="$(psql_ 'select version_num from alembic_version' | tr -d '[:space:]')"
BUNDLE_ANTES="$(bundle_servido)"
ok "alembic: ${ALEMBIC_ANTES:-?}"
ok "bundle:  ${BUNDLE_ANTES:-(nao identificado)}"

if (( DRY_RUN )); then
  titulo "DRY-RUN - nada foi alterado"
  echo "  faria: docker compose ${COMPOSE_FLAGS[*]} -f $COMPOSE_ARQ up -d --build"
  if (( EH_PROD || MIGRATION )); then echo "  faria: backup antes"; fi
  exit 0
fi

if (( EH_PROD )); then
  titulo "Confirmacao"
  echo "  Isto e PRODUCAO ($DOMINIO)."
  read -r -p "  Digite aws para seguir: " resp
  [[ "$resp" == "aws" ]] || morre "confirmacao nao conferiu"
fi

# --- 5. Backup ----------------------------------------------------------------
titulo "Backup"
ULTIMO_BKP=""
if (( EH_PROD || MIGRATION )); then
  if COMPOSE_FILE="$RAIZ/infra/$COMPOSE_ARQ" "$RAIZ/infra/scripts/backup.sh" >/dev/null 2>&1; then
    ULTIMO_BKP="$(ls -t /opt/e1p-backups/* 2>/dev/null | head -1 || true)"
    ok "backup feito: ${ULTIMO_BKP:-/opt/e1p-backups/}"
  else
    morre "o backup falhou - nao sigo sem rede de seguranca"
  fi
else
  ok "dispensado (dev, sem migration)"
fi

# --- 6. Atualizar e reconstruir ----------------------------------------------
titulo "Deploy"
if [[ "$REF" == "main" ]]; then
  git checkout --quiet main
  git merge --ff-only origin/main
else
  git checkout --quiet --detach "$SHA_ALVO"
fi
ok "checkout em $(git rev-parse --short HEAD)"

# Sem nomear servico de proposito: "up -d --build web" reconstroi SO o nomeado e deixa o resto
# servindo build velho, silenciosamente. E nunca --remove-orphans: o mesmo project name e
# compartilhado com o compose de monitoring, e a flag mataria o Uptime Kuma.
compose_ up -d --build

# --- 7. Provar que subiu ------------------------------------------------------
titulo "Verificacao"
printf '  aguardando a API responder'
saude=""
for _ in $(seq 1 30); do
  saude="$(curl -sS --max-time 5 "https://$DOMINIO/api/health" 2>/dev/null || true)"
  case "$saude" in *status*ok*) break ;; esac
  printf '.'
  sleep 4
done
printf '\n'
case "$saude" in
  *status*ok*) ok "health: $saude" ;;
  *) morre "a API nao respondeu saudavel a tempo. Backup: ${ULTIMO_BKP:-/opt/e1p-backups/} | voltar para: ${SHA_ANTES:0:7}" ;;
esac

caidos="$(compose_ ps --format '{{.Name}} {{.State}}' 2>/dev/null | grep -v ' running' || true)"
if [[ -z "$caidos" ]]; then ok "todos os containers de pe"; else aviso "fora do ar: $caidos"; fi

ALEMBIC_DEPOIS="$(psql_ 'select version_num from alembic_version' | tr -d '[:space:]')"
HEAD_REPO="$(ls apps/api/migrations/versions/*.py | sed 's|.*/||' | grep -oE '^[0-9]+' | sort -n | tail -1)"
if [[ "$ALEMBIC_DEPOIS" == "$HEAD_REPO" ]]; then
  ok "alembic: $ALEMBIC_ANTES -> $ALEMBIC_DEPOIS (head do repo)"
else
  morre "alembic ficou em '$ALEMBIC_DEPOIS' mas o repo pede '$HEAD_REPO' - a migration nao aplicou."
fi

BUNDLE_DEPOIS="$(bundle_servido)"
if (( FRONT )); then
  if [[ -n "$BUNDLE_DEPOIS" && "$BUNDLE_DEPOIS" != "$BUNDLE_ANTES" ]]; then
    ok "bundle mudou: ${BUNDLE_ANTES:-?} -> $BUNDLE_DEPOIS"
  else
    morre "o diff mexe no front mas o bundle servido continua '$BUNDLE_DEPOIS' - o web esta servindo build velho."
  fi
else
  if [[ "$BUNDLE_DEPOIS" == "$BUNDLE_ANTES" ]]; then
    ok "bundle inalterado, como esperado"
  else
    aviso "o bundle mudou ($BUNDLE_ANTES -> $BUNDLE_DEPOIS) sem o diff tocar o front - vale entender."
  fi
fi

titulo "Pronto"
echo "  $PERFIL: ${SHA_ANTES:0:7} -> $(git rev-parse --short HEAD)  ($DOMINIO)"
