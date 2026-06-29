"""Marketing: geração de carrossel editorial por IA (com fallback) + templates + CRUD.

Estilo inspirado na skill do usuário (ver docs/skills/carrosseis-instagram.md): carrossel
editorial/investigativo 4:5 com capa, slides editoriais, slide de acento e CTA, + legenda
e hashtags. A geração de IMAGEM (HTML→PNG) acontece no front (html2canvas).
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.modules.marketing.models import Carousel
from app.modules.marketing.schemas import CarouselCreate, CarouselUpdate

# Templates personalizáveis (ponto de partida; usuário ajusta cores/fonte).
TEMPLATES = [
    {"key": "editorial", "label": "Editorial", "primary_color": "#B078FF", "bg_color": "#292A25",
     "text_color": "#FFFFFF", "accent_color": "#3CD3A4", "font": "Raleway"},
    {"key": "moderno", "label": "Moderno", "primary_color": "#5D44F8", "bg_color": "#0F1020",
     "text_color": "#FFFFFF", "accent_color": "#3DD68C", "font": "Inter"},
    {"key": "minimalista", "label": "Minimalista", "primary_color": "#111827",
     "bg_color": "#FFFFFF", "text_color": "#111827", "accent_color": "#5D44F8", "font": "Inter"},
    {"key": "gradiente", "label": "Gradiente", "primary_color": "#FF6B6B", "bg_color": "#2D1B4E",
     "text_color": "#FFFFFF", "accent_color": "#FFD93D", "font": "Poppins"},
    {"key": "juridico", "label": "Jurídico", "primary_color": "#1E3A5F", "bg_color": "#0B1A2B",
     "text_color": "#F5F1E6", "accent_color": "#C8A04A", "font": "Georgia"},
    {"key": "vibrante", "label": "Vibrante", "primary_color": "#FF2D87", "bg_color": "#1A1A2E",
     "text_color": "#FFFFFF", "accent_color": "#00F5D4", "font": "Poppins"},
]

_EDITORIAL_SYSTEM = (
    "Você cria carrosséis editoriais/investigativos para Instagram (pt-BR), estilo manchete de "
    "revista que para o scroll. REGRA DE OURO: se uma pessoa leiga não entende, falhou — zero "
    "jargão sem explicação.\n"
    "Responda APENAS com um objeto JSON: "
    "{\"slides\": [...], \"caption\": \"...\", \"hashtags\": \"...\"}.\n"
    "Cada slide é {\"kind\", \"heading\", \"body\", \"secondary\", \"highlight\"}:\n"
    "- 1º slide kind='cover': heading = título IMPACTANTE em CAIXA ALTA (pergunta provocativa ou "
    "afirmação chocante); highlight = 1 palavra-chave do título.\n"
    "- slides do meio kind='editorial': heading = frase narrativa (storytelling, 1 ideia por "
    "slide), secondary = complemento com dado/número; highlight = palavra a destacar.\n"
    "- 1 slide do meio pode ser kind='accent' (frase de impacto máximo).\n"
    "- último slide kind='cta': heading = chamada (ex.: 'GOSTOU? SALVE ESTE POST'); "
    "body = 'Compartilhe com quem precisa'.\n"
    "Máximo ~30 palavras por slide. caption = legenda envolvente (2-4 linhas). "
    "hashtags = 8 a 10 hashtags relevantes separadas por espaço, cada uma começando com #."
)


class MarketingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _fallback(topic: str, n: int) -> dict:
    first = topic.strip().split()[0] if topic.strip() else "Isso"
    slides = [{"kind": "cover", "heading": topic.strip().upper()[:90], "body": "",
               "secondary": "", "highlight": first}]
    for i in range(1, n - 1):
        slides.append({
            "kind": "accent" if i == n - 2 else "editorial",
            "heading": f"Ponto {i} sobre {topic}".strip(),
            "body": "",
            "secondary": "Explique aqui o ponto com um dado ou exemplo.",
            "highlight": "",
        })
    slides.append({"kind": "cta", "heading": "GOSTOU? SALVE ESTE POST",
                   "body": "Salve e compartilhe com quem precisa.",
                   "secondary": "", "highlight": ""})
    return {
        "slides": slides[:n],
        "caption": f"{topic}\n\nSalve este carrossel e compartilhe com quem precisa. 🚀",
        "hashtags": "#conteudo #dicas #negocios #empreendedorismo #marketing "
                    "#instagram #carrossel #brasil",
    }


def _parse(text: str, topic: str, n: int) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    raw = data.get("slides", []) if isinstance(data, dict) else data
    slides = []
    for s in raw:
        slides.append({
            "kind": str(s.get("kind", "editorial"))[:12],
            "heading": str(s.get("heading", ""))[:200],
            "body": str(s.get("body", ""))[:600],
            "secondary": str(s.get("secondary", ""))[:400],
            "highlight": str(s.get("highlight", ""))[:80],
        })
    if not slides:
        raise ValueError("sem slides")
    if len(slides) < n:
        slides += _fallback(topic, n)["slides"][len(slides):]
    return {
        "slides": slides[:n],
        "caption": str(data.get("caption", "") if isinstance(data, dict) else "")[:1500],
        "hashtags": str(data.get("hashtags", "") if isinstance(data, dict) else "")[:600],
    }


def generate_content(topic: str, n: int, tone: str) -> dict:
    """IA escreve slides + legenda + hashtags; cai para um esqueleto editorial em caso de erro."""
    if not settings.anthropic_api_key:
        return _fallback(topic, n)
    user = f"Tema: {topic}\nNúmero de slides: {n}\nTom: {tone}"
    try:
        text = ai.complete(system=_EDITORIAL_SYSTEM, user_message=user, max_tokens=2000).text
        return _parse(text, topic, n)
    except Exception:
        return _fallback(topic, n)


_FIELDS = ("topic", "status", "handle", "caption", "hashtags", "template",
           "primary_color", "bg_color", "text_color", "accent_color", "font")


def create_carousel(db: Session, *, tenant_id: str, actor: str, data: CarouselCreate) -> Carousel:
    car = Carousel(
        tenant_id=tenant_id,
        topic=data.topic,
        slides=[s.model_dump() for s in data.slides],
        handle=data.handle,
        caption=data.caption,
        hashtags=data.hashtags,
        template=data.template,
        primary_color=data.primary_color,
        bg_color=data.bg_color,
        text_color=data.text_color,
        accent_color=data.accent_color,
        font=data.font,
    )
    db.add(car)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="carousel.create", target=car.id)
    db.commit()
    db.refresh(car)
    return car


def get_carousel(db: Session, carousel_id: str) -> Carousel:
    car = db.get(Carousel, carousel_id)
    if car is None:
        raise MarketingError("Carrossel não encontrado", 404)
    return car


def list_carousels(db: Session) -> list[Carousel]:
    return list(db.scalars(select(Carousel).order_by(Carousel.created_at.desc())).all())


def update_carousel(
    db: Session, *, carousel_id: str, tenant_id: str, actor: str, data: CarouselUpdate
) -> Carousel:
    car = get_carousel(db, carousel_id)
    for f in _FIELDS:
        val = getattr(data, f)
        if val is not None:
            setattr(car, f, val)
    if data.slides is not None:
        car.slides = [s.model_dump() for s in data.slides]
    audit.record(db, tenant_id=tenant_id, actor=actor, action="carousel.update", target=car.id)
    db.commit()
    db.refresh(car)
    return car


def delete_carousel(db: Session, *, carousel_id: str, tenant_id: str, actor: str) -> None:
    car = get_carousel(db, carousel_id)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="carousel.delete", target=car.id)
    db.delete(car)
    db.commit()
