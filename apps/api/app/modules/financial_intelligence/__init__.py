"""Camada analítica read-only do Epic 5 (Inteligência Financeira).

Módulo criado pela Story 5.3 (DRE por categoria). As Stories 5.7 (projeção) e 5.8 (motor de
diagnóstico/narrador) ESTENDEM este mesmo módulo (`projection.py`, `engine.py`/`ai_narrator.py`)
em vez de criar módulos próprios — todas compartilham o padrão SOMENTE-LEITURA e as mesmas fontes
(Payable/Charge classificados + plano de contas). Nada aqui escreve no banco.
"""
