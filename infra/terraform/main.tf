# Esqueleto de IaC do e1p — Fase A (enxuta). Ver docs/AWS-DEPLOYMENT.md.
# Provisionamento real é preenchido no momento do primeiro deploy.
# Mantido como stub para fixar a estrutura e as decisões de custo.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # backend "s3" {}  # configurar bucket de state remoto no primeiro deploy
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "sa-east-1" # São Paulo (latência BR)
}

variable "project" {
  type    = string
  default = "e1p"
}

# Componentes da Fase A a declarar quando formos ao deploy:
# - aws_s3_bucket            (frontend estático + uploads)
# - aws_cloudfront_distribution (CDN + wildcard *.e1p.com)
# - aws_db_instance          (RDS Postgres t4g.micro, single-AZ)
# - aws_instance             (EC2 t4g.small Graviton com Docker)  -- ou App Runner
# - aws_ecr_repository       (imagens da API)
# - aws_sqs_queue            (jobs assíncronos)
# - aws_ssm_parameter        (segredos)
# - aws_budgets_budget       (guard-rail de custo)
