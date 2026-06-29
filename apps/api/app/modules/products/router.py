"""Rotas de Produtos, Cupons e Alunos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.products import service
from app.modules.products.models import Enrollment, Product
from app.modules.products.schemas import (
    CouponCreate,
    CouponOut,
    EnrollmentOut,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    SellRequest,
)

router = APIRouter(prefix="/products", tags=["products"])

_guard = require_module("products")


def _product_out(p: Product, db: Session) -> ProductOut:
    base = settings.frontend_url.rstrip("/")
    return ProductOut(
        id=p.id,
        tenant_id=p.tenant_id,
        name=p.name,
        kind=p.kind,
        price_cents=p.price_cents,
        description=p.description,
        active=p.active,
        stock=p.stock,
        checkout_url=f"{base}/checkout/{p.id}",
        students=service.student_count(db, p.id),
        created_at=p.created_at,
    )


def _enroll_out(e: Enrollment, db: Session) -> EnrollmentOut:
    product = db.get(Product, e.product_id)
    return EnrollmentOut(
        id=e.id,
        tenant_id=e.tenant_id,
        product_id=e.product_id,
        product_name=product.name if product else None,
        name=e.name,
        email=e.email,
        status=e.status,
        amount_cents=e.amount_cents,
        created_at=e.created_at,
    )


def _err(e: service.ProductError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


# ── Produtos ───────────────────────────────────────────


@router.get("", response_model=list[ProductOut])
def list_products(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ProductOut]:
    return [_product_out(p, db) for p in service.list_products(db)]


@router.post("", response_model=ProductOut, status_code=201)
def create_product(
    data: ProductCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ProductOut:
    p = service.create_product(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    return _product_out(p, db)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: str,
    data: ProductUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ProductOut:
    try:
        p = service.update_product(
            db, product_id=product_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.ProductError as e:
        raise _err(e) from e
    return _product_out(p, db)


@router.post("/{product_id}/sell", response_model=EnrollmentOut, status_code=201)
def sell_product(
    product_id: str,
    data: SellRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> EnrollmentOut:
    try:
        e = service.sell(
            db, product_id=product_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.ProductError as ex:
        raise _err(ex) from ex
    return _enroll_out(e, db)


# ── Cupons ─────────────────────────────────────────────


@router.get("/coupons", response_model=list[CouponOut])
def list_coupons(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[CouponOut]:
    return [CouponOut.model_validate(c) for c in service.list_coupons(db)]


@router.post("/coupons", response_model=CouponOut, status_code=201)
def create_coupon(
    data: CouponCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CouponOut:
    try:
        c = service.create_coupon(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    except service.ProductError as e:
        raise _err(e) from e
    return CouponOut.model_validate(c)


@router.post("/coupons/{coupon_id}/toggle", response_model=CouponOut)
def toggle_coupon(
    coupon_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CouponOut:
    try:
        c = service.toggle_coupon(
            db, coupon_id=coupon_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ProductError as e:
        raise _err(e) from e
    return CouponOut.model_validate(c)


# ── Alunos ─────────────────────────────────────────────


@router.get("/enrollments", response_model=list[EnrollmentOut])
def list_enrollments(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[EnrollmentOut]:
    return [_enroll_out(e, db) for e in service.list_enrollments(db)]
