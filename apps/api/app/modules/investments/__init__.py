"""Conta de investimento — rendimento e rentabilidade (Epic 5 — Inteligência Financeira, Story 5.6).

Registra aplicações (principal aplicado, rendimento acumulado, tipo de aplicação, indexador/taxa)
e lança o RENDIMENTO como receita financeira no grupo `FINANCEIRO` do plano de contas (5.1) —
entrando na DRE (5.3) em regime de competência — SEM acionar o split de vendas da Carteira.

Decisão técnica central (Task 3): o rendimento vira uma `Charge` (Contas a Receber) construída
DIRETAMENTE já baixada (`status=paid`), NUNCA passando por `mark_paid`/`build_transaction` — logo
não cria `Transaction`/`PlatformEarning` nem cobra split de plataforma (IV1). Ver `service.py`.
"""
