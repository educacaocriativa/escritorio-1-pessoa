# ADR 0001 — Stack e Infraestrutura

- **Status:** Aceito
- **Data:** 2026-06-29

## Contexto
e1p é um SaaS multi-tenant grande (~19 módulos), com IA pesada (Claude), muitas integrações
(Meta Ads, WhatsApp, gateways de pagamento, OCR, assinatura digital), futura necessidade de app mobile,
e restrição explícita de **custo baixo na AWS**. Já existe um módulo (Assistente Jurídico) implementado
em FastAPI + React (`~/lex-intelligentia-app`).

## Decisão
1. **Backend: FastAPI (Python).** Reaproveita o módulo existente; Python é o terreno mais forte para
   IA/Claude, OCR e o anonimizador. Menor risco e mais rápido de evoluir.
2. **Frontend: React + Vite + TypeScript + Tailwind.** Combina com o design Figma "Portal" e com o
   módulo existente.
3. **Monorepo (pnpm workspaces para JS + app Python isolado).** Tipos e design tokens compartilhados
   entre web e a futura mobile — uma fonte de verdade.
4. **Mobile: API-first agora, app em Expo/React Native depois.** Web também servida como PWA no caminho.
5. **Multi-tenancy: PostgreSQL com Row-Level Security (RLS), banco único com `tenant_id`.**
   Mais barato (um banco) e seguro para a regra de isolamento.
6. **Infra AWS: container enxuto agora, ECS Fargate depois.** Início ~US$30-40/mês:
   1 EC2 Graviton (ARM) com Docker Compose + RDS Postgres `t4g.micro` + S3/CloudFront para o front.
   Tudo conteinerizado e 12-factor → trocar o alvo de deploy é barato.

## Alternativas consideradas e rejeitadas (por ora)
- **Next.js / NestJS / Node full-stack:** exigiria reescrever o backend Python e perder integração
  nativa de IA/OCR. SEO das landing pages será resolvido com renderização estática dedicada quando
  o módulo de Sites for construído.
- **Serverless máximo (Lambda + Aurora Serverless):** cold start e limites ruins para chamadas longas
  de IA, OCR e tempo-real (dashboard de agenda ao vivo).
- **Cloud-native dia 1 (Fargate + ALB + SQS):** melhor escala, porém mais caro parado no início.

## Consequências
- Precisamos de Docker para dev/deploy (instalar quando formos ao deploy).
- RLS exige disciplina: toda tabela de negócio tem `tenant_id` e política RLS; acesso sempre via
  camada de tenancy.
- Caminho de migração para Fargate deve ser mantido aberto (sem acoplar a EC2 específica).
