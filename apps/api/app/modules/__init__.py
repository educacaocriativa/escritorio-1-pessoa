"""Registro de módulos de negócio.

Cada módulo expõe um `router` (APIRouter). Conforme forem criados, importe e adicione em ALL_ROUTERS.
Ex.:
    from app.modules.agenda.router import router as agenda_router
    ALL_ROUTERS = [agenda_router, ...]
"""
from fastapi import APIRouter

ALL_ROUTERS: list[APIRouter] = []
