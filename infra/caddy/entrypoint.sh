#!/bin/sh
# Monta os blocos OPCIONAIS do Caddyfile conforme o ambiente, e só então arranca o Caddy.
#
# Por que existe (issue #151): o parse do Caddyfile é ALL-OR-NOTHING. O bloco wildcard usa
# `dns cloudflare {$CLOUDFLARE_API_TOKEN}` e, com o token vazio, o Caddy recusa o arquivo
# INTEIRO (`missing API token`) — nem o domínio único sobe, mesmo com o certificado dele
# intacto em disco. Em 2026-08-20 isso derrubou a produção por ~40 min, e o contorno tinha
# sido um Caddyfile local não versionado, que some no primeiro `git pull`.
#
# A ativação é por ENV, nunca por arquivo criado à mão no servidor: config que vive só na
# máquina é invisível a qualquer leitura do repositório e o defeito só aparece na recriação
# do container, longe da mudança que o causou.
set -eu

CONF_D=/etc/caddy/conf.d
OPCIONAIS=/etc/caddy/optional

# Idempotente: recriar o container não pode acumular nem herdar bloco de um arranque anterior.
rm -rf "$CONF_D"
mkdir -p "$CONF_D"

ativa() {
	cp "$OPCIONAIS/$1" "$CONF_D/$1"
	echo "caddy/entrypoint: bloco ATIVADO -> $1"
}

# Wildcard exige os DOIS: sem ROOT_DOMAIN o endereço do site vira `*.` (inválido); sem token
# o Caddy recusa a config inteira. Um `[ -n ]` só deixaria metade da armadilha de pé.
if [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${ROOT_DOMAIN:-}" ]; then
	ativa wildcard.caddy
else
	echo "caddy/entrypoint: wildcard DESLIGADO (CLOUDFLARE_API_TOKEN e/ou ROOT_DOMAIN vazios) - o dominio unico segue normal"
fi

if [ "${MONITORING_ENABLED:-}" = "true" ]; then
	ativa monitor.caddy
else
	echo "caddy/entrypoint: monitor DESLIGADO (MONITORING_ENABLED != true)"
fi

# O CMD da imagem oficial (`caddy run --config /etc/caddy/Caddyfile --adapter caddyfile`)
# chega aqui como "$@" — repassar em vez de reescrever evita divergir da imagem base.
exec "$@"
