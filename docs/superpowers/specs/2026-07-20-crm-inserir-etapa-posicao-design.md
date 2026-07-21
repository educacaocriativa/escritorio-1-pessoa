# Inserir etapa do Funil (CRM) em qualquer posição

**Data:** 2026-07-20
**Status:** Aprovado (brainstorming), aguardando plano de implementação

## 1. Problema

Hoje, no Kanban do CRM (`/crm` → "Funil de clientes"), o botão **"+ Nova etapa"** só permite
criar uma coluna nova **no final** da sequência (Entrada → Em contato → Proposta → Ganho → Perda
→ nova). Não existe jeito de inserir uma etapa **no meio** do funil (ex.: entre "Em contato" e
"Proposta") sem editar manualmente cada etapa depois.

## 2. Escopo (decidido no brainstorming)

- **Somente inserção em posição arbitrária ao criar uma nova etapa.** Etapas já existentes
  continuam na ordem em que estão — **não** há reordenação de etapas existentes (ex.: arrastar
  colunas) nesta entrega.
- UI: o atual `window.prompt` de "Nova etapa" vira um **modal** com campo de nome + um select
  **"Inserir depois de"** listando as etapas atuais na ordem, com a **última etapa pré-selecionada
  por padrão** (preserva o comportamento atual — quem só confirma sem mexer no select, cria no
  fim, como hoje).
- Etapas arquivadas (`is_archived`) não entram no select nem são afetadas pela renumeração.

### Fora de escopo (decisão explícita)

- Arrastar/reordenar colunas já existentes.
- Editar `is_won`/`is_lost` de uma etapa (dívida já registrada no `CLAUDE.md`).

## 3. Arquitetura

Nenhuma mudança de schema é necessária. `pipeline_stages.position` (`INTEGER`, sem constraint de
unicidade) já existe, e a ordenação já é `ORDER BY position, id`
(`apps/api/app/modules/crm/service.py`, `_ordered_stages()`).

**Estratégia:** ao criar uma etapa em qualquer posição, **renumerar sequencialmente** (0, 1, 2,
…) todas as etapas ativas (não arquivadas) do tenant, em vez de fazer aritmética de gaps. Mais
simples, sem risco de colisão e sem depender de constraint de unicidade que não existe hoje.

### Backend (`apps/api/app/modules/crm/`)

- **`schemas.py`** — `StageCreate` ganha `after_stage_id: str | None = None` (o campo `position`
  existente permanece no schema, sem uso por este fluxo).
- **`service.py`, `create_stage()`**:
  1. Buscar etapas ativas ordenadas do tenant (`_ordered_stages()` já existe, filtrando
     `is_archived=False`).
  2. Validar `after_stage_id`, se enviado: deve existir entre as etapas ativas do tenant (a
     query já é filtrada por RLS); senão `422`. Referenciar uma etapa arquivada também cai
     nesse `422`, pois `_ordered_stages()` já as exclui da lista de ativas.
  3. Calcular índice de inserção: `after_stage_id` **ausente/`None`** → **acrescenta ao final**
     (idêntico ao comportamento atual — preserva compatibilidade para qualquer chamador que não
     use o campo novo); caso contrário, índice = posição da etapa referenciada na lista ordenada
     `+ 1`. **Não há suporte a inserir antes da primeira etapa** nesta entrega — não é alcançável
     pela UI (o select sempre lista etapas reais) e evita ambiguidade entre "campo omitido" e
     "inserir no início" (que o JSON não distingue).
  4. Numa única transação: montar a lista final de objetos (etapas existentes + a nova, no
     índice calculado) e escrever `position = 0..N-1` para cada um, na ordem.
  5. Etapas arquivadas mantêm seu `position` atual (não entram na renumeração, não aparecem no
     board mesmo assim, e não são um `after_stage_id` válido).
- **`router.py`** — `POST /crm/stages` já recebe o body completo; só passa o novo campo adiante,
  sem mudança de assinatura de rota.

### Frontend (`apps/web/src/features/crm/CrmPage.tsx`)

- Substituir o `window.prompt` de `createStage()` (linhas 42-52) por um modal novo
  (`NewStageModal` ou estado local de modal na própria página, seguindo o padrão de outros
  modais já existentes no CRM, se houver):
  - Campo texto: nome da etapa (obrigatório, não-vazio).
  - Select "Inserir depois de": opções = etapas ativas atuais, na ordem do board; **default =
    última etapa** da lista.
  - Botões Cancelar / Criar.
- Ao confirmar: `POST /crm/stages { name, after_stage_id }`.
- Após sucesso: **recarregar `/crm/board`** (não tentar reordenar otimisticamente no client — como
  todas as posições podem mudar, é mais simples e seguro buscar o estado real do servidor).

## 4. Testes

Estender `apps/api/tests/test_crm.py`:
- Criar etapa sem `after_stage_id` → continua indo para o final (comportamento atual
  preservado).
- Inserir etapa no meio (`after_stage_id` de uma etapa intermediária) → ordem final correta.
- Inserir etapa depois da última etapa (`after_stage_id` da última) → equivalente a acrescentar
  ao final.
- `after_stage_id` de uma etapa arquivada → `422`.
- `after_stage_id` desconhecido/inexistente → `422`.

(Teste de isolamento cross-tenant fica de fora da suíte unitária: os testes de `test_crm.py`
rodam sobre SQLite, que não aplica RLS — a mesma lacuna já documentada no `CLAUDE.md` §6.1 para
todo o módulo. `after_stage_id` de outro tenant já cai automaticamente no caso "não encontrado"
em produção, porque `_ordered_stages()` só enxerga o tenant da sessão via RLS.)
