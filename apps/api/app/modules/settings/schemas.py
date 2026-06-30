"""Schemas de Configurações + Brand Kit."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProfileOut(BaseModel):
    display_name: str
    document: str
    email: str
    phone: str
    address: str
    website: str
    about: str
    logo_url: str
    primary_color: str
    secondary_color: str
    accent_color: str
    text_color: str
    bg_color: str
    font: str


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    document: str | None = Field(default=None, max_length=18)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=255)
    about: str | None = None
    logo_url: str | None = Field(default=None, max_length=1024)
    primary_color: str | None = Field(default=None, max_length=9)
    secondary_color: str | None = Field(default=None, max_length=9)
    accent_color: str | None = Field(default=None, max_length=9)
    text_color: str | None = Field(default=None, max_length=9)
    bg_color: str | None = Field(default=None, max_length=9)
    font: str | None = Field(default=None, max_length=40)
