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

# O project name do compose, lido do MESMO container (nao cravado): e ele que da nome tanto a
# imagem construida (`<projeto>-web`) quanto ao label pelo qual achamos o container do web.
PROJETO="$(docker inspect infra-api-1 --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null || true)"

tem_traefik=0
tem_prod=0
[[ "$LABELS" == *docker-compose.traefik.yml* ]] && tem_traefik=1
[[ "$LABELS" == *docker-compose.prod.yml* ]] && tem_prod=1
(( tem_traefik + tem_prod == 1 )) || morre "nao identifiquei o ambiente a partir de: $LABELS"

if (( tem_traefik )); then
  PERFIL="hostinger"
  COMPOSE_ARQ="docker-compose.traefik.yml"
  DOMINIO="e1p.doroeventos.com.br"
  EH_PROD=0
  PAPEL="desenvolvimento/teste"
else
  PERFIL="aws"
  COMPOSE_ARQ="docker-compose.prod.yml"
  DOMINIO="e1p.criativaeduca.com.br"
  EH_PROD=1
  PAPEL="PRODUCAO"
fi

# Os compose files vem do PROPRIO label, nao de uma lista escrita aqui: a stack em pe registra
# TODOS os arquivos com que foi criada, override local incluso. Detectar em vez de escolher e a
# premissa deste script, e este era o unico ponto em que ela nao valia.
#
# Cravar a lista custou a producao em 2026-08-20: a AWS tem um `docker-compose.override.yml`
# NAO versionado (monta um Caddyfile sem o bloco wildcard, que exige um CLOUDFLARE_API_TOKEN
# vazio ali de proposito). Recriar sem ele fez o Caddy recusar a config INTEIRA -- `missing API
# token` -- e derrubar ate o dominio unico, com o certificado dele intacto em disco. ~40 min
# fora do ar. Ver issue #151 e /opt/e1p/DEPLOY-AWS.md (runbook local, nao versionado).
COMPOSE_ARGS=()
IFS=',' read -ra _arqs <<< "$LABELS"
for _a in "${_arqs[@]}"; do
  _a="${_a#"${_a%%[![:space:]]*}"}"; _a="${_a%"${_a##*[![:space:]]}"}"
  [[ -n "$_a" ]] && COMPOSE_ARGS+=(-f "$_a")
done
(( ${#COMPOSE_ARGS[@]} )) || morre "nao consegui derivar os compose files de: $LABELS"

# --env-file e obrigatorio nos DOIS perfis, e a excecao que existia aqui era falsa: os dois
# compose files usam ${VAR} para as senhas, e interpolacao NAO vem do `env_file:` de servico.
# Sem a flag o compose morre em "required variable APP_DB_PASSWORD is missing" antes de
# conseguir listar um servico sequer (medido na AWS em 2026-08-20).
COMPOSE_FLAGS=(--env-file .env.prod)

ok "perfil $PERFIL ($PAPEL) - https://$DOMINIO"
ok "compose: ${COMPOSE_ARGS[*]}"

# O superusuario do Postgres nao e "postgres" aqui; perguntar ao container evita chutar.
PG_USER="$(docker exec infra-postgres-1 printenv POSTGRES_USER)"
PG_DB="$(docker exec infra-postgres-1 printenv POSTGRES_DB)"
psql_() { docker exec infra-postgres-1 psql -U "$PG_USER" -d "$PG_DB" -tAc "$1"; }
compose_() { (cd "$RAIZ/infra" && docker compose "${COMPOSE_FLAGS[@]}" "${COMPOSE_ARGS[@]}" "$@"); }
bundle_servido() {
  curl -sS --max-time 20 "https://$DOMINIO/" 2>/dev/null \
    | grep -oE '/assets/index-[A-Za-z0-9_-]+[.]js' | head -1 || true
}
# O web esta rodando o que o `up -d --build` acabou de construir? A pergunta certa e "o container em
# pe esta na imagem mais nova?", e nao "a imagem mudou?": o build pode sair 100% de cache (o `dist/`
# nao mudou) e o compose entao nem recria o container -- um deploy correto, que a pergunta errada
# acusaria. Ela vale para `public/`, para e2e e para codigo real.
#
# Mas comparar IDs de imagem NAO serve nesta AWS (Docker Compose v5.5.0), e custou dois falsos
# alarmes em producao, em 2026-10-01 e 2026-10-02: o deploy estava certo (API saudavel, alembic no
# head, `api` e `worker` recriados) e o script abortou no fim, "o container do web roda a imagem
# 375550b39186 mas a construida agora e 7d25aa8dc180". Fatos medidos: os ids diferiam com o
# CONTEUDO identico (build 100% de cache); `up -d --no-deps web` dizia `Container infra-web-1
# Running`; o label `com.docker.compose.image` do container era um TERCEIRO id (f21f19fa1178); so
# `--force-recreate` igualava os ids. A causa PROVAVEL (nao verificada) e que a attestation/
# provenance do build gera um digest de indice novo a cada build, enquanto o compose decide pelo
# digest dele. Para confirmar no host: `docker image inspect <id antigo> --format '{{json .RootFS.Layers}}'`
# e comparar com o da imagem nova -- camadas iguais confirmam.
#
# Entao a comparacao e por CONTEUDO: as camadas do filesystem (`RootFS.Layers`) da imagem do
# container contra as da recem-construida. Camadas iguais = mesmo conteudo, ids diferentes ou nao.
# Retorno: 0 = mesmo conteudo | 1 = conteudo diferente | 2 = nao deu para comparar.
camadas_da_imagem() { # $1 = id ou nome da imagem
  docker image inspect "$1" --format '{{json .RootFS.Layers}}' 2>/dev/null || true
}
imagem_do_web_esta_atual() { # $1 = imagem do container em pe, $2 = imagem recem-construida
  [[ -n "$1" && -n "$2" ]] || return 2
  [[ "$1" == "$2" ]] && return 0
  local a b
  a="$(camadas_da_imagem "$1")"
  b="$(camadas_da_imagem "$2")"
  # Camadas validas comecam por `["sha256:`. Vazio, `[]` ou `null` (imagem antiga ja podada, p.ex.)
  # nao e "conteudo igual": e que nao ha o que comparar.
  [[ "$a" == '["sha256:'* && "$b" == '["sha256:'* ]] || return 2
  [[ "$a" == "$b" ]]
}
# Diz, para a mensagem de inconclusivo, o que nao deu para resolver.
o_que_nao_resolveu() { # $1 = imagem do container, $2 = imagem construida
  if [[ -z "$1" ]]; then echo "o id da imagem do container do web"
  elif [[ -z "$2" ]]; then echo "o id da imagem ${PROJETO}-web construida"
  elif [[ "$(camadas_da_imagem "$1")" != '["sha256:'* ]]; then echo "as camadas da imagem do container (${1:7:12})"
  else echo "as camadas da imagem construida (${2:7:12})"
  fi
}
# Le o container do web em pe e a imagem `<projeto>-web` (globais CID_WEB, IMG_EM_PE, IMG_CONSTRUIDA).
le_imagens_do_web() {
  CID_WEB="$(docker ps -q --filter "label=com.docker.compose.project=$PROJETO" --filter "label=com.docker.compose.service=web" 2>/dev/null | head -1)"
  IMG_EM_PE="$(docker inspect "$CID_WEB" --format '{{.Image}}' 2>/dev/null || true)"
  IMG_CONSTRUIDA="$(docker image inspect "${PROJETO}-web" --format '{{.Id}}' 2>/dev/null || true)"
}
# Inconclusivo NAO e reprovacao: avisa e segue. Conteudo realmente diferente (container velho de
# verdade) se cura UMA vez -- recria so o web, mesmas flags de compose, sem --remove-orphans e sem
# nomear outro servico -- e confere de novo; se ainda diverge, ai sim aborta. Depois da cura:
# sem container do web de pe e uma queda real (aborta, com mensagem propria); container de pe mas
# sem como comparar e inconclusivo de novo (avisa e segue).
garante_web_na_imagem_nova() {
  local rc=0
  le_imagens_do_web
  imagem_do_web_esta_atual "$IMG_EM_PE" "$IMG_CONSTRUIDA" || rc=$?
  case "$rc" in
    0) ok "web no conteudo recem-construido (container ${IMG_EM_PE:7:12}, imagem ${IMG_CONSTRUIDA:7:12})"; return 0 ;;
    2) aviso "nao consegui comparar a imagem do web (nao resolvi $(o_que_nao_resolveu "$IMG_EM_PE" "$IMG_CONSTRUIDA")) - checagem inconclusiva, nao e reprovacao"; return 0 ;;
  esac
  aviso "o web roda ${IMG_EM_PE:7:12}, de conteudo diferente da construida ${IMG_CONSTRUIDA:7:12} - recriando so o web, uma vez"
  compose_ up -d --no-deps --force-recreate web || morre "falhou ao recriar o web - confira 'docker compose ps' e os logs do web"
  le_imagens_do_web
  rc=0
  imagem_do_web_esta_atual "$IMG_EM_PE" "$IMG_CONSTRUIDA" || rc=$?
  case "$rc" in
    0) ok "web recriado e agora no conteudo recem-construido (${IMG_EM_PE:7:12})" ;;
    1) morre "o container do web roda a imagem ${IMG_EM_PE:7:12} e a construida agora e ${IMG_CONSTRUIDA:7:12}: o CONTEUDO difere mesmo depois de recriar o web - esta servindo build velho." ;;
    *)
      [[ -n "$CID_WEB" ]] || morre "o web nao voltou depois de recriado - confira 'docker compose ps' e os logs do web"
      aviso "web recriado e de pe, mas nao consegui comparar a imagem (nao resolvi $(o_que_nao_resolveu "$IMG_EM_PE" "$IMG_CONSTRUIDA")) - checagem inconclusiva, nao e reprovacao"
      ;;
  esac
}

# --- 2. O checkout esta limpo? ------------------------------------------------
# --untracked-files=no NAO e frouxidao: e o que torna a guarda APLICAVEL neste parque. A AWS
# carrega arquivos NAO RASTREADOS de proposito -- `DEPLOY-AWS.md`, `docker-compose.override.yml`,
# `Caddyfile.single` -- justamente para o `git pull` nunca conflitar (o passo 1 acima os cita por
# nome). `git status --porcelain` lista nao rastreado como `?? caminho`, entao a versao anterior
# ABORTAVA em 100% das execucoes naquele host: um `?? DEPLOY-AWS.md` sozinho ja derrubava.
# Medido em 2026-08-21, no primeiro `--dry-run` real depois do merge do #167.
#
# O risco que a guarda existe para pegar continua pego: arquivo VERSIONADO modificado ou em
# stage -- o caso "editei em producao para testar e esqueci" --, porque o `git pull --ff-only`
# do passo seguinte falharia no meio do deploy, ou pior, o build subiria com a edicao solta.
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || morre "ha mudancas nao commitadas em arquivo versionado de $RAIZ - resolva antes de deployar"

git fetch origin --quiet
SHA_ANTES="$(git rev-parse HEAD)"
# --verify --quiet e obrigatorio aqui: `git rev-parse <ref-inexistente>` ECOA o argumento no
# stdout antes de falhar, entao um `a || b` sem ele concatena as duas saidas e devolve um
# "SHA" de duas linhas que envenena todo comando seguinte.
SHA_ALVO="$(git rev-parse --verify --quiet "origin/$REF^{commit}" \
  || git rev-parse --verify --quiet "$REF^{commit}" || true)"
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
# Caminhos que moram sob apps/web mas NUNCA viram JS do bundle. Sem esta exclusao a asserção do
# passo 7 pede o impossivel: o Vite copia `public/` VERBATIM para a raiz do `dist/` (e assim que
# `sw.js` e `manifest.webmanifest` chegam la), e nem os `*.spec.ts` do Playwright nem os
# `*.test.tsx` do vitest sao importados pela entrada. Foi exatamente assim que o deploy do #300 --
# um unico arquivo em `public/`, a verificacao de propriedade do dominio no Google -- ABORTOU
# depois de ter subido inteiro e correto, com a producao ja saudavel (medido em 04/09/2026).
FORA_DO_BUNDLE=(':(exclude)apps/web/public' ':(exclude)apps/web/e2e' ':(exclude,glob)apps/web/**/*.test.*')
git diff --name-only "$SHA_ANTES..$SHA_ALVO" -- apps/web packages "${FORA_DO_BUNDLE[@]}" | grep -q . && FRONT=1
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

  # Exigimos TODOS os checks do commit, MENOS os listados em IGNORADOS. E uma lista de exclusao
  # de proposito, nao de inclusao: uma lista de inclusao desatualiza CALADA (quando `sast-semgrep`
  # entrou no ci.yml, um gate por inclusao teria seguido aprovando sem ele). Por exclusao o erro
  # aparece: um check novo BLOQUEIA o deploy uma vez, e ai se decide conscientemente o que fazer.
  #
  # `mutation` esta fora porque o mutation.yml roda por agendamento noturno (`on: schedule`), nao
  # em PR — o resultado dele e sinal para investigar, nunca condicao para deployar.
  IGNORADOS='^(mutation)$'
  ULTIMO_POR_NOME="[.check_runs[]? | select(.name | test(\"$IGNORADOS\") | not)] | group_by(.name) | map(max_by(.started_at))"
  VERDE='(.conclusion=="success" or .conclusion=="skipped" or .conclusion=="neutral")'

  qtd="$(printf '%s' "$CI_JSON" | jq -r "$ULTIMO_POR_NOME | length")"
  (( qtd > 0 )) || morre "nenhum check encontrado para ${SHA_ALVO:0:7} - o CI chegou a rodar nesse commit?"

  rodando="$(printf '%s' "$CI_JSON" | jq -r "$ULTIMO_POR_NOME | [.[] | select(.status!=\"completed\") | .name] | join(\", \")")"
  [[ -z "$rodando" ]] || morre "o CI ainda esta rodando em ${SHA_ALVO:0:7}: $rodando"

  ruins="$(printf '%s' "$CI_JSON" | jq -r "$ULTIMO_POR_NOME | [.[] | select($VERDE | not) | .name + \"=\" + (.conclusion // \"?\")] | join(\", \")")"
  [[ -z "$ruins" ]] || morre "check reprovado em ${SHA_ALVO:0:7}: $ruins - so subimos versao com CI verde."

  ok "$qtd checks verdes: $(printf '%s' "$CI_JSON" | jq -r "$ULTIMO_POR_NOME | [.[].name] | sort | join(\", \")")"
fi

# --- 4. Retrato do "antes" ----------------------------------------------------
titulo "Antes"
ALEMBIC_ANTES="$(psql_ 'select version_num from alembic_version' | tr -d '[:space:]')"
BUNDLE_ANTES="$(bundle_servido)"
ok "alembic: ${ALEMBIC_ANTES:-?}"
ok "bundle:  ${BUNDLE_ANTES:-(nao identificado)}"

if (( DRY_RUN )); then
  titulo "DRY-RUN - nada foi alterado"
  echo "  faria: docker compose ${COMPOSE_FLAGS[*]} ${COMPOSE_ARGS[*]} up -d --build"
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

# Esta checagem nao depende de o conteudo mudar, entao ela cobre o buraco que a exclusao do
# `FORA_DO_BUNDLE` abriria sozinha: um deploy que so mexe em `public/` cai no ramo "bundle
# inalterado, como esperado" e passaria SEM NINGUEM ter verificado que o web foi reconstruido.
# Por que compara conteudo e nao ids, e por que inconclusivo nao aborta: ver `imagem_do_web_esta_atual`
# (falsos alarmes de 2026-10-01/02) e a issue #151 (derrubar deploy por engano ja custou ~40 min).
garante_web_na_imagem_nova

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
