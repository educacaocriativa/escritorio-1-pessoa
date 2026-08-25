"""Fixtures de teste. Usa SQLite em memória + override de get_db.

Nota: RLS é específica do Postgres e NÃO é exercida aqui — é validada em ambiente com Postgres
(ver docs/AWS-DEPLOYMENT.md). Estes testes cobrem a lógica de auth/serviço/rotas.
"""
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.receipt_auth import get_receipt_db
from app.core.tenancy import get_tenant_db
from app.db.registry import Base
from app.db.session import get_db, get_tenant_session_factory
from app.main import app


# -- GUARDA DE FUSO: o `TZ` DECLARADO vs. o fuso EFETIVO do processo (issue #210) --------------
#
# Irmao do guarda de `apps/web/src/test-setup.ts` (#169/PR #172), pelo mesmo motivo e com a
# assercao INVERTIDA -- porque a medicao aqui deu outro resultado.
#
# O front EXIGE `America/Sao_Paulo`: os testes dele leem o relogio da maquina. Esta suite nao
# exige fuso nenhum, e isso foi MEDIDO, nao suposto: em 22/08/2026 a suite rodou tres vezes com
# o relogio do processo em UTC-3, UTC e UTC+9 -- no ultimo o dia LOCAL ja era 23/08 enquanto o
# UTC ainda era 22/08, que e justamente a discordancia que o #185 mostrou ser necessaria. Os
# tres deram `2200 passed, 1 skipped`. O codigo deriva data de `hoje_do_tenant()`, que e
# `datetime.now(UTC)` + `ZoneInfo` do tenant (#78, migration 0073): o fuso do PROCESSO nao e
# entrada de nada.
#
# Por isso aqui NAO se fixa `TZ` (seria o "os dois por reflexo" que a #210 proibe) e nao se
# exige fuso. O que este guarda cobra e so que o `TZ` declarado NAO MINTA.
#
# /!\ E ele existe porque a mentira e REAL e silenciosa. No Windows o CPython nao tem
# `time.tzset()`, e quem le `TZ` e a CRT da Microsoft, que NAO entende nome IANA -- ela le o
# formato POSIX (`UTC0`, `JST-9`, `BRT3`). Diante de um nome IANA ela nao falha: ela ADIVINHA.
# Medido nesta maquina em 22/08/2026, com o mesmo interpretador que roda a suite:
#
#     TZ="America/Sao_Paulo"  -> offset efetivo +01:00   (e nao -03:00)
#     TZ="Asia/Tokyo"         -> offset efetivo +01:00   (e nao +09:00)
#
# Ou seja: quem copiar para os jobs Python o `TZ: America/Sao_Paulo` que o #184 pos no job
# `frontend` ganha, na maquina de quem desenvolve, um TERCEIRO fuso -- nem o do Brasil nem o do
# CI. E quem seguir ao pe da letra a receita da propria #210 (`TZ=Asia/Tokyo`, "fuso de sinal
# oposto") mede UTC+1 achando que mede UTC+9: varredura que nao separa nada e devolve
# "0 quebras" com cara de aprovacao. Este bloco faz esse sintoma dizer o proprio nome.
#
# /!\ Ele e um DETECTOR, nao uma prova. Um nome IANA cujo palpite da CRT por acaso coincida com
# o offset certo passa batido (`Europe/Lisbon` hoje e um desses: +01:00 dos dois lados). Serve
# para o caso que doi -- o palpite DIVERGIR e ninguem notar.
def _offset_legivel(offset: timedelta | None) -> str:
    """`-03:00` em vez de `-1 day, 21:00:00`, que e como o `timedelta` negativo se imprime.

    Nao e enfeite: a mensagem inteira existe para ser LIDA sob pressao, e um offset do Brasil
    escrito como "menos um dia mais 21 horas" e exatamente o tipo de ruido que faz quem le
    desistir e ir procurar o defeito no lugar errado.
    """
    if offset is None:
        return "desconhecido"
    total = int(offset.total_seconds())
    horas, minutos = divmod(abs(total) // 60, 60)
    return f"{'-' if total < 0 else '+'}{horas:02d}:{minutos:02d}"


def _incoerencia_de_fuso(
    declarado: str | None, offset_efetivo: timedelta | None, agora: datetime
) -> str | None:
    """A regra, PURA e com o relogio INJETADO -- devolve a mensagem, ou None se nada a cobrar.

    Pura pelo mesmo motivo de `core.scheduling.status_por_data`: no Windows um teste nao consegue
    mudar o fuso EFETIVO do proprio processo (nao ha `time.tzset()`), entao um guarda que so
    lesse o ambiente seria um guarda que ninguem consegue provar que dispara.
    """
    if not declarado:
        return None  # sem `TZ` nao ha promessa a conferir -- e o caso do CI, que roda em UTC
    try:
        zona = ZoneInfo(declarado)
    except (ZoneInfoNotFoundError, ValueError):
        # `TZ` em formato POSIX (`UTC0`, `JST-9`). A CRT honra, o `zoneinfo` nao decifra, e
        # inventar um parser de POSIX TZ aqui seria trocar um detector por uma segunda fonte de
        # erro. Sem base de comparacao, nada a cobrar.
        return None
    offset_declarado = zona.utcoffset(agora)
    if offset_efetivo == offset_declarado:
        return None
    return "\n".join(
        [
            f'FUSO DECLARADO QUE O PROCESSO NAO HONRA: TZ="{declarado}" promete o offset',
            f"{_offset_legivel(offset_declarado)}, e o relogio EFETIVO deste processo esta em "
            f"{_offset_legivel(offset_efetivo)}.",
            "",
            "Nao e bug de data, de agenda nem de `hoje_do_tenant()`: e o AMBIENTE.",
            "",
            f"  os.environ['TZ'] ........ {declarado!r}",
            f"  offset que TZ promete ... {_offset_legivel(offset_declarado)}",
            f"  offset EFETIVO .......... {_offset_legivel(offset_efetivo)}",
            f"  time.tzname ............. {time.tzname}",
            f"  time.tzset() existe? .... {hasattr(time, 'tzset')}",
            "",
            "Causa provavel: Windows. Sem `time.tzset()`, quem le `TZ` e a CRT da Microsoft, que",
            "NAO entende nome IANA -- diante de um, ela ADIVINHA em vez de falhar.",
            "",
            "Para medir fuso no Windows use o formato POSIX, que a CRT entende de verdade:",
            "    UTC0 (UTC)  |  JST-9 (UTC+9)  |  BRT3 (UTC-3)",
            "...ou meca em Linux/WSL/container, onde o nome IANA vale.",
            "",
            "Esta suite NAO depende do fuso do processo (medido em 22/08/2026: 2200 verdes em",
            "UTC-3, UTC e UTC+9). O `TZ` so precisa nao mentir.",
        ]
    )


def _guarda_de_fuso() -> None:
    """Roda no import do conftest -- ou seja, antes de QUALQUER arquivo de teste.

    Fica aqui, e nao num `test_*.py` proprio, pela licao do #169: um guarda em arquivo separado
    depende da ordem de coleta e some entre os pulados assim que a suite para no primeiro erro.
    """
    agora = datetime.now(UTC)
    problema = _incoerencia_de_fuso(os.environ.get("TZ"), agora.astimezone().utcoffset(), agora)
    if problema is not None:
        raise RuntimeError(problema)


_guarda_de_fuso()


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db() -> Iterator[Session]:
    Base.metadata.create_all(engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    # Remove assinantes globais do barramento (ex.: WhatsApp on-move, que abriria uma
    # conexão Postgres real). Testes que precisam de assinante registram o seu próprio.
    from app.core import events

    events.clear()

    def _override_get_db() -> Iterator[Session]:
        yield db

    # get_tenant_db usa set_config (Postgres) — em SQLite trocamos pela sessão de teste.
    # (RLS não é exercida aqui; é validada em ambiente Postgres — ver docs/AWS-DEPLOYMENT.md.)
    # Rotas públicas abrem tenant_session direto (fora do request) — em teste, apontar à
    # sessão SQLite compartilhada em vez de abrir conexão Postgres real.
    def _override_factory():
        @contextmanager
        def _factory(_tenant_id: str) -> Iterator[Session]:
            # Espelha `tenant_session` de produção (app/db/session.py): commita ao sair do
            # `with`. Sem isso, mudanças feitas aqui (ex.: assinatura de contrato via link
            # público) ficam pendentes na sessão (autoflush=False) e uma query FILTRADA
            # subsequente (ex.: `WHERE status='signed'`) não as enxerga — só um lookup por PK
            # bateria no identity map. Único ponto de "escrita" do teste que não passava por um
            # commit explícito de service.
            yield db
            db.commit()

        return _factory

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_db] = _override_get_db
    # get_receipt_db também abre tenant_session (Postgres) — em teste, aponta para o SQLite
    # compartilhado, igual get_tenant_db. A resolução da CREDENCIAL (receipt_uploader) NÃO é
    # sobrescrita: é justamente o que os testes de token de dispositivo exercitam.
    app.dependency_overrides[get_receipt_db] = _override_get_db
    app.dependency_overrides[get_tenant_session_factory] = _override_factory
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
