"""Regras da integração Google (OAuth + Calendar API), via httpx puro.

Sem SDK oficial (google-api-python-client): replicamos o estilo de core/whatsapp.py — httpx
direto, "sem credencial = no-op/log, com credencial = chamada real" — consistente com o padrão
do projeto e com "Custo importa" (CLAUDE.md §3.4).

Princípio de robustez (mesmo de core/whatsapp.py, exigido por IV1/IV2): uma falha na chamada ao
Google (rede, token revogado, quota) NUNCA derruba a operação de negócio da Agenda — captura,
loga (sem vazar o token) e retorna None. O evento é criado normalmente, apenas sem Meet.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core import audit
from app.core.security import sign_oauth_state
from app.db.session import tenant_session
from app.modules.agenda.models import AgendaEvent
from app.modules.google_calendar.models import DEFAULT_SCOPE, GoogleCredential

logger = logging.getLogger("e1p.google_calendar")

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (endpoint público, não é segredo)
_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"  # noqa: S105 (endpoint público)
_CALENDAR_EVENTS_URL = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events?conferenceDataVersion=1"
)
# Evento específico (reschedule/cancel) — {event_id} é o google_event_id guardado no AgendaEvent.
_CALENDAR_EVENT_URL = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}"
)
_HTTP_TIMEOUT = 10

# Tipos de evento onde "reunião" faz sentido (geram Meet). Bloqueios/prazos/cobranças não.
MEET_KINDS = {"reuniao", "atendimento", "audiencia"}
# Tipos de evento espelhados no Google (create/reschedule/cancel), com ou sem Meet. Bloqueio
# ocupa horário de verdade na agenda do dono e por isso é espelhado — mas não é reunião, então
# não pede conferenceData (ver create_meet_event abaixo).
PUSHED_KINDS = MEET_KINDS | {"bloqueio"}


class GoogleNotConfiguredError(Exception):
    """O app OAuth do Google não está configurado na plataforma (config global vazia)."""


# ── Fluxo OAuth ──────────────────────────────────────────────────────────────
def build_authorize_url(tenant_id: str) -> str:
    """Monta a URL de autorização do Google. `access_type=offline` + `prompt=consent` garantem
    o refresh_token na primeira autorização; `state` assinado protege contra CSRF."""
    if not settings.google_oauth_configured:
        raise GoogleNotConfiguredError("Integração Google não configurada")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": DEFAULT_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": sign_oauth_state(tenant_id),
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Troca o `code` do callback por tokens (access + refresh)."""
    resp = httpx.post(
        _TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_account_email(access_token: str) -> str:
    """Busca o e-mail da conta Google conectada (para exibir 'conectado como ...')."""
    resp = httpx.get(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("email", "")


def _expiry_from(token_data: dict) -> datetime | None:
    expires_in = token_data.get("expires_in")
    if not expires_in:
        return None
    try:
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None


def get_credential(db: Session) -> GoogleCredential | None:
    """A credencial do tenant atual (RLS já isola a sessão). None se não conectado."""
    return db.scalars(select(GoogleCredential)).first()


def _invalidar_vinculos_de_outra_conta(db: Session, *, novo_email: str) -> int:
    """Zera os vínculos com o Google dos eventos que vieram de OUTRA conta. Retorna quantos.

    POR QUE NA RECONEXÃO, e não ao desconectar: enquanto o tenant está sem credencial, os três
    consumidores de `google_event_id` (`patch_meet_event`, `delete_meet_event` e o
    `pull_changes` do worker) já retornam cedo em `get_credential(db) is None` — nenhum id velho
    chega ao Google. A janela de dano abre só quando uma credencial volta. Limpar no
    `disconnect` seria cedo demais: ainda não se sabe qual conta vai voltar, e destruiria o
    vínculo no caso DOMINANTE, que é reconectar com a MESMA conta.

    Roda na sessão do chamador de propósito (ao contrário de `_descartar_credencial_revogada`,
    que precisa de sessão própria): `upsert_credential` É a dona da transação e commita logo em
    seguida — a limpeza e a nova credencial entram juntas ou não entram.

    Cada cláusula do WHERE é deliberada:

    - `google_event_id IS NOT NULL` — PROTEGE O `meeting_url` DIGITADO À MÃO. Quem colou um link
      de Zoom nunca teve `google_event_id` (`agenda/service.py::create_event` só chama o Google
      quando `not data.meeting_url`). Sem esta cláusula, apagaríamos links que o usuário digitou.

    - `google_account_email IS NOT NULL` — LINHA LEGADA FICA INTACTA. `NULL` é procedência
      desconhecida (gravada antes da migration 0086, que não fez backfill). Apagar às cegas
      reintroduziria a duplicação de eventos no próximo sync para os dados que já existem. Elas
      se autocuram no ramo de update de `sync.py::_apply_item`.
      ⚠️ Esta cláusula é REDUNDANTE **hoje**, e isso foi MEDIDO (prova por mutação da #302:
      removê-la sozinha não muda nenhum comportamento observável): pela lógica de três valores
      do SQL, `NULL != 'alguem@gmail.com'` já avalia a NULL, não a TRUE, e a linha legada
      escapa do `WHERE` sozinha. Ela fica porque a proteção não pode depender de um efeito
      colateral de NULL que ninguém lê: trocar o `!=` por qualquer coisa NULL-tolerante
      (`IS DISTINCT FROM`, `coalesce(..., '') !=`) apagaria TODA a base legada em silêncio — e
      a mutação que faz exatamente isso mata o teste da linha legada.

    - `!= novo_email` — RECONECTAR COM A MESMA CONTA É NO-OP. É a razão de existir de todo este
      desenho: o caso comum (token expirou, dono reconecta a mesma conta) não pode perder nada.

    `novo_email` vazio ("" quando o `userinfo` falhou no callback) também é no-op: sem saber
    QUEM está conectando não dá para afirmar que a conta mudou, e na dúvida não se destrói.

    TRADE-OFF ASSUMIDO: `meeting_url` vai junto. Um link de Meet da conta antiga PODE continuar
    funcionando, e apagá-lo é irreversível. É o que a issue #302 pede explicitamente — um link
    que abre o Meet de outra pessoa é pior que um card sem link.

    UPDATE em MASSA (uma query), não laço Python: a RLS já isola a sessão no tenant (Regra de
    Ouro nº 1) e o `WHERE` não precisa — nem pode — repetir o filtro de tenant.
    """
    if not novo_email:
        return 0
    resultado = db.execute(
        update(AgendaEvent)
        .where(
            AgendaEvent.google_event_id.is_not(None),
            AgendaEvent.google_account_email.is_not(None),
            AgendaEvent.google_account_email != novo_email,
        )
        .values(google_event_id=None, meeting_url=None, google_account_email=None)
        .execution_options(synchronize_session=False)
    )
    return resultado.rowcount or 0


def upsert_credential(db: Session, *, tenant_id: str, email: str, token_data: dict) -> None:
    """Cria/atualiza a credencial do tenant (uma por tenant). Preserva o refresh_token antigo
    se o Google não devolver um novo (ele só vem na 1ª autorização com prompt=consent)."""
    cred = get_credential(db)
    if cred is None:
        cred = GoogleCredential(tenant_id=tenant_id)
        db.add(cred)
    cred.google_account_email = email
    cred.access_token = token_data.get("access_token", "")
    new_refresh = token_data.get("refresh_token")
    if new_refresh:
        cred.refresh_token = new_refresh
    cred.token_expiry = _expiry_from(token_data)
    cred.scope = token_data.get("scope", DEFAULT_SCOPE)
    # ANTES do commit abaixo (mesma transação): se a conta que está conectando não é a que
    # gerou os `google_event_id` guardados, esses ids apontam para o calendário de OUTRA pessoa.
    invalidados = _invalidar_vinculos_de_outra_conta(db, novo_email=email)
    if invalidados:
        logger.warning(
            "[google:reconexao:conta_trocada] tenant=%s eventos_invalidados=%d",
            tenant_id, invalidados,
        )
    # `detail=email`: QUAL conta entrou. Sem isso, nem reconstruindo a sequência de entradas dá
    # para saber de qual conta para qual a reconexão trocou — o `connect` é a única ponta que
    # sabe o e-mail novo, e o `target` (id da credencial) é o MESMO em toda troca do tenant.
    # `email` vazio (userinfo falhou no callback, ver `handle_callback`) grava "" e é honesto:
    # a conexão de fato aconteceu sem que soubéssemos quem é.
    audit.record(
        db, tenant_id=tenant_id, actor="google:oauth", action="google.credential.connect",
        target=cred.id, detail=email,
    )
    db.commit()


def handle_callback(db: Session, *, tenant_id: str, code: str) -> None:
    """Fluxo completo do callback: troca o code por tokens, descobre o e-mail e faz upsert.

    Buscar o e-mail é só para exibição ("conectado como ...") — uma falha aí (rede, escopo
    insuficiente) NUNCA deve descartar tokens já obtidos com sucesso (mesmo princípio de
    robustez do módulo, ver docstring do topo do arquivo)."""
    token_data = exchange_code(code)
    access_token = token_data.get("access_token", "")
    email = ""
    if access_token:
        try:
            email = fetch_account_email(access_token)
        except httpx.HTTPError:
            logger.exception("[google:userinfo:failed] tenant=%s", tenant_id)
    upsert_credential(db, tenant_id=tenant_id, email=email, token_data=token_data)


def disconnect(db: Session, *, tenant_id: str, actor: str) -> bool:
    """Apaga a credencial do tenant. Best-effort: tenta revogar no Google, mas SEMPRE apaga
    localmente mesmo se a revogação falhar (a intenção do usuário é desconectar)."""
    cred = get_credential(db)
    if cred is None:
        return False
    token_to_revoke = cred.refresh_token or cred.access_token
    if token_to_revoke:
        try:
            httpx.post(
                _REVOKE_URL, data={"token": token_to_revoke}, timeout=_HTTP_TIMEOUT
            )
        except Exception:
            logger.exception("[google:revoke:failed] tenant=%s", tenant_id)
    # Lidos ANTES do `delete`: depois dele `cred` está marcado para remoção e ler atributo de
    # instância deletada depende de a sessão ainda não ter expirado o objeto. O `target=cred.id`
    # que ficava DEPOIS do delete só funcionava por acidente de timing; agora nenhum dos dois
    # valores depende disso. (Mesma disciplina de `_descartar_credencial_revogada`, que já lê
    # `tenant_id`/`cred_id` antes de mexer na credencial.)
    cred_id = cred.id
    email_da_conta = cred.google_account_email
    db.delete(cred)
    # `detail`: QUAL conta saiu. A linha morre nesta mesma transação, então o e-mail não é
    # recuperável por join depois — é exatamente o caso que a coluna `detail` existe para cobrir.
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="google.credential.disconnect",
        target=cred_id, detail=email_da_conta,
    )
    db.commit()
    return True


def _descartar_credencial_revogada(cred: GoogleCredential) -> None:
    """Apaga a credencial morta numa sessão CURTA e INDEPENDENTE — nunca na sessão do chamador.

    POR QUÊ a sessão própria: `_ensure_fresh_token` é chamado de dentro de quatro fluxos
    (`create_meet_event`, `patch_meet_event`, `delete_meet_event` e o `pull_changes` do worker) e
    em NENHUM deles ele é dono da transação — há um AgendaEvent recém-alterado e ainda sem commit
    na sessão. Um `db.commit()` aqui persistiria TUDO o que estivesse pendente, no meio de uma
    operação que ainda podia falhar. Esta sessão curta commita só o DELETE + a auditoria e fecha
    (mesmo padrão de `funnels/automation.py` e `notifications/service.py::on_client_moved`).

    POR QUÊ apagar: `/integrations/google/status` deduz "conectado" da existência da linha. Com o
    refresh_token morto a linha sobrevivia e a tela mentia ("conectado como ...") enquanto nenhum
    Meet era criado. Sem a linha, o status volta a `connected: false` sozinho e reconectar segue
    funcionando pelo caminho normal (`upsert_credential` recria a linha) — sem coluna nova, sem
    migration, sem mexer no router.

    BEST-EFFORT (princípio de robustez do módulo, IV1/IV2): se a sessão curta falhar (banco fora,
    RLS, o que for), loga e segue. Nenhuma exceção nova sai de `_ensure_fresh_token` — a Agenda
    nunca cai por causa da integração Google.
    """
    # Lidos ANTES de abrir a outra sessão: `cred` pertence à sessão do chamador e não pode ser
    # usado dentro dela (nem depois do delete, que o expiraria lá).
    tenant_id = cred.tenant_id
    cred_id = cred.id
    email_da_conta = cred.google_account_email
    try:
        with tenant_session(tenant_id) as descarte:
            morta = descarte.get(GoogleCredential, cred_id)
            if morta is None:
                return  # o usuário (ou outro fluxo) já desconectou — nada a fazer
            descarte.delete(morta)
            # Ação PRÓPRIA, deliberadamente distinta de `google.credential.disconnect`: quem
            # apagou foi o sistema ao ver o token morto, não o usuário pedindo para desconectar.
            # Confundir as duas no audit apagaria a diferença entre "revogado pelo Google" e
            # "o dono clicou em Desconectar".
            # `detail`: QUAL conta o Google revogou. Vem do `email_da_conta` lido lá em cima, na
            # sessão do CHAMADOR — `morta` é outra instância, e ler dela também serviria, mas o
            # snapshot já está na mão e não depende do estado da sessão curta.
            audit.record(
                descarte, tenant_id=tenant_id, actor="google:token",
                action="google.credential.revoked", target=cred_id, detail=email_da_conta,
            )
    except Exception:
        logger.exception("[google:token:descarte_falhou] tenant=%s", tenant_id)


# ── Geração de Meet ao criar evento ──────────────────────────────────────────
def _ensure_fresh_token(db: Session, cred: GoogleCredential) -> str | None:
    """Retorna um access_token válido, renovando via refresh_token se já expirou. None se não
    dá para renovar (sem refresh_token)."""
    expiry = cred.token_expiry
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry is None or expiry > datetime.now(UTC):
        return cred.access_token or None
    if not cred.refresh_token:
        return None
    resp = httpx.post(
        _TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": cred.refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        },
        timeout=_HTTP_TIMEOUT,
    )
    if resp.status_code == 400 and "invalid_grant" in resp.text:
        # Refresh token revogado ou expirado. É TERMINAL: repetir não adianta, só reconectar.
        # NÃO é rotina. O app OAuth está publicado ("Em produção" desde 2026-09-05), então o
        # antigo ciclo de 7 dias do modo "Testing" ACABOU — não use mais essa explicação para
        # encerrar uma investigação. Cair aqui hoje significa revogação de verdade: o dono
        # removeu o acesso do e1p na conta Google, trocou a senha, ou passou ~6 meses sem usar a
        # integração. É raro e merece ser investigado (ver docs/GO-LIVE-CHECKLIST.md §5,
        # "Autocura da conexão morta").
        logger.warning(
            "[google:token:revogado] tenant=%s — refresh_token morto, precisa reconectar",
            cred.tenant_id,
        )
        # A credencial morta é descartada aqui (em sessão própria, ver a função abaixo): sem a
        # linha, `/integrations/google/status` volta a responder `connected: false` e a UI
        # oferece "Conectar Google", em vez de exibir "conectado como ..." com a integração
        # parada. O log acima deixa de ser o único sinal da falha.
        _descartar_credencial_revogada(cred)
        return None
    resp.raise_for_status()
    token_data = resp.json()
    cred.access_token = token_data.get("access_token", "")
    cred.token_expiry = _expiry_from(token_data)
    db.add(cred)
    return cred.access_token or None


def create_meet_event(
    db: Session, *, tenant_id: str, event
) -> tuple[str | None, str | None, str | None] | None:
    """Cria o evento espelho no Google Calendar (com link de Meet) para um AgendaEvent.

    Retorna (hangout_link, google_event_id, google_account_email) em caso de sucesso, ou None se:
    - o tenant não tem Google conectado (no-op — preserva AC3/IV1); ou
    - a chamada ao Google falhou (rede/token/quota) — a exceção é capturada e logada, NUNCA
      propagada, para não derrubar a criação do evento da Agenda (IV1/IV2).
    """
    cred = get_credential(db)
    if cred is None:
        return None
    try:
        access_token = _ensure_fresh_token(db, cred)
        if not access_token:
            return None
        body = {
            "summary": event.title,
            "description": event.description or "",
            "start": {"dateTime": _iso(event.starts_at)},
            "end": {"dateTime": _iso(event.ends_at)},
            "attendees": [{"email": g} for g in (event.guests or [])],
        }
        if event.kind in MEET_KINDS:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        resp = httpx.post(
            _CALENDAR_EVENTS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        # A conta vem da MESMA `cred` que acabou de autenticar a chamada — é a verdade sobre
        # quem escreveu o evento lá, e não uma releitura posterior de `get_credential` (que
        # poderia já ser outra conta se o dono reconectasse no meio). `or None` porque
        # `google_account_email` fica "" quando o `userinfo` falhou no callback: string vazia
        # não é um e-mail, é procedência desconhecida — mesma semântica do NULL da coluna.
        return data.get("hangoutLink"), data.get("id"), cred.google_account_email or None
    except Exception:
        # Falha de integração externa não derruba a Agenda (IV1). Não logamos o token.
        logger.exception("[google:create_meet:failed] tenant=%s", tenant_id)
        return None


# ── Sincronização de reschedule/cancel de volta pro Google ───────────────────
def patch_meet_event(db: Session, *, tenant_id: str, event) -> bool:
    """Propaga um REMARCAR (novos horários) para o evento espelho no Google Calendar.

    Best-effort e NÃO bloqueante (mesmo princípio de robustez de create_meet_event / IV1/IV2):
    qualquer falha (token revogado, rede, quota, 404 porque o evento sumiu lá) é capturada e
    logada — NUNCA propaga, para não derrubar o reschedule local da Agenda.

    Retorna True se sincronizou; False se não havia o que/como sincronizar (sem google_event_id,
    sem Google conectado, sem token) ou se a chamada falhou.
    """
    if not getattr(event, "google_event_id", None):
        return False
    cred = get_credential(db)
    if cred is None:
        return False
    try:
        access_token = _ensure_fresh_token(db, cred)
        if not access_token:
            return False
        body = {
            "start": {"dateTime": _iso(event.starts_at)},
            "end": {"dateTime": _iso(event.ends_at)},
        }
        resp = httpx.patch(
            _CALENDAR_EVENT_URL.format(event_id=event.google_event_id),
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception("[google:patch_meet:failed] tenant=%s", tenant_id)
        return False


def delete_meet_event(db: Session, *, tenant_id: str, event) -> bool:
    """Propaga um CANCELAR para o Google Calendar (remove o evento espelho).

    Best-effort e NÃO bloqueante (ver patch_meet_event). Um 404/410 do Google significa que o
    evento já não existe lá — o objetivo (não deixar evento fantasma) já está cumprido, então
    conta como sucesso (idempotente).
    """
    if not getattr(event, "google_event_id", None):
        return False
    cred = get_credential(db)
    if cred is None:
        return False
    try:
        access_token = _ensure_fresh_token(db, cred)
        if not access_token:
            return False
        resp = httpx.delete(
            _CALENDAR_EVENT_URL.format(event_id=event.google_event_id),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code in (404, 410):
            return True  # já não existe no Google — nada a fazer
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception("[google:delete_meet:failed] tenant=%s", tenant_id)
        return False


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
