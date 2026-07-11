"""Testes da varredura de órfãos no object storage (Story 6.1).

Roda o script contra o SQLite de teste com `get_db`/`tenant_session` sobrescritos (mesmo padrão
do `test_migrate_attachments_to_s3.py`) e o storage mockado (dict em memória, sem bater em S3
real — mesma lacuna de CI já documentada p/ RLS/S3). Cobre os 3 IVs:

  - IV1: objeto referenciado por anexo vivo NUNCA é apagado.
  - IV2: o escopo por prefixo (`tenants/{id}/...`) não mistura objetos entre tenants.
  - IV3: dry-run (padrão) não remove nada; `--apply` remove só os órfãos confirmados.
"""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core import storage
from app.core.storage import StorageObject
from app.scripts import scan_orphan_storage as scan

TENANT_A = "aaaaaaaa-1111-2222-3333-444444444444"
TENANT_B = "bbbbbbbb-1111-2222-3333-444444444444"

# Chaves sob o prefixo real de cada tenant (`tenants/{id}/attachments/...`).
KA = f"tenants/{TENANT_A}/attachments/att-ka/doc.pdf"   # vivo (referenciado) — tenant A
OA = f"tenants/{TENANT_A}/attachments/att-oa/orfao.pdf"  # órfão antigo (30d) — tenant A
RA = f"tenants/{TENANT_A}/attachments/att-ra/recente.pdf"  # órfão porém recente (6h) — tenant A
MID = f"tenants/{TENANT_A}/attachments/att-mid/mid.pdf"  # órfão de 3 dias — tenant A
KB = f"tenants/{TENANT_B}/attachments/att-kb/doc.pdf"   # vivo (referenciado) — tenant B
OB = f"tenants/{TENANT_B}/attachments/att-ob/orfao.pdf"  # órfão antigo (30d) — tenant B

OLD = datetime.now(UTC) - timedelta(days=30)
MID_AGE = datetime.now(UTC) - timedelta(days=3)
RECENT = datetime.now(UTC) - timedelta(hours=6)


class FakeStorage:
    """Bucket em memória: mapeia chave→LastModified e registra as remoções."""

    def __init__(self) -> None:
        self.objects: dict[str, datetime] = {
            KA: OLD, OA: OLD, RA: RECENT, MID: MID_AGE, KB: OLD, OB: OLD,
        }
        self.configured = True
        self.deleted: list[str] = []

    def is_configured(self) -> bool:
        return self.configured

    def list_objects(self, prefix: str) -> list[StorageObject]:
        return [
            StorageObject(key=k, last_modified=ts)
            for k, ts in self.objects.items()
            if k.startswith(prefix)
        ]

    def delete_object(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture()
def seeded(db: Session) -> Session:
    from app.modules.attachments.models import Attachment
    from app.modules.auth.models import Tenant

    db.add(Tenant(id=TENANT_A, slug="ta", legal_name="Tenant A SA", document="1"))
    db.add(Tenant(id=TENANT_B, slug="tb", legal_name="Tenant B SA", document="2"))
    # Só KA e KB estão VIVOS (referenciados por um Attachment com storage_key).
    db.add(Attachment(
        tenant_id=TENANT_A, owner_type="payable", owner_id="p1", label="boleto",
        filename="doc.pdf", content_type="application/pdf", size=5, data=None, storage_key=KA,
    ))
    db.add(Attachment(
        tenant_id=TENANT_B, owner_type="payable", owner_id="p2", label="boleto",
        filename="doc.pdf", content_type="application/pdf", size=5, data=None, storage_key=KB,
    ))
    db.commit()
    return db


@pytest.fixture()
def wired(monkeypatch: pytest.MonkeyPatch, seeded: Session) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(storage, "is_configured", fake.is_configured)
    monkeypatch.setattr(storage, "list_objects", fake.list_objects)
    monkeypatch.setattr(storage, "delete_object", fake.delete_object)

    def _get_db():
        yield seeded

    @contextmanager
    def _tenant_session(_tid: str):
        yield seeded

    monkeypatch.setattr(scan, "get_db", _get_db)
    monkeypatch.setattr(scan, "tenant_session", _tenant_session)
    return fake


def test_find_orphans_marks_only_old_unreferenced(wired: FakeStorage):
    orphans = scan.find_orphans(older_than_days=7)
    keys = {o.key for o in orphans}
    # OA e OB são órfãos antigos (30d); KA/KB vivos (IV1); RA (6h) e MID (3d) < 7d → fora (AC2).
    assert keys == {OA, OB}


def test_iv2_orphans_attributed_to_correct_tenant(wired: FakeStorage):
    orphans = scan.find_orphans(older_than_days=7)
    by_key = {o.key: o.tenant_id for o in orphans}
    # O escopo por prefixo não mistura tenants: OA é do A, OB é do B.
    assert by_key[OA] == TENANT_A
    assert by_key[OB] == TENANT_B


def test_iv3_dry_run_deletes_nothing(wired: FakeStorage, capsys: pytest.CaptureFixture[str]):
    rc = scan.main([])  # sem --apply = dry-run (padrão)
    assert rc == 0
    assert wired.deleted == []  # NENHUMA remoção
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert OA in out and OB in out


def test_apply_deletes_only_confirmed_orphans(wired: FakeStorage):
    rc = scan.main(["--apply"])
    assert rc == 0
    # Remove EXATAMENTE os órfãos confirmados — nem a mais (KA/KB vivos, RA recente) nem a menos.
    assert sorted(wired.deleted) == sorted([OA, OB])


def test_iv1_live_objects_survive_apply(wired: FakeStorage):
    scan.main(["--apply"])
    assert KA not in wired.deleted
    assert KB not in wired.deleted
    assert KA in wired.objects and KB in wired.objects


def test_recent_orphan_not_removed(wired: FakeStorage):
    scan.main(["--apply"])
    assert RA not in wired.deleted  # recente demais (< older-than), mesmo sendo órfão


def test_older_than_window_moves_boundary(wired: FakeStorage):
    # Estreitar a janela para 1 dia passa a capturar o órfão de 3 dias (MID), mas NUNCA o de 6h
    # (RA) — demonstra que o filtro de idade é o que separa "em voo" de "lixo".
    keys = {o.key for o in scan.find_orphans(older_than_days=1)}
    assert MID in keys       # 3 dias > 1 dia → agora é candidato
    assert RA not in keys    # 6h < 1 dia → segue protegido (em voo)
    assert {OA, OB} <= keys  # os antigos continuam candidatos


def test_noop_without_bucket(monkeypatch: pytest.MonkeyPatch):
    calls = {"list": 0, "delete": 0}

    def _list(_prefix: str):
        calls["list"] += 1
        return []

    def _delete(_key: str):
        calls["delete"] += 1

    monkeypatch.setattr(storage, "is_configured", lambda: False)
    monkeypatch.setattr(storage, "list_objects", _list)
    monkeypatch.setattr(storage, "delete_object", _delete)

    rc = scan.main(["--apply"])
    assert rc == 0  # NO-OP: retorna 0 (não 1) sem tentar listar/deletar nada
    assert calls == {"list": 0, "delete": 0}


def test_older_than_must_be_positive():
    with pytest.raises(SystemExit):
        scan._parse_args(["--older-than", "0"])
    with pytest.raises(SystemExit):
        scan._parse_args(["--older-than", "-3"])


def test_storage_key_survey_is_current():
    """CANÁRIO anti-regressão (Story 6.1 — review @architect/Aria).

    `find_orphans` define "objeto vivo" APENAS a partir de `Attachment.storage_key`
    (ver `_live_storage_keys`). Se QUALQUER outra tabela passar a usar o object storage
    (ganhar uma coluna `storage_key`) sem que `_live_storage_keys()` **e** o LEVANTAMENTO no
    topo de `scan_orphan_storage.py` sejam atualizados, a varredura passaria a marcar os
    objetos VIVOS dessa tabela como órfãos e os APAGARIA — falso positivo destrutivo que só
    apareceria em produção (não há S3 no CI). Este teste quebra DE PROPÓSITO nesse momento,
    convertendo uma regressão silenciosa numa falha alta e visível de CI, e apontando o quê
    atualizar. Guarda concreta para o cenário levantado na Task 1 (ex.: migrar `PublicImage`
    para o S3), mais amplo que só `PublicImage`: cobre qualquer tabela nova.
    """
    from app.db.registry import Base  # importa TODOS os modelos → metadata completo

    tables_with_storage_key = {
        name
        for name, table in Base.metadata.tables.items()
        if "storage_key" in table.columns
    }
    assert tables_with_storage_key == {"attachments"}, (
        "Uma tabela além de `attachments` passou a ter a coluna `storage_key` "
        f"(={tables_with_storage_key}). Atualize `_live_storage_keys()` e o LEVANTAMENTO no "
        "topo de scan_orphan_storage.py para incluir as chaves vivas dessa nova tabela — "
        "senão a varredura de órfãos APAGARÁ objetos ainda em uso."
    )
