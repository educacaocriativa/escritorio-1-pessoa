# Build estático e serve via nginx (em prod, o estático vai para S3+CloudFront).
FROM node:22-alpine AS build
WORKDIR /repo

# Habilita pnpm
RUN corepack enable

# Copia manifestos do monorepo para cache de dependências
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml* ./
COPY packages ./packages
COPY apps/web ./apps/web

RUN pnpm install --frozen-lockfile || pnpm install
# Domínio raiz usado pra exibir o endereço de subdomínio do tenant (Story 4.4) — Vite só
# expõe env vars prefixadas com VITE_ e as embute no bundle em build-time (SPA estática,
# sem servidor Node em runtime). Default "e1p.com" bate com o default do backend
# (Settings.root_domain em app/config.py) para dev/build sem o arg explícito.
ARG VITE_ROOT_DOMAIN=e1p.com
ENV VITE_ROOT_DOMAIN=$VITE_ROOT_DOMAIN
RUN pnpm --filter @e1p/web build

FROM nginx:alpine
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
