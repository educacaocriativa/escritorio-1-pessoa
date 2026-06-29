"""Registro de módulos de negócio.

Cada módulo expõe um `router` (APIRouter). Adicione novos módulos aqui conforme construídos.
"""
from fastapi import APIRouter

from app.modules.auth.router import router as auth_router

ALL_ROUTERS: list[APIRouter] = [
    auth_router,
]
