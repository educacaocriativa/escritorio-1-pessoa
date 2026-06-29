"""Regras de Produtos, Cupons e Alunos. Vender cria Transaction (split) + matricula o Aluno."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.products.models import (
    DISCOUNT_FIXED,
    ENROLL_ACTIVE,
    Coupon,
    Enrollment,
    Product,
)
from app.modules.products.schemas import (
    CouponCreate,
    ProductCreate,
    ProductUpdate,
    SellRequest,
)
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import KIND_PRODUCT


class ProductError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ── Produtos ───────────────────────────────────────────


def create_product(db: Session, *, tenant_id: str, actor: str, data: ProductCreate) -> Product:
    p = Product(
        tenant_id=tenant_id,
        name=data.name,
        kind=data.kind,
        price_cents=data.price_cents,
        description=data.description,
        stock=data.stock,
    )
    db.add(p)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="product.create", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def list_products(db: Session) -> list[Product]:
    return list(db.scalars(select(Product).order_by(Product.created_at.desc())).all())


def get_product(db: Session, product_id: str) -> Product:
    p = db.get(Product, product_id)
    if p is None:
        raise ProductError("Produto não encontrado", 404)
    return p


def update_product(
    db: Session, *, product_id: str, tenant_id: str, actor: str, data: ProductUpdate
) -> Product:
    p = get_product(db, product_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(p, key, value)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="product.update", target=p.id)
    db.commit()
    db.refresh(p)
    return p


def student_count(db: Session, product_id: str) -> int:
    return db.scalar(
        select(func.count(Enrollment.id)).where(
            Enrollment.product_id == product_id, Enrollment.status == ENROLL_ACTIVE
        )
    ) or 0


# ── Cupons ─────────────────────────────────────────────


def create_coupon(db: Session, *, tenant_id: str, actor: str, data: CouponCreate) -> Coupon:
    if data.discount_type == "percent" and data.discount_value > 100:
        raise ProductError("Desconto percentual não pode passar de 100%", 422)
    c = Coupon(
        tenant_id=tenant_id,
        code=data.code,
        discount_type=data.discount_type,
        discount_value=data.discount_value,
        product_id=data.product_id,
        max_uses=data.max_uses,
        expires_at=data.expires_at,
    )
    db.add(c)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="coupon.create", target=c.id)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ProductError("Já existe um cupom com esse código", 409) from e
    db.refresh(c)
    return c


def list_coupons(db: Session) -> list[Coupon]:
    return list(db.scalars(select(Coupon).order_by(Coupon.created_at.desc())).all())


def toggle_coupon(db: Session, *, coupon_id: str, tenant_id: str, actor: str) -> Coupon:
    c = db.get(Coupon, coupon_id)
    if c is None:
        raise ProductError("Cupom não encontrado", 404)
    c.active = not c.active
    audit.record(db, tenant_id=tenant_id, actor=actor, action="coupon.toggle", target=c.id)
    db.commit()
    db.refresh(c)
    return c


def _apply_coupon(coupon: Coupon, price: int) -> int:
    if coupon.discount_type == DISCOUNT_FIXED:
        final = price - coupon.discount_value
    else:  # percent
        final = price - (price * coupon.discount_value + 50) // 100
    return max(0, final)


def _valid_coupon(db: Session, code: str, product_id: str) -> Coupon:
    coupon = db.scalar(select(Coupon).where(Coupon.code == code.strip().upper()))
    if coupon is None or not coupon.active:
        raise ProductError("Cupom inválido", 404)
    if coupon.product_id and coupon.product_id != product_id:
        raise ProductError("Cupom não vale para este produto", 422)
    if coupon.max_uses is not None and coupon.uses >= coupon.max_uses:
        raise ProductError("Cupom esgotado", 409)
    if coupon.expires_at is not None and coupon.expires_at < datetime.now(UTC).date():
        raise ProductError("Cupom expirado", 409)
    return coupon


# ── Venda / Alunos ─────────────────────────────────────


def sell(
    db: Session, *, product_id: str, tenant_id: str, actor: str, data: SellRequest
) -> Enrollment:
    """Vende o produto: aplica cupom, cria a transação (split) e matricula o aluno. Atômico."""
    product = get_product(db, product_id)
    if not product.active:
        raise ProductError("Produto inativo", 409)

    price = product.price_cents
    coupon = None
    if data.coupon_code:
        coupon = _valid_coupon(db, data.coupon_code, product_id)
        price = _apply_coupon(coupon, price)
    if price <= 0:
        raise ProductError("Valor final inválido (cupom zera o preço)", 422)

    tx = wallet_service.build_transaction(
        db, tenant_id=tenant_id, actor=actor, by_ai=False,
        kind=KIND_PRODUCT, method=data.method, gross_cents=price,
        description=f"Venda: {product.name}",
    )
    enrollment = Enrollment(
        tenant_id=tenant_id,
        product_id=product_id,
        name=data.name,
        email=str(data.email) if data.email else None,
        amount_cents=price,
        transaction_id=tx.id,
    )
    db.add(enrollment)
    if product.stock is not None and product.stock > 0:
        product.stock -= 1
    if coupon is not None:
        coupon.uses += 1
    audit.record(db, tenant_id=tenant_id, actor=actor, action="product.sell", target=product_id)
    db.commit()
    db.refresh(enrollment)
    return enrollment


def list_enrollments(db: Session) -> list[Enrollment]:
    return list(db.scalars(select(Enrollment).order_by(Enrollment.created_at.desc())).all())
