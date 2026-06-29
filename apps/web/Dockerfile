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
RUN pnpm --filter @e1p/web build

FROM nginx:alpine
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
