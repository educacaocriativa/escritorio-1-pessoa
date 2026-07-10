# Epic 3: Deploy, Storage & Observabilidade

> **Classificação:** BLOQUEANTE para o lançamento (monitoramento e storage-S3 são bloqueante-leve/faseáveis).
> **Sequenciamento:** terceiro epic do go-live. Fonte: `docs/prd.md` §8; guias `docs/HOSTINGER-DEPLOY.md` e
> `docs/AWS-DEPLOYMENT.md`; dívida em `CLAUDE.md` §6.1.

## Contexto do sistema existente (para o @sm)
A app é 100% conteinerizada (12-factor). Já existe um **bundle de deploy commitado** (`59ff179`) para VPS
Hostinger: `infra/docker-compose.prod.yml` (Caddy próprio, TLS Let's Encrypt), `infra/docker-compose.traefik.yml`
(integra ao Traefik compartilhado da VPS de produção `e1p.doroeventos.com.br`), `infra/Caddyfile`,
`infra/.env.prod.example`, `infra/docker/initdb-prod/01-rls-enforce.sh` (cria o papel non-superuser `e1p_app`
essencial pro RLS) e o guia `docs/HOSTINGER-DEPLOY.md`. O container `api` roda `alembic upgrade head` + seed
no boot. Lacunas conhecidas: **não há staging**, **não há CI** rodando os testes na imagem de produção (houve
um bug de drift venv↔produção — versão do FastAPI divergente escondeu um erro de rota 204 que só quebrou no
container), **backup** é só um cron sugerido na própria VPS (sem cópia offsite nem restore testado),
**não há monitoramento/alertas**, e o teste de isolamento cross-tenant (RLS é Postgres-only) só foi validado
manualmente. Anexos hoje são `LargeBinary` no Postgres (módulo Anexos, componente `Attachments.tsx`),
incham banco/backup. O caminho AWS (EC2 Graviton → ECS Fargate, RDS, S3/CloudFront) é a evolução documentada.

## Epic Goal
Transformar o bundle de deploy Hostinger já commitado numa esteira repetível e segura: validar cada deploy
num staging antes de produção, garantir que os testes rodem dentro da imagem Docker (matando o drift
venv↔prod), proteger os dados com backups offsite testados, ter visibilidade mínima de disponibilidade, e
dar destino durável aos arquivos.

## Integration Requirements
Manter 12-factor para não acoplar à VPS específica (caminho AWS aberto). A app sempre roda como papel
non-superuser `e1p_app` (RLS válida). Nenhuma mudança pode quebrar os ~252 testes existentes; o CI passa a
ser gate obrigatório antes do deploy. Custo respeita o guard-rail (soluções baratas/self-hosted).

---

## Story 3.1 — Ambiente de staging espelhando produção
As a **operador do go-live**,
I want **um ambiente de staging com a mesma imagem de produção e dados sintéticos**,
so that **cada deploy seja validado antes de ir para produção, sem risco ao dado real**.

### Acceptance Criteria
1. Existe um staging que sobe a mesma imagem/compose de produção (`docker-compose.prod.yml` ou `.traefik.yml`), com `.env` próprio e dados sintéticos (seed), isolado da produção.
2. O fluxo de release documenta: deploy em staging → validação (smoke test dos módulos-chave) → promoção para produção.
3. Staging usa segredos próprios e nunca aponta para o banco/credenciais de produção.

### Integration Verification
- IV1: Subir o staging roda `alembic upgrade head` + seed e responde no `/health` (mesma topologia do dev/prod).
- IV2: O papel `e1p_app` non-superuser é criado no staging (RLS válida), igual à produção.
- IV3: Nenhuma configuração de staging afeta produção (redes/volumes/segredos isolados).

## Story 3.2 — CI testando a imagem Docker de produção
As a **operador do go-live**,
I want **um CI que rode a suíte de testes DENTRO da imagem Docker de produção e o e2e de isolamento cross-tenant**,
so that **o drift venv↔produção seja pego antes do deploy e o isolamento RLS seja garantido automaticamente**.

### Acceptance Criteria
1. O CI builda a imagem de produção e roda a suíte completa (`scripts/check.sh`/pytest) **dentro** dela, não só no venv local.
2. O CI executa o teste de isolamento cross-tenant no Postgres real (testcontainers), hoje só validado manualmente.
3. O CI é **gate obrigatório**: um deploy só é promovido se o CI passar; falha bloqueia o deploy.

### Integration Verification
- IV1: Todos os ~252 testes existentes continuam passando na imagem de produção.
- IV2: O teste de isolamento reproduz o cenário "João não vê dados da Maria" no Postgres real.
- IV3: O gate não introduz falso-positivo que trave deploys legítimos (pipeline estável).

## Story 3.3 — Backups automatizados + offsite + restore testado
As a **dono do negócio**,
I want **backups diários do Postgres copiados para fora da VPS, com restauração testada**,
so that **os dados sobrevivam à perda do servidor inteiro**.

### Acceptance Criteria
1. Um job diário faz `pg_dump` (gzip) do banco de produção (evoluindo o cron do `HOSTINGER-DEPLOY.md`).
2. Os dumps são copiados para storage **offsite** (S3/outro), com retenção definida.
3. Um procedimento de **restauração** é executado e validado ao menos uma vez (restore em staging a partir de um dump), documentado no runbook.

### Integration Verification
- IV1: O backup roda sem interromper a aplicação em produção.
- IV2: O restore em staging reconstrói o banco íntegro (RLS/papel `e1p_app` preservados).
- IV3: A cópia offsite existe e é acessível (não fica só na VPS).

## Story 3.4 — Monitoramento e alertas
As a **operador do go-live**,
I want **monitorar disponibilidade (health da API, TLS, disco, restart de container) com alerta acionável**,
so that **eu saiba de uma queda antes do cliente e possa reagir**.

### Acceptance Criteria
1. Há monitoramento de uptime/health da API (`/health`) e da validade do TLS (Caddy/Traefik), com alerta (ex.: Uptime Kuma + notificação).
2. Sinais básicos de host são observados: disco e reinícios de container.
3. Um alerta chega por um canal acionável (e-mail/WhatsApp/Telegram) quando um check falha.

### Integration Verification
- IV1: O monitoramento não impacta a performance da aplicação (checks leves).
- IV2: Um teste de queda simulada (parar o container) dispara o alerta.
- IV3: Custo do monitoramento respeita o guard-rail (NFR3) — solução barata/self-hosted preferida.

## Story 3.5 — Storage durável de anexos (object storage S3-compatível)
As a **dono do negócio**,
I want **mover os anexos de bytes-no-Postgres para object storage isolado por tenant**,
so that **o banco/backup não inche e os arquivos escalem com segurança**.

### Acceptance Criteria
1. O módulo de Anexos passa a persistir os arquivos em object storage S3-compatível (mantendo `owner_type`/`owner_id`/`label` e o isolamento por tenant), em vez de `LargeBinary` no Postgres.
2. Upload, listagem, download e delete continuam funcionando pela mesma interface (componente `Attachments.tsx` e endpoints atuais inalterados no contrato).
3. Anexos existentes são migrados (ou plano de migração documentado); o download de anexos antigos continua funcionando.

### Integration Verification
- IV1: Contas a Pagar/Receber (boleto/contrato) e a Agenda (anexos do evento) continuam exibindo/baixando os arquivos.
- IV2: Isolamento por tenant preservado (um tenant não acessa arquivo de outro).
- IV3: O tamanho do dump do Postgres cai após a migração (validar no backup).
