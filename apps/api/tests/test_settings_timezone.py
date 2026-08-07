"""O fuso do tenant mora em `tenants` (migration 0073) — e nada mais lê a coluna do perfil.

O bug que motivou a mudança só aparece no Postgres (RLS), e o gate contra a regressão vive em
`test_auth_timezone_rls.py`. Aqui ficam as garantias que o SQLite consegue dar: o contrato de
leitura/escrita e — principalmente — o **teste de ausência** que reprova quem voltar a ler
`tenant_profiles.timezone`.

Esse teste de ausência é o que impede o pior desfecho possível desta mudança: metade do sistema
lendo a coluna nova e a outra metade a antiga, com as duas divergindo em silêncio no dia em que
alguém trocar o fuso.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tz import DEFAULT_TENANT_TIMEZONE
from app.modules.auth.models import Tenant
from app.modules.settings.service import tenant_timezone, timezone_of

REGISTER = {
    "legal_name": "Fuso ME",
    "document": "11444777000161",
    "slug": "fusome",
    "email": "fuso@example.com",
    "name": "Flávio",
    "password": "uma-senha-bem-grande",
}

_APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_o_padrao_e_sao_paulo(client: TestClient, headers):
    assert client.get("/auth/me", headers=headers).json()["tenant"]["timezone"] == (
        DEFAULT_TENANT_TIMEZONE
    )


def test_salvar_o_fuso_reverbera_na_SESSAO(client: TestClient, headers):
    """O caminho inteiro: `/settings/profile` grava e `/auth/me` entrega.

    São sessões diferentes (uma com tenant, outra crua) e é justamente essa fronteira que estava
    quebrada — a tela salvava, e o login continuava devolvendo o padrão."""
    r = client.patch(
        "/settings/profile", json={"timezone": "America/Manaus"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["timezone"] == "America/Manaus"

    assert client.get("/auth/me", headers=headers).json()["tenant"]["timezone"] == (
        "America/Manaus"
    )
    assert client.get("/settings/profile", headers=headers).json()["timezone"] == (
        "America/Manaus"
    )


def test_o_fuso_grava_em_TENANTS_nao_no_perfil(client: TestClient, headers, db: Session):
    """Prova de onde o dado foi parar — não só de que a rota respondeu certo."""
    from app.modules.settings.models import TenantProfile

    client.patch("/settings/profile", json={"timezone": "America/Manaus"}, headers=headers)

    assert db.query(Tenant).one().timezone == "America/Manaus"
    # A coluna antiga fica congelada no default até ser dropada numa migration posterior.
    assert db.query(TenantProfile).one().timezone == DEFAULT_TENANT_TIMEZONE


def test_fuso_invalido_e_recusado(client: TestClient, headers):
    r = client.patch("/settings/profile", json={"timezone": "Marte/Olympus"}, headers=headers)
    assert r.status_code == 422


def test_os_dois_resolvedores_concordam(client: TestClient, headers, db: Session):
    """`tenant_timezone(db)` (sessão de tenant) e `timezone_of(db, id)` (sessão crua) respondem a
    mesma pergunta. Divergirem seria o bug de novo, só que ao contrário."""
    client.patch("/settings/profile", json={"timezone": "America/Belem"}, headers=headers)
    tenant_id = db.query(Tenant).one().id

    assert tenant_timezone(db) == "America/Belem"
    assert timezone_of(db, tenant_id) == "America/Belem"


def test_tenant_sem_perfil_cai_no_padrao(db: Session):
    """Fail-safe: um fuso ausente nunca pode derrubar uma request."""
    t = Tenant(slug="sem-perfil", legal_name="Sem Perfil", document="11444777000161")
    db.add(t)
    db.commit()

    assert timezone_of(db, t.id) == DEFAULT_TENANT_TIMEZONE
    assert tenant_timezone(db) == DEFAULT_TENANT_TIMEZONE


# ── Teste de AUSÊNCIA ───────────────────────────────────────────────────────────────────

# `settings/models.py` DECLARA a coluna (ela existe até ser dropada) e `settings/router.py` a
# menciona só num comentário explicando por que não a usa. Fora daí, ninguém pode lê-la.
_PODEM_MENCIONAR = {"modules/settings/models.py", "modules/settings/router.py"}


def test_ninguem_le_mais_o_fuso_do_perfil():
    """**Teste de ausência.** `tenant_profiles.timezone` está congelada: quem a ler vai receber o
    valor do dia da migration, não o que o dono configurou depois.

    Quando o fuso saiu do perfil, TRÊS consumidores continuavam lendo a coluna antiga — a Agenda
    (evento de dia inteiro), o Cockpit (a janela do dia) e a validade das notificações. Nenhum
    teste teria protestado: a coluna existe, tem valor e a leitura funciona. Só o dono, meses
    depois, veria a Agenda discordar do login sobre que dia é hoje.

    Este teste é o consumidor mecânico que aquela mudança não tinha.
    """
    ofensores: list[str] = []
    for arquivo in _APP.rglob("*.py"):
        rel = arquivo.relative_to(_APP).as_posix()
        if rel in _PODEM_MENCIONAR:
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            # `<algo>.timezone` onde `<algo>` é claramente um perfil — o padrão que existia nos
            # três call sites (`profile.timezone`, `p.timezone`, `TenantProfile.timezone`).
            if not isinstance(no, ast.Attribute) or no.attr != "timezone":
                continue
            base = no.value
            nome = base.id if isinstance(base, ast.Name) else None
            if nome in {"profile", "p", "perfil", "TenantProfile"}:
                ofensores.append(f"{rel}:{no.lineno} ({nome}.timezone)")

    assert not ofensores, (
        "Estes pontos leem o fuso do PERFIL, que está congelado desde a migration 0073. "
        "Use `settings.service.tenant_timezone(db)` (sessão de tenant) ou "
        f"`timezone_of(db, tenant_id)` (sessão crua): {ofensores}"
    )
