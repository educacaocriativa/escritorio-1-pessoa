"""Marketing: geração de carrossel por IA (com fallback) + templates personalizáveis + CRUD."""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.modules.marketing.models import Carousel
from app.modules.marketing.schemas import CarouselCreate, CarouselUpdate

# Templates personalizáveis: ponto de partida que o usuário ajusta (cores/fonte).
TEMPLATES = [
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


class MarketingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _fallback_slides(topic: str, n: int) -> list[dict]:
    slides = [{"heading": topic.strip()[:60], "body": "Arraste para o lado 👉"}]
    for i in range(1, n - 1):
        slides.append({"heading": f"Ponto {i}", "body": f"Algo importante sobre {topic}."})
    slides.append({"heading": "Gostou?", "body": "Salve este post e siga para mais! 🚀"})
    return slides[:n]


def _parse_slides(text: str) -> list[dict]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    out = []
    for s in data:
        out.append({
            "heading": str(s.get("heading", ""))[:120],
            "body": str(s.get("body", ""))[:500],
        })
    if not out:
        raise ValueError("vazio")
    return out


def generate_slides(topic: str, n: int, tone: str) -> list[dict]:
    """IA escreve os slides; cai para um esqueleto se não houver chave/parsing falhar."""
    if not settings.anthropic_api_key:
        return _fallback_slides(topic, n)
    system = (
        "Você é redator de carrosséis de Instagram (pt-BR). Gere um carrossel envolvente. "
        "Responda APENAS com um array JSON de objetos {\"heading\": \"...\", \"body\": \"...\"}. "
        "O 1º slide é um gancho forte; os do meio entregam valor; o último é uma CTA. "
        "headings curtos (até 6 palavras), body com 1-2 frases."
    )
    user = f"Tema: {topic}\nNúmero de slides: {n}\nTom: {tone}"
    try:
        text = ai.complete(system=system, user_message=user, max_tokens=1500).text
        slides = _parse_slides(text)
        return slides[:n] if len(slides) >= n else slides + _fallback_slides(topic, n)[len(slides):]
    except Exception:
        return _fallback_slides(topic, n)


def create_carousel(db: Session, *, tenant_id: str, actor: str, data: CarouselCreate) -> Carousel:
    car = Carousel(
        tenant_id=tenant_id,
        topic=data.topic,
        slides=[s.model_dump() for s in data.slides],
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
    fields = ("topic", "status", "template", "primary_color", "bg_color", "text_color",
              "accent_color", "font")
    for f in fields:
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
