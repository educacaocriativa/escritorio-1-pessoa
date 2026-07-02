"""Catálogo de skills jurídicas: carrega os wizard_configs (formulários) e os SKILL.md
(prompts-sistema) que vivem em juridico/resources/. Cacheado em memória no primeiro acesso.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_RES = Path(__file__).parent / "resources"
_CONFIGS = _RES / "wizard_configs"
_SKILLS = _RES / "skills"


@lru_cache(maxsize=1)
def _configs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not _CONFIGS.exists():
        return out
    for f in sorted(_CONFIGS.glob("*.json")):
        if f.name.startswith("._"):
            continue
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
            out[cfg["skill"]] = cfg
        except Exception:  # noqa: BLE001, S112 — config inválido é ignorado, não derruba o catálogo
            continue
    return out


@lru_cache(maxsize=64)
def skill_prompt(skill: str) -> str | None:
    """Conteúdo do SKILL.md (prompt-sistema) da skill, procurando em qualquer categoria."""
    if not _SKILLS.exists():
        return None
    for root, dirs, files in os.walk(_SKILLS):
        dirs[:] = [d for d in dirs if not d.startswith("._")]
        if Path(root).name == skill and "SKILL.md" in files:
            return (Path(root) / "SKILL.md").read_text(encoding="utf-8")
    return None


def list_skills() -> list[dict]:
    """Metadados de todas as skills, para a grade de seleção (sem os passos do formulário)."""
    return [
        {
            "skill": c["skill"],
            "label": c.get("label", c["skill"]),
            "category": c.get("category", "core"),
            "description": c.get("description", ""),
            "output_type": c.get("output_type", "Documento jurídico"),
        }
        for c in _configs().values()
    ]


def get_config(skill: str) -> dict | None:
    """Config completo (com os passos do formulário) de uma skill."""
    return _configs().get(skill)
