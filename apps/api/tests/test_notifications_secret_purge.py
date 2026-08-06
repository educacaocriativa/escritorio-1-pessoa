"""A senha temporária não fica para sempre em texto puro na fila.

Achado ao investigar o incidente de 2026-08-05: `notifications.message` guarda o corpo do
convite INTEIRO, incluindo a linha `Senha temporária: ...`, sem expiração — e
`whatsapp_template_variables` guarda a mesma senha como último elemento. Foi o que permitiu
recuperar a senha de um funcionário quando a entrega falhou, e é exatamente por isso que
incomoda: o hash bcrypt em `users` protege muito bem uma senha que está em claro na mesa ao
lado.

Regra (decisão do fundador): entregue → expurga já; terminal sem entrega → expurga depois da
carência (a senha ainda pode ser útil ao Master nesse intervalo); `pending` → nunca (o worker
ainda precisa do corpo para enviar).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.notifications import service
from app.modules.notifications.models import Notification
from app.modules.whatsapp_templates.models import PURPOSE_STAFF_INVITE

TENANT_ID = "44444444-4444-4444-4444-444444444444"
AGORA = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
SENHA = "lJQ2ooc8HPpj"
CORPO = f"Olá! Login: a@b.com\nSenha temporária: {SENHA}\n"


def _convite(db, *, status: str, criada_em: datetime, purpose: str = PURPOSE_STAFF_INVITE):
    n = Notification(
        tenant_id=TENANT_ID, channel="whatsapp", recipient="5511999999999",
        message=CORPO, status=status, purpose=purpose,
        whatsapp_template_variables=["Fulano", "Empresa", "a@b.com", SENHA],
    )
    db.add(n)
    db.flush()
    # `created_at` tem server_default; sobrescrevemos para posicionar a notificação no tempo.
    n.created_at = criada_em
    db.commit()
    return n


def test_convite_entregue_perde_a_senha_do_registro(db) -> None:
    n = _convite(db, status="sent", criada_em=AGORA)

    assert service.purge_invite_secrets(db, tenant_id=TENANT_ID, now=AGORA) == 1

    db.refresh(n)
    assert SENHA not in n.message
    assert n.whatsapp_template_variables is None
    # O metadado permanece: o rastro de QUE houve um convite não pode sumir junto com o segredo.
    assert n.status == "sent" and n.purpose == PURPOSE_STAFF_INVITE
    assert n.recipient == "5511999999999"


def test_convite_pendente_mantem_o_corpo(db) -> None:
    """O worker ainda vai enviar essa mensagem — expurgar aqui entregaria um texto sem senha."""
    n = _convite(db, status="pending", criada_em=AGORA)

    assert service.purge_invite_secrets(db, tenant_id=TENANT_ID, now=AGORA) == 0

    db.refresh(n)
    assert SENHA in n.message


def test_convite_nao_entregue_sobrevive_a_carencia(db) -> None:
    """`logged`/`failed` é o caso em que o Master pode precisar da senha — expurgar no ato
    destruiria a única cópia recuperável dentro da janela em que ela ainda serve."""
    n = _convite(db, status="logged", criada_em=AGORA - timedelta(days=3))

    assert service.purge_invite_secrets(db, tenant_id=TENANT_ID, now=AGORA) == 0

    db.refresh(n)
    assert SENHA in n.message


def test_convite_nao_entregue_e_velho_e_expurgado(db) -> None:
    n = _convite(db, status="logged", criada_em=AGORA - timedelta(days=8))

    assert service.purge_invite_secrets(db, tenant_id=TENANT_ID, now=AGORA) == 1

    db.refresh(n)
    assert SENHA not in n.message


def test_nao_toca_em_notificacao_de_outro_proposito(db) -> None:
    """Só o convite carrega senha. Cobrança/contrato têm corpo que o dono pode querer reler."""
    n = _convite(db, status="sent", criada_em=AGORA, purpose="charge_reminder")

    assert service.purge_invite_secrets(db, tenant_id=TENANT_ID, now=AGORA) == 0

    db.refresh(n)
    assert n.message == CORPO


def test_e_idempotente(db) -> None:
    """Roda a cada sweep: a segunda passada não pode recontar o que já limpou."""
    _convite(db, status="sent", criada_em=AGORA)

    assert service.purge_invite_secrets(db, tenant_id=TENANT_ID, now=AGORA) == 1
    assert service.purge_invite_secrets(db, tenant_id=TENANT_ID, now=AGORA) == 0
