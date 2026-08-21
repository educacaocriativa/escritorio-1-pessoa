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

# A imagem oficial tem ENTRYPOINT null e o CMD completo (`caddy run --config ... --adapter
# caddyfile`). Pondo o entrypoint aqui, esse CMD chega ao script como "$@" e e repassado com
# `exec` — nada da imagem base precisa ser reescrito.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
