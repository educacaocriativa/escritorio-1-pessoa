"""Administração da ingestão de leads (`POST /public/ingest/leads`) — sem tela, de propósito.

    docker compose exec api python -m app.scripts.lead_ingest_admin emitir-token --tenant <slug> --nome "site nexuspublica.com.br"
    docker compose exec api python -m app.scripts.lead_ingest_admin listar-tokens --tenant <slug>
    docker compose exec api python -m app.scripts.lead_ingest_admin revogar-token --id <uuid>
    docker compose exec api python -m app.scripts.lead_ingest_admin configurar --tenant <slug> --produto publia --funil lead=<funnel_id> --funil carrinho_abandonado=<funnel_id>
    docker compose exec api python -m app.scripts.lead_ingest_admin mostrar --tenant <slug>

O token cru é impresso UMA vez, na última linha: guarde-o direto no cofre do site. Erro de
operador (slug, evento ou funil inexistente) sai com código 2 e mensagem, nunca traceback.

Isolamento: `tenants` e `machine_tokens` são globais (sessão de `get_db`, filtro explícito); a
configuração mora em `tenant_profiles` (RLS) e é escrita numa `tenant_session` do tenant
resolvido pelo slug. Passo a passo de produção: `docs/RUNBOOK-INGESTAO-DE-LEADS.md`.
"""  # noqa: E501
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.db.session import get_db, tenant_session
from app.modules.auth.models import Tenant
from app.modules.funnels.models import Funnel
from app.modules.lead_ingest import config
from app.modules.machine_tokens import service as machine_tokens_service
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST, MachineToken
from app.modules.settings import service as settings_service

ATOR = "script:lead_ingest_admin"


class AdminError(Exception):
    """Entrada inválida do operador. Vira mensagem e exit 2, nunca traceback."""


@contextmanager
def _sessao_global() -> Iterator[Session]:
    gen = get_db()
    db = next(gen)
    try:
        yield db
    finally:
        gen.close()


def tenant_por_slug(db: Session, slug: str) -> Tenant:
    # `tenants` é GLOBAL, sem RLS — o filtro explícito é a exceção documentada da Regra de
    # Ouro nº 1, a mesma do login.
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug.strip().lower()))
    if tenant is None:
        raise AdminError(f"Tenant não encontrado: {slug}")
    return tenant


def emitir_token(db: Session, *, slug: str, nome: str) -> tuple[MachineToken, str]:
    tenant = tenant_por_slug(db, slug)
    return machine_tokens_service.create_token(
        db, tenant_id=tenant.id, name=nome, scope=SCOPE_LEAD_INGEST
    )


def ler_funis(pares: list[str]) -> dict[str, str]:
    """`["lead=<id>", "renovacao="]` → `{"lead": "<id>", "renovacao": ""}` (`""` remove)."""
    funis: dict[str, str] = {}
    for par in pares:
        evento, separador, funil_id = par.partition("=")
        evento = evento.strip()
        if not separador:
            raise AdminError(f"Use evento=funil_id; recebi: {par}")
        if evento not in config.EVENTOS:
            raise AdminError(
                f"Evento desconhecido: {evento}. Válidos: {', '.join(config.EVENTOS)}"
            )
        funis[evento] = funil_id.strip()
    return funis


def configurar(
    tdb: Session, *, tenant_id: str, produto: str | None, funis: dict[str, str]
) -> dict:
    """Mescla na configuração atual e devolve a resultante.

    Nada é gravado se algo for inválido: o perfil só recebe o dicionário novo no fim.
    """
    perfil = settings_service.get_profile(tdb, tenant_id)
    atual = dict(perfil.lead_ingest_config or {})
    if produto is not None:
        try:
            atual["produto"] = config.validar_produto(produto)
        except ValueError as e:
            raise AdminError(str(e)) from e
    mapa = dict(atual.get("funis") or {})
    for evento, funil_id in funis.items():
        if not funil_id:
            mapa.pop(evento, None)
            continue
        # RLS: só enxerga funil DESTE tenant — um id de outro tenant cai aqui também.
        if tdb.get(Funnel, funil_id) is None:
            raise AdminError(f"Funil não encontrado neste tenant: {funil_id}")
        mapa[evento] = funil_id
    atual["funis"] = mapa
    # Dicionário NOVO, não mutação do antigo: coluna JSON sem MutableDict — o ORM só percebe
    # a mudança por atribuição.
    perfil.lead_ingest_config = atual
    audit.record(
        tdb, tenant_id=tenant_id, actor=ATOR, action="settings.lead_ingest.configure",
        target=perfil.id,
    )
    tdb.commit()
    return atual


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.lead_ingest_admin",
        description="Credencial e configuração da ingestão de leads (POST /public/ingest/leads).",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    emitir = sub.add_parser("emitir-token", help="Emite credencial lead_ingest (mostrada UMA vez).")
    emitir.add_argument("--tenant", required=True, help="slug do tenant")
    emitir.add_argument("--nome", required=True, help="quem usa (ex.: site nexuspublica.com.br)")

    listar = sub.add_parser("listar-tokens", help="Credenciais do tenant, ativas e revogadas.")
    listar.add_argument("--tenant", required=True, help="slug do tenant")

    revogar = sub.add_parser("revogar-token", help="Revoga uma credencial pelo id.")
    revogar.add_argument("--id", required=True, help="id da credencial (de listar-tokens)")

    configurar_cmd = sub.add_parser("configurar", help="Grava produto e/ou funil por evento.")
    configurar_cmd.add_argument("--tenant", required=True, help="slug do tenant")
    configurar_cmd.add_argument("--produto", default=None, help="slug do produto (ex.: publia)")
    configurar_cmd.add_argument(
        "--funil", action="append", default=[],
        help="evento=funnel_id (repetível; evento= remove o mapeamento)",
    )

    mostrar = sub.add_parser("mostrar", help="Mostra a configuração atual do tenant.")
    mostrar.add_argument("--tenant", required=True, help="slug do tenant")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.comando == "emitir-token":
            with _sessao_global() as db:
                token, raw = emitir_token(db, slug=args.tenant, nome=args.nome)
            print(f"Credencial {token.id} emitida para o tenant {token.tenant_id} "
                  f"({token.scope}).")
            print("Token (aparece só agora; guarde no cofre do site):")
            print(raw)
            return 0
        if args.comando == "listar-tokens":
            with _sessao_global() as db:
                tenant = tenant_por_slug(db, args.tenant)
                for t in machine_tokens_service.list_tokens(db, tenant_id=tenant.id):
                    situacao = "revogada" if t.revoked_at else "ativa"
                    print(f"{t.id}  {situacao:8}  {t.scope}  {t.name}  último uso: "
                          f"{t.last_used_at or 'nunca'}")
            return 0
        if args.comando == "revogar-token":
            with _sessao_global() as db:
                try:
                    token = machine_tokens_service.revoke(db, token_id=args.id)
                except machine_tokens_service.MachineTokenError as e:
                    raise AdminError(str(e)) from e
            print(f"Credencial {token.id} revogada em {token.revoked_at}.")
            return 0
        with _sessao_global() as db:
            tenant_id = tenant_por_slug(db, args.tenant).id
        with tenant_session(tenant_id) as tdb:
            if args.comando == "configurar":
                resultado = configurar(
                    tdb, tenant_id=tenant_id, produto=args.produto, funis=ler_funis(args.funil)
                )
            else:
                resultado = dict(settings_service.get_profile(tdb, tenant_id).lead_ingest_config)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0
    except AdminError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
