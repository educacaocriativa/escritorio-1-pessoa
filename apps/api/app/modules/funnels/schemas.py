"""Schemas do Construtor de Funil de Vendas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FunnelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class FunnelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    nodes: list[dict] | None = None
    edges: list[dict] | None = None


class FunnelOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    nodes: list[dict]
    edges: list[dict]
    created_at: datetime


class FunnelSummary(BaseModel):
    id: str
    name: str
    node_count: int
    created_at: datetime


class ComponentItem(BaseModel):
    key: str
    label: str
    description: str
    shape: str = "node"  # "page" (quadrado, com mockup) | "node" (redondo)
    action: str = ""  # tipo de ação executável (vazio = só diagrama)


class ComponentCategory(BaseModel):
    category: str
    label: str
    color: str
    items: list[ComponentItem]


class ComposeRequest(BaseModel):
    kind: str = Field(default="generic")  # email | whatsapp | sms | generic
    prompt: str = Field(min_length=2, max_length=500)


class ComposeResult(BaseModel):
    subject: str = ""
    body: str = ""


class RunNodeRequest(BaseModel):
    action: str = Field(min_length=1)  # create_client | add_tag | create_quote | ...
    client_id: str | None = None
    params: dict = Field(default_factory=dict)


class RunNodeResult(BaseModel):
    message: str
    kind: str = ""
    ref_id: str | None = None
