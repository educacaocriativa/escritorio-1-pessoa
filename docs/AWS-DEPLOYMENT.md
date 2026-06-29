# Deploy AWS — e1p (custo-consciente)

Filosofia: **começar barato e portável, escalar quando o tráfego justificar.** Tudo é container 12-factor,
então trocar o alvo de deploy não exige reescrever a aplicação.

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
