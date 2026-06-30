"""Registro de módulos de negócio.

Cada módulo expõe um `router` (APIRouter). Adicione novos módulos aqui conforme construídos.
"""
from fastapi import APIRouter

from app.modules.agenda.router import router as agenda_router
from app.modules.auth.router import router as auth_router
from app.modules.cockpit.router import router as cockpit_router
from app.modules.contracts.router import public_router as contracts_public_router
from app.modules.contracts.router import router as contracts_router
from app.modules.crm.router import router as crm_router
from app.modules.funnels.router import router as funnels_router
from app.modules.marketing.router import router as marketing_router
from app.modules.notifications.router import router as notifications_router
from app.modules.pages.router import public_router as pages_public_router
from app.modules.pages.router import router as pages_router
from app.modules.payables.router import router as payables_router
from app.modules.platform.router import router as platform_router
from app.modules.products.router import router as products_router
from app.modules.quotes.router import public_router as quotes_public_router
from app.modules.quotes.router import router as quotes_router
from app.modules.receivables.router import router as receivables_router
from app.modules.settings.router import router as settings_router
from app.modules.stock.router import router as stock_router
from app.modules.wallet.router import router as wallet_router

ALL_ROUTERS: list[APIRouter] = [
    auth_router,
    agenda_router,
    crm_router,
    cockpit_router,
    platform_router,
    notifications_router,
    wallet_router,
    receivables_router,
    payables_router,
    products_router,
    quotes_router,
    quotes_public_router,
    contracts_router,
    contracts_public_router,
    marketing_router,
    funnels_router,
    stock_router,
    settings_router,
    pages_router,
    pages_public_router,
]
