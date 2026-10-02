# Runbook — Ingestão de leads com atribuição (`POST /public/ingest/leads`)

**Para quem:** quem opera o e1p em produção. **Quando:** ao ligar um site externo ao CRM de um
tenant (hoje: nexuspublica.com.br → tenant Nexus), ao trocar a credencial, ou ao diagnosticar
lead que não chegou. Desenho: seção "Ingestão de leads com atribuição" do `CLAUDE.md`.

## 0. Onde rodar, e com qual papel (leia antes de tudo)

Produção é a EC2 da AWS (`https://e1p.criativaeduca.com.br`), com o compose em `/opt/e1p/infra`
(ver `docs/AWS-DEPLOYMENT.md`). Rodar o compose à mão exige os **dois** `-f` e o `--env-file`;
com um `-f` só, o `docker-compose.override.yml` não versionado é descartado e o Caddy cai. Nos
comandos abaixo, `DC` é este atalho:

```bash
cd /opt/e1p/infra
DC="docker compose --env-file .env.prod -f docker-compose.prod.yml -f docker-compose.override.yml"
```

**O script administrativo (`lead_ingest_admin`: `emitir-token`, `listar-tokens`, `configurar`,
`mostrar`, `revogar-token`) roda SEMPRE assim:**

```bash
$DC exec api python -m app.scripts.lead_ingest_admin <comando> ...
```

Isso o executa dentro do contêiner da API, com o papel de banco **`e1p_app`**, que sofre RLS. É
assim que a validação "funil de outro tenant não existe aqui" funciona. **Nunca** o rode conectado
como `e1p_root`: o superusuário ignora a RLS e a checagem de funil deixa de proteger o tenant.

Para **diagnóstico somente leitura** direto no banco, o usuário de produção é `e1p_root`, banco
`e1pdb` (o `e1puser` do `docker-compose.yml` é só do ambiente de desenvolvimento). Como
`e1p_root` ignora a RLS, só faça `SELECT`, e sempre com `tenant_id` explícito.

## 1. Descobrir o slug do tenant

```bash
$DC exec postgres psql -U e1p_root -d e1pdb -c \
  "SELECT id, slug, legal_name FROM tenants WHERE legal_name ILIKE '%nexus%';"
```

`tenants` é tabela global (sem RLS); o slug é o subdomínio do tenant. Abaixo, `<slug>`.

## 2. Emitir a credencial

```bash
$DC exec api python -m app.scripts.lead_ingest_admin emitir-token \
  --tenant <slug> --nome "site nexuspublica.com.br"
```

A **última linha** é o token cru. Ele aparece só agora: o e1p guarda apenas o hash.
Entregue-o direto no cofre do site (variável de ambiente que a squad do site definir) — nunca em
chat, e-mail, issue ou commit. Perdeu? Emita outro e revogue o perdido (passo 6).

Emitir e revogar **não gravam auditoria** (dívida conhecida, ver `CLAUDE.md`): anote quem fez e
quando no registro da operação.

## 3. Configurar produto e funis

> **Ordem: faça o §4 (teste de ponta a ponta) ANTES deste passo.** Com o funil `lead` mapeado
> (ou um funil de entrada padrão em Configurações), o lead de teste do §4 entra de verdade na
> jornada de Boas-vindas e dispara as mensagens reais. Sem mapeamento ainda, o teste só cria o
> card. Se já configurou, rode o §4 num tenant de teste, ou aceite a inscrição e cancele a
> jornada do "Teste Runbook" na tela de Funis antes de apagar o card.

Monte os funis no editor (Funis) e copie o id de cada um da URL. Depois:

```bash
$DC exec api python -m app.scripts.lead_ingest_admin configurar --tenant <slug> \
  --produto publia \
  --funil lead=<id do funil Boas-vindas> \
  --funil carrinho_abandonado=<id do funil Recuperação> \
  --funil compra_aprovada=<id do funil Onboarding>
$DC exec api python -m app.scripts.lead_ingest_admin mostrar --tenant <slug>
```

- `--produto publia` liga as tags `publia:reembolso`, `publia:chargeback`, `publia:cancelou`,
  `publia:lead-whatsapp` e a leitura do código na 1ª mensagem de WhatsApp. Sem produto, nada disso.
- `--funil evento=` (vazio) remove um mapeamento. Evento sem mapeamento: lead, carrinho e compra
  caem no funil de entrada padrão de Configurações; renovação, reembolso, chargeback e
  cancelamento não entram em funil nenhum.
- **A compra encerra as jornadas de entrada.** Ao chegar `compra_aprovada`, as jornadas vivas do
  contato nos funis de `lead`, `carrinho_abandonado` e no funil de entrada padrão são canceladas
  (exceto o funil da própria compra), para quem pagou não receber "esqueceu o carrinho". O site
  manda `carrinho_abandonado` assim que o pix/boleto é gerado, então o pagamento costuma chegar
  minutos depois. Como defesa em profundidade, comece o funil de Recuperação por um passo
  **"Esperar"** (ex.: 30 a 60 min): quem paga rápido nem chega a receber a 1ª mensagem.
- Eventos válidos: `lead`, `carrinho_abandonado`, `compra_aprovada`, `renovacao`, `reembolso`,
  `chargeback`, `cancelamento`.
- Slug, evento ou funil inexistente (ou de outro tenant) sai com `Erro: ...` e código 2; a
  configuração anterior fica intacta.

## 4. Testar de ponta a ponta

(Rode este passo **antes** do §3 — ver o aviso lá: o lead de teste não deve cair no funil real.)

```bash
curl -sS -X POST "https://e1p.criativaeduca.com.br/api/public/ingest/leads" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"evento":"lead","chave_idempotencia":"teste:runbook:1","ocorrido_em":"2026-10-01T10:00:00-03:00",
       "contato":{"nome":"Teste Runbook","email":"teste.runbook@example.com"},
       "tags":["origem:teste"],"atribuicao":{"situacao":"sem_origem"}}' -w "\nHTTP %{http_code}\n"
```

Esperado: `HTTP 201` e o card "Teste Runbook" na Entrada, com a tag `origem:teste` e o fato
"Deixou o contato no site" no histórico. Repetir o mesmo comando: `HTTP 200` com
`"resultado":"ja_processado"` e nada novo no card. Apague o card de teste depois.

## 5. Diagnóstico

| Sintoma | Causa provável |
|---|---|
| `401` | Token errado, revogado, de outro escopo, ou cabeçalho sem `Bearer `. `listar-tokens` mostra situação e último uso. |
| `413` | Corpo acima de 64 KB. Erro permanente: o site não deve reenviar. |
| `422` | Corpo fora do contrato (o `detail` diz o campo). Erro permanente: a fila do site não deve reenviar. Inclui o teto anti-abuso: **mais de 100 tags** na lista, ou **uma tag com mais de 200 caracteres**. O site trunca antes de enviar; é bug do site, não do e1p. (Dentro do teto, o excedente do limite do CRM — 50 tags × 40 caracteres — não dá erro: fica registrado em `tags_descartadas`.) |
| `200` inesperado | A `chave_idempotencia` já foi processada — o site está reutilizando chave. |
| `500` | Falha inesperada; o site reenvia. Ver `$DC logs api` (logger `e1p.lead_ingest`). |
| Lead chegou e não entrou no funil | Funil apagado ou vazio: procure `[lead_ingest] inscrição falhou` no log. |
| Compra registrada, card não foi para Ganho | O tenant não tem coluna de Ganho ativa: procure `sem coluna de Ganho ativa` no log. |

### Registro preso (chave reivindicada que não concluiu)

Um processo que cai entre o commit do contato e o das tags/fato deixa `concluido_em` nulo. A
próxima tentativa do site retoma sozinha, então um registro preso por pouco tempo é normal. Mais de
15 minutos indica que o site parou de reenviar (ou que a retentativa também falha). Somente
leitura, tenant explícito:

```bash
$DC exec postgres psql -U e1p_root -d e1pdb -c   "SELECT id, chave_idempotencia, evento, client_id, created_at
     FROM lead_ingest_records
    WHERE tenant_id = '<tenant_id do §1>'
      AND concluido_em IS NULL
      AND created_at < now() - interval '15 minutes'
    ORDER BY created_at;"
```

O que fazer: peça ao site para **reenviar o mesmo evento com a mesma `chave_idempotencia`** (a
retomada conclui sem duplicar contato nem fato). Reenviado e ainda preso: veja `$DC logs api`
(logger `e1p.lead_ingest`) pelo erro da retentativa. Não edite nem apague a linha à mão.

## 6. Trocar ou revogar a credencial

```bash
$DC exec api python -m app.scripts.lead_ingest_admin listar-tokens --tenant <slug>
$DC exec api python -m app.scripts.lead_ingest_admin emitir-token --tenant <slug> --nome "site (rotação)"
# ...troque no cofre do site, confirme um 201...
$DC exec api python -m app.scripts.lead_ingest_admin revogar-token --id <id da antiga>
```

Revogada, a credencial responde 401 na hora. Excluir a conta do tenant apaga as credenciais dele.
