# Caddy com o plugin de DNS da Cloudflare compilado no binário.
#
# Por quê: a imagem oficial `caddy:2-alpine` NÃO traz módulos de provedor de DNS, e o
# certificado wildcard (`*.e1p.com`) EXIGE o desafio DNS-01 — o Let's Encrypt não emite
# curinga via HTTP-01. O módulo `caddy-dns/cloudflare` precisa ser buildado com `xcaddy`
# (Story 4.4). O domínio único (IV1) continua usando o HTTP-01 automático, sem regressão.
#
# Pré-requisito operacional (fora do escopo de código): o DNS de `${ROOT_DOMAIN}` precisa
# estar gerido pela Cloudflare, e um `CLOUDFLARE_API_TOKEN` (escopo Zone.DNS Edit) definido
# no `.env.prod` — ver docs/HOSTINGER-DEPLOY.md §8.
FROM caddy:2-builder-alpine AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy

# Blocos OPCIONAIS do Caddyfile + o entrypoint que decide quais entram (issue #151).
# Eles ficam na IMAGEM, versionados no repo — a ativacao e por ENV, nunca por arquivo criado
# a mao no servidor. Config que vive so na maquina e invisivel a qualquer leitura do
# repositorio, e o defeito so aparece na recriacao do container.
COPY optional/ /etc/caddy/optional/
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# O entrypoint monta os blocos opcionais e repassa o comando com `exec "$@"`. O comando vem do
# CMD declarado LOGO ABAIXO -- nao do CMD da imagem base, que o ENTRYPOINT zera (ver o aviso).
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# ⚠️ O CMD PRECISA estar aqui, e nao herdado. Declarar ENTRYPOINT num Dockerfile **ZERA** o CMD
# da imagem base -- `docker inspect` mostrou `CMD=null` nesta imagem contra
# `CMD=["caddy","run",...]` na `caddy:2-alpine`. Sem ele o entrypoint chega no `exec "$@"` sem
# argumento nenhum, o script termina com sucesso, e o `restart: always` reinicia em loop: o
# container "saudavel" que nunca serve nada. Derrubou a producao em 2026-08-21, com exit code 0.
#
# O comentario anterior aqui dizia que "o CMD da imagem oficial chega ao script como $@" -- era
# FALSO, e nenhum dos cinco cenarios validados o pegava, porque todos passavam um comando
# explicito (`sh -c ...`) e portanto forneciam o $@ que faltava no caminho real.
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
