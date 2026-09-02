# Deploy AWS — e1p (custo-consciente)

> ## ⚠️ Como está HOJE (2026-08-20) — leia antes do resto
>
> O que está de fato em produção **não é** a Fase A descrita abaixo. A AWS foi provisionada pelo
> time do sócio como **uma EC2 só, com toda a stack em Docker Compose** — o mesmo formato da VPS:
>
> | | Planejado abaixo | Real hoje |
> |---|---|---|
> | Frontend | S3 + CloudFront | container `web` atrás do Caddy, na mesma EC2 |
> | Banco | RDS `t4g.micro` | `postgres:16-alpine` **em container**, na mesma EC2 |
> | Arquivos | S3 | `bytea` dentro do Postgres |
> | Fila | SQS | worker + Redis na mesma EC2 |
> | Segredos | SSM | `.env` no host |
> | IaC | Terraform | provisionado à mão |
>
> Confere com o planejado apenas o host: `t4g` **Graviton/ARM**, com o Compose de `docker-compose.prod.yml`.
> Domínio: **https://e1p.criativaeduca.com.br**. A VPS Hostinger (`e1p.doroeventos.com.br`) passou a
> ser dev/teste em 2026-08-20 e foi **descomissionada por completo em 2026-08-30** (containers,
> volumes, `/opt/e1p`, backups, cron, remote `rclone` e DNS — ver `docs/HOSTINGER-DEPLOY.md`).
> **Esta EC2 é hoje o único ambiente que existe: não há dev nem staging.** Toda validação que
> exigir um host roda contra a produção — trate qualquer teste aqui com esse peso.
>
> **Consequências operacionais que valem hoje**, e não quando a Fase A existir:
> - **Backup é só local** (`/opt/e1p-backups`, diário às 03:15). Não há `rclone`/offsite na AWS —
>   a VPS de dev tem, a produção não. Se a instância morrer, morrem app e banco juntos.
> - Imagens precisam buildar em **arm64**; dependência com binário só-amd64 não sobe.
> - Deploy é o `infra/scripts/deploy.sh` (abaixo), não pipeline.

## Deploy de uma nova versão (o de hoje)

```bash
ssh -t -i ~/.ssh/e1p_aws_prod flavio@<host> "cd /opt/e1p && ./infra/scripts/deploy.sh"
```

O script **detecta o ambiente sozinho** pelo compose file da stack em pé, roda o gate de CI, faz
backup, reconstrói e então **prova** o resultado (health, alembic e hash do bundle servido). Em
produção ele exige confirmação digitada. `--dry-run` mostra o plano sem executar. É o mesmo script
em dev e em prod — só muda o host de destino.

⚠️ **Ele deriva os compose files do label da stack em pé, e isso NÃO é detalhe.** Esta instância
tem um `infra/docker-compose.override.yml` **não versionado** (monta um `Caddyfile.single`, sem o
bloco wildcard) e um runbook local em `/opt/e1p/DEPLOY-AWS.md`. Rodar o compose à mão com um `-f`
só **descarta o override**: o Caddy volta com o `infra/Caddyfile` versionado, exige o
`CLOUDFLARE_API_TOKEN` que aqui é vazio de propósito, **recusa a config inteira** e derruba também
o domínio único — aconteceu em 2026-08-20, ~40 min fora do ar. Ver issue #151.

**À mão, os DOIS `-f` são obrigatórios**, e o `--env-file` também (o `docker-compose.prod.yml` usa
`${VAR}` para as senhas, e interpolação não vem do `env_file:` de serviço):

```bash
cd /opt/e1p/infra && docker compose --env-file .env.prod   -f docker-compose.prod.yml -f docker-compose.override.yml up -d
```

Antes de qualquer comando de deploy à mão: `git status` no `/opt/e1p` e leia o runbook local — o
que está no repositório é o deploy canônico, não necessariamente o desta máquina.

---

Filosofia: **começar barato e portável, escalar quando o tráfego justificar.** Tudo é container 12-factor,
então trocar o alvo de deploy não exige reescrever a aplicação.

> O que segue é o **plano** de destino, ainda não construído. Mantido como direção, não como descrição.

## Fase A — Início enxuto (~US$30-45/mês)
| Componente | Serviço | Notas de custo |
|---|---|---|
| Frontend (SPA) | **S3 + CloudFront** | Centavos. Wildcard `*.e1p.com` via Route53 + ACM (cert grátis). |
| Backend + worker | **1 EC2 `t4g.small` (Graviton/ARM)** com Docker Compose | ARM é ~20% mais barato. ~US$12/mês. |
| Banco | **RDS Postgres `t4g.micro`, single-AZ** | ~US$13/mês. Backups automáticos. |
| Arquivos | **S3** (uploads, docs gerados, mídia) | Lifecycle → Glacier p/ antigos. |
| Fila de jobs | **SQS** | Praticamente grátis no início. |
| Segredos | **SSM Parameter Store** | Grátis (vs Secrets Manager US$0.40/segredo). |
| DNS/CDN/TLS | **Route53 + CloudFront + ACM** | ACM grátis; Route53 ~US$0.50/zona. |
| Registry | **ECR** | Centavos. |

## Fase B — Escala (quando precisar)
- Backend → **ECS Fargate (Graviton)**, Spot para workers, atrás de **ALB**. Autoscaling.
- Banco → RDS Multi-AZ ou **Aurora Serverless v2** (escala por carga).
- Cache → ElastiCache (Redis) se necessário.
- Observabilidade → CloudWatch + alarmes de custo (Budgets).

## ⚠️ RLS exige papel NÃO-superusuário (isolamento de tenant)
A app NUNCA deve conectar no Postgres como superusuário — superusuários ignoram Row-Level Security
e o isolamento entre tenants vaza. Na AWS/RDS:
- O usuário master do RDS tem `rds_superuser` (faz bypass de RLS). **Não use ele na app.**
- Crie um papel dedicado `e1p_app` (NOSUPERUSER), dono das tabelas (roda as migrations), e use-o
  na `DATABASE_URL` da aplicação. Em dev isso é feito por `infra/docker/initdb/01-rls-enforce.sql`.

## Guard-rails de custo (configurar desde já)
- **AWS Budgets** com alerta em e-mail (ex.: estourou US$50/mês).
- Tudo **Graviton/ARM** onde houver opção.
- **S3 lifecycle** + CloudFront cache agressivo para reduzir egress.
- Desligar/agendar ambientes de staging fora do horário (Instance Scheduler).
- Trava de gasto no módulo de Meta Ads (limite mensal por tenant) — já previsto na spec.

## IaC
`infra/terraform/` provisiona a infra (VPC, RDS, S3, CloudFront, ECR, IAM, SSM, SQS).
Começamos com módulos mínimos da Fase A; a Fase B adiciona Fargate/ALB sem recriar dados.

## Pipeline (futuro)
GitHub Actions: build das imagens (ARM) → push ECR → deploy. Migrations Alembic rodam no start do container.
Frontend: build estático → sync S3 → invalidação CloudFront.

> **Pendência operacional:** instalar Docker localmente e configurar credenciais AWS (`aws configure`)
> quando formos ao primeiro deploy. Nada disso bloqueia o desenvolvimento local (docker-compose).
