# e1p — Empresa de 1 Pessoa

SaaS multi-tenant white-label para profissionais autônomos, com IA (Claude) integrada em todos os módulos.

> 📌 **Comece por [`CLAUDE.md`](CLAUDE.md)** — a memória viva do projeto (visão, stack, regras de ouro, estado).

## Documentação
- [`CLAUDE.md`](CLAUDE.md) — contexto do projeto (carregado em toda sessão de IA)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — arquitetura técnica
- [`docs/MODULES.md`](docs/MODULES.md) — os 19 módulos + ordem de construção
- [`docs/AWS-DEPLOYMENT.md`](docs/AWS-DEPLOYMENT.md) — deploy AWS custo-consciente
- [`docs/decisions/`](docs/decisions/) — ADRs (decisões de arquitetura)

## Estrutura
```
apps/api/        Backend FastAPI (Python)
apps/web/        Frontend React + Vite + TS + Tailwind
packages/        shared-types · design-tokens
infra/           docker-compose (dev) · Dockerfiles · terraform (AWS)
.claude/agents/  Agentes de QA (regressão, bugs, duplicação)
scripts/         check.sh e utilitários
```

## Dev local (resumo)
```bash
# Requisitos: Docker, Node 22 + pnpm, Python 3.13
cp .env.example .env            # preencha ANTHROPIC_API_KEY etc.
# --env-file é OBRIGATÓRIO: com só "-f infra/docker-compose.yml", o Compose v5 procura
# o .env dentro de infra/ (não na raiz) e ignora suas variáveis silenciosamente.
docker compose --env-file .env -f infra/docker-compose.yml up --build
# Web:  http://localhost:5173    API: http://localhost:8000/health
```

## Qualidade (obrigatório a cada mudança)
```bash
bash scripts/check.sh           # lint + types + testes (backend e web)
```
Mais os agentes de QA em `.claude/agents/` (ver `CLAUDE.md` §5).
