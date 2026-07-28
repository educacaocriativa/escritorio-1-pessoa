# Checklist manual — comprovante pelo celular

Rodar uma vez antes de considerar a entrega concluída. Nada aqui é automatizável: share sheets
de sistema operacional e RLS do Postgres não são exercitáveis por vitest/pytest.

## 1. Isolamento cross-tenant (Postgres real)

Este passo é manual **só porque o módulo `receipts` ainda não tem seu teste automatizado de RLS**
— não porque seja impossível de automatizar. O repositório já tem o padrão pronto: testes
marcados `pytest.mark.rls_e2e` (testcontainers, Postgres real), excluídos do `pytest -q` normal e
rodados pelo job dedicado `cross-tenant-rls` no CI (`.github/workflows/ci.yml`). Vários módulos já
têm o companheiro `_rls.py` (ex.: `apps/api/tests/test_chart_of_accounts_rls.py`,
`test_cost_centers_rls.py`, `test_financial_intelligence_diagnostics_rls.py`) — falta escrever
`test_receipts_rls.py` seguindo o mesmo modelo. Até isso ser feito, rode manualmente:

- [ ] Subir a stack: `docker compose --env-file .env -f infra/docker-compose.yml up -d --build`
- [ ] Criar dois tenants (A e B) via `/auth/register`.
- [ ] Em A, criar uma conta a pagar e anotar o `bill_id`.
- [ ] Em B, subir um comprovante (`POST /payables/receipts`) e anotar o `receipt_id`.
- [ ] Com o token de B, chamar `POST /payables/receipts/{receipt_id}/link` com o `bill_id` de A.
- [ ] **Esperado:** `404` — a RLS esconde a conta de A da sessão de B. Se vier `200`, a RLS não
      está ativa (checar se a app conecta como `e1p_app`, não superusuário).

## 2. Android — share sheet

- [ ] Abrir `https://<domínio>` no Chrome do Android.
- [ ] Menu → **Instalar app**. Confirmar que o ícone aparece na tela inicial.
- [ ] Abrir o app do banco, fazer/abrir um pagamento, tocar em **Compartilhar**.
- [ ] **Esperado:** "e1p" aparece na lista de destinos.
- [ ] Tocar em e1p → abre a tela de escolha da conta com o arquivo já enviado.
- [ ] Escolher uma conta em aberto, manter "marcar como paga", tocar em **Anexar**.
- [ ] **Esperado:** volta para Contas a pagar, a conta está "Pago" e tem o anexo `comprovante`.
- [ ] Repetir deslogado: deve cair no login e retomar sozinho depois de entrar.

## 3. Android — o service worker não serve versão velha

- [ ] Fazer um deploy novo com uma mudança visível.
- [ ] Abrir o PWA já instalado no aparelho, sem limpar dados.
- [ ] **Esperado:** a mudança aparece na primeira abertura. Se não aparecer, conferir o
      `Cache-Control` de `/sw.js` no nginx (deve ser `no-cache`).

## 4. iPhone — Atalho

- [ ] Em Configurações → Celular, gerar um token e copiar.
- [ ] Montar o atalho no app Atalhos seguindo os 4 passos da tela.
- [ ] Testar com um arquivo qualquer pela folha de compartilhamento.
- [ ] **Esperado:** o Safari abre em `/comprovante/<id>` com o arquivo já na bandeja.
- [ ] Publicar o atalho como link do iCloud (**manual, uma vez só** — não dá para gerar por
      código) e guardar o link para distribuir a quem for usar.
- [ ] Revogar o token em Configurações e repetir: **esperado** `401`.

## 5. Limites

- [ ] Compartilhar um arquivo acima de 10 MB → mensagem de erro clara, não tela branca.
- [ ] Compartilhar um tipo não suportado (ex.: `.docx`) → recusado com mensagem.
- [ ] Encher a bandeja com 30 itens e tentar o 31º → mensagem pedindo para vincular/descartar.
