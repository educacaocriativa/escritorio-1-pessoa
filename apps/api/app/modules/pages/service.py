"""Páginas: templates por modelo, CRUD, publicação (snapshot público) e captura de lead."""
from __future__ import annotations

import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.pages.models import STATUS_DRAFT, STATUS_PUBLISHED, Page, PublishedPage
from app.modules.pages.schemas import PageCreate, PageUpdate


class PageError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _h(text: str) -> dict:
    return {"type": "heading", "text": text}


def _t(text: str) -> dict:
    return {"type": "text", "text": text}


def _btn(label: str, url: str = "") -> dict:
    return {"type": "button", "label": label, "url": url}


def _form(button: str = "Enviar") -> dict:
    return {
        "type": "form", "button": button, "showEmail": True, "extraFields": [], "disclaimer": "",
    }


# Templates iniciais por modelo de página (mesmos modelos dos nós-página do funil).
STARTERS: dict[str, list[dict]] = {
    "vendas": [
        _h("Sua oferta irresistível"),
        _t("Descreva aqui o principal benefício e por que vale a pena."),
        {"type": "image", "url": ""},
        _btn("Comprar agora"),
    ],
    "captura": [
        _h("Baixe o material gratuito"),
        _t("Deixe seu contato e receba agora mesmo."),
        _form("Quero receber"),
    ],
    "obrigado": [_h("Obrigado! 🎉"), _t("Em breve entraremos em contato com você.")],
    "checkout": [_h("Finalize sua compra"), _t("Confira o resumo do pedido."), _btn("Pagar agora")],
    "download": [_h("Seu material está pronto"), _t("Clique abaixo para baixar."), _btn("Baixar")],
    "webinar": [
        _h("Webinar ao vivo"),
        _t("Inscreva-se gratuitamente e garanta sua vaga."),
        {"type": "video", "url": ""},
        _form("Garantir vaga"),
    ],
    "conteudo": [_h("Título da página"), _t("Comece a escrever o conteúdo aqui.")],
}


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:40] or "pagina").strip("-")


def _gen_slug(title: str) -> str:
    return f"{_slugify(title)}-{secrets.token_urlsafe(8)}"


def _snapshot(page: Page) -> dict:
    return {
        "title": page.title,
        "blocks": page.blocks,
        "primary_color": page.primary_color,
        "bg_color": page.bg_color,
        "text_color": page.text_color,
        "accent_color": page.accent_color,
        "font": page.font,
        "logo_url": page.logo_url,
    }


def _publish_snapshot(db: Session, page: Page) -> None:
    if not page.public_slug:
        return
    snap = db.get(PublishedPage, page.public_slug)
    if snap is None:
        snap = PublishedPage(slug=page.public_slug)
        db.add(snap)
    snap.tenant_id = page.tenant_id
    snap.page_id = page.id
    snap.data = _snapshot(page)


def create_page(db: Session, *, tenant_id: str, actor: str, data: PageCreate) -> Page:
    from app.modules.settings import service as settings_service

    profile = settings_service.get_profile(db, tenant_id)  # herda o Brand Kit
    blocks = data.blocks
    if blocks is None:
        blocks = STARTERS.get(data.model, STARTERS["conteudo"])
    page = Page(
        tenant_id=tenant_id,
        title=data.title,
        model=data.model,
        blocks=blocks,
        public_slug=_gen_slug(data.title),
        primary_color=profile.primary_color,
        bg_color=profile.bg_color,
        text_color=profile.text_color,
        accent_color=profile.accent_color,
        font=profile.font,
        logo_url=profile.logo_url,
    )
    db.add(page)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="page.create", target=page.id)
    db.commit()
    db.refresh(page)
    return page


def get_page(db: Session, page_id: str) -> Page:
    p = db.get(Page, page_id)
    if p is None:
        raise PageError("Página não encontrada", 404)
    return p


def list_pages(db: Session) -> list[Page]:
    return list(db.scalars(select(Page).order_by(Page.created_at.desc())).all())


def update_page(db: Session, *, page_id: str, tenant_id: str, actor: str, data: PageUpdate) -> Page:
    page = get_page(db, page_id)
    for f in ("title", "blocks", "primary_color", "bg_color", "text_color", "accent_color",
              "font", "logo_url"):
        val = getattr(data, f)
        if val is not None:
            setattr(page, f, val)
    if page.status == STATUS_PUBLISHED:  # mantém o público em dia
        _publish_snapshot(db, page)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="page.update", target=page.id)
    db.commit()
    db.refresh(page)
    return page


def publish(db: Session, *, page_id: str, tenant_id: str, actor: str) -> Page:
    page = get_page(db, page_id)
    page.status = STATUS_PUBLISHED
    _publish_snapshot(db, page)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="page.publish", target=page.id)
    db.commit()
    db.refresh(page)
    return page


def unpublish(db: Session, *, page_id: str, tenant_id: str, actor: str) -> Page:
    page = get_page(db, page_id)
    page.status = STATUS_DRAFT
    if page.public_slug:
        snap = db.get(PublishedPage, page.public_slug)
        if snap is not None:
            db.delete(snap)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="page.unpublish", target=page.id)
    db.commit()
    db.refresh(page)
    return page


def delete_page(db: Session, *, page_id: str, tenant_id: str, actor: str) -> None:
    page = get_page(db, page_id)
    if page.public_slug:
        snap = db.get(PublishedPage, page.public_slug)
        if snap is not None:
            db.delete(snap)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="page.delete", target=page.id)
    db.delete(page)
    db.commit()


# ── Público (sem login) ─────────────────────────────────────────────────────
def public_view(db: Session, *, slug: str) -> dict:
    snap = db.get(PublishedPage, slug)
    if snap is None:
        raise PageError("Página não encontrada", 404)
    return snap.data


def _format_fields(fields: dict[str, str] | None) -> str:
    if not fields:
        return ""
    lines = "\n".join(f"{k}: {v}" for k, v in fields.items() if v)
    return f"Campos do formulário:\n{lines}" if lines else ""


def public_submit(
    db: Session,
    *,
    slug: str,
    name: str,
    email: str | None,
    phone: str,
    fields: dict[str, str] | None = None,
    session_factory,
) -> None:
    """Formulário de captura → cria um LEAD no CRM do tenant dono da página."""
    snap = db.get(PublishedPage, slug)
    if snap is None:
        raise PageError("Página não encontrada", 404)
    from app.modules.crm import service as crm_service
    from app.modules.crm.schemas import ClientCreate

    with session_factory(snap.tenant_id) as tdb:
        crm_service.create_client(
            tdb, tenant_id=snap.tenant_id, actor="pagina:lead",
            data=ClientCreate(
                name=name, email=email, phone=phone or None, source="landing",
                notes=_format_fields(fields),
            ),
        )
