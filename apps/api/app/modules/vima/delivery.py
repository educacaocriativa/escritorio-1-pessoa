"""*"Este usuário consegue receber o briefing por WhatsApp — e por qual caminho?"*

Uma pergunta, uma resposta, dois consumidores:

- `app/modules/auth/router.py::get_preferences` / `update_preferences` — a tela mostra o motivo
  e o PATCH recusa ligar o que não entrega.
- `app/modules/vima/scheduler.py::_entregar_no_whatsapp` — escolhe entre o texto inteiro
  (Evolution) e o aviso com botão (Meta).

Os dois precisam da MESMA resposta. Se divergissem, a tela diria "ligado" e o job não mandaria
nada — a pior forma de falha possível num canal diário, porque é silenciosa dos dois lados.

⚠️ A indisponibilidade da Meta é uma dependência **externa ao repositório**: o template com botão
de resposta rápida precisa passar pela aprovação da Meta, que leva dias e não depende de deploy.
Enquanto não passa, o tenant Meta fica sem briefing por WhatsApp — e a tela **diz por quê**.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.whatsapp import capabilities
from app.modules.settings.models import TenantProfile
from app.modules.whatsapp_templates.models import (
    PURPOSE_VIMA_BRIEFING,
    STATUS_APPROVED,
    WhatsappTemplate,
)

SEM_TELEFONE = "Cadastre um WhatsApp no seu perfil para receber o briefing por lá."
TEMPLATE_PENDENTE = (
    "O template do briefing ainda não foi aprovado pela Meta. Enquanto isso, o briefing "
    "continua na tela todo dia — só o envio por WhatsApp é que não sai."
)


@dataclass(frozen=True)
class Entrega:
    """O veredito. `template_id` só é preenchido quando o caminho passa por template."""

    disponivel: bool
    motivo: str | None
    template_id: str | None = None


def avaliar(db: Session, *, phone: str | None) -> Entrega:
    """Sessão RLS-escopada (o perfil e os templates são do tenant corrente, Regra de Ouro nº 1).

    Ordem das guardas: telefone primeiro, porque sem destinatário nem faz sentido perguntar por
    qual transporte — e porque é o motivo que o usuário resolve sozinho, em um campo.
    """
    if not phone or not phone.strip():
        return Entrega(disponivel=False, motivo=SEM_TELEFONE)

    # `select(TenantProfile)` sem `where`, igual a `settings.get_profile`: a sessão já é
    # RLS-escopada e o perfil que vem é o do tenant corrente. Não CRIA perfil — isto é leitura
    # dentro de uma regra de negócio, e um efeito colateral de escrita aqui seria armadilha.
    profile = db.scalar(select(TenantProfile))
    if not capabilities.for_profile(profile).templates:
        # Evolution: sem template e sem janela de 24h — o briefing inteiro sai em um passo.
        return Entrega(disponivel=True, motivo=None)

    template = _template_do_aviso(db, profile)
    if template is None:
        return Entrega(disponivel=False, motivo=TEMPLATE_PENDENTE)
    return Entrega(disponivel=True, motivo=None, template_id=template.id)


def _template_do_aviso(db: Session, profile) -> WhatsappTemplate | None:
    """O template vinculado ao aviso do briefing, se existir E continuar aprovado.

    A aprovação é reconferida na LEITURA, e não só no vínculo: a Meta despausa e repausa
    template por conta própria (`PAUSED`/`DISABLED`), e um vínculo criado quando estava
    `APPROVED` continuaria no banco apontando para um template que já não entrega.
    """
    binding = (getattr(profile, "whatsapp_template_bindings", None) or {}).get(
        PURPOSE_VIMA_BRIEFING
    )
    if not binding:
        return None
    template = db.get(WhatsappTemplate, binding)
    if template is None or template.status != STATUS_APPROVED:
        return None
    return template
