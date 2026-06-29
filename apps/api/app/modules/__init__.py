"""Registro de módulos de negócio.

Cada módulo expõe um `router` (APIRouter). Adicione novos módulos aqui conforme construídos.
"""
from fastapi import APIRouter

from app.modules.agenda.router import router as agenda_router
from app.modules.auth.router import router as auth_router
from app.modules.crm.router import router as crm_router

ALL_ROUTERS: list[APIRouter] = [
    auth_router,
    agenda_router,
    crm_router,
]
