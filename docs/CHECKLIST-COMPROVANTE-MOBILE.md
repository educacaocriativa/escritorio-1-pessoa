# Checklist manual — comprovante pelo celular

Rodar uma vez antes de considerar a entrega concluída. Os share sheets do Android e do iOS
(§2 e §4) exigem aparelho real e não são exercitáveis por automação — esses continuam manuais.
O isolamento cross-tenant (§1) **já está automatizado** e não faz mais parte deste checklist.

## 1. Isolamento cross-tenant (Postgres real) — AUTOMATIZADO

Não é mais um passo manual: `apps/api/tests/test_receipts_rls.py` (`pytest.mark.rls_e2e`,
testcontainers, Postgres real) cobre exatamente o cenário abaixo — token/sessão do tenant B não
vincula uma conta do tenant A, `get_staged` não resolve anexo em staging de outro tenant, e
`list_candidates` só devolve contas do tenant da sessão corrente. Roda `alembic upgrade head`
como o papel não-superusuário `e1p_app` contra um Postgres real, exercitando de fato a migration
0057. Excluído do `pytest -q` normal; rodado pelo job dedicado `cross-tenant-rls` no CI
(`.github/workflows/ci.yml`) ou manualmente com:

```bash
cd apps/api && pytest -m rls_e2e -k receipts
```

⚠️ **Com a máquina só para você.** Se houver outra suíte pesada rodando (`pytest -q`, `pnpm e2e`,
mutação), a contaminação devolve `AssertionError` indistinguível de regressão real e o resultado
não conta como sinal — ver `CLAUDE.md` §5.5. Para rodar tudo em série de uma vez:
`bash scripts/gates.sh`.

Se precisar validar à mão de qualquer forma (ex.: investigando uma regressão), o roteiro
equivalente por HTTP é: dois tenants via `/auth/register`, conta a pagar em A, comprovante em B,
`POST /payables/receipts/{id}/link` com token de B e `bill_id` de A → esperado `404`.

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
