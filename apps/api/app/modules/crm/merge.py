"""Mescla de contatos duplicados — o card absorvido some, o histórico não.

A PR #76 (`absorb_lead`) parou de CRIAR duplicados: as três portas de entrada passaram a
convergir por telefone normalizado. Os que já existiam ficaram, por decisão explícita do
fundador na época ("a correção vale daqui para frente"). Este módulo é a ferramenta que faltava.

**Por que a mescla precisa existir, e não só a prevenção:** o duplicado não é feio, é
funcional. No tenant do fundador havia SEIS "Flavio Kato" com o mesmo `phone_key`; o funil
inscreveu um deles (`source=api`, sem nenhuma conversa) enquanto a conversa real do WhatsApp
estava pendurada em outro (`source=whatsapp`). A mensagem foi enviada e entregue, e mesmo assim
não apareceu no fio — porque `get_timeline` mostra os avisos automáticos do
`chat.client_id`, e eram cards diferentes. Enquanto houver dois cards, qualquer coisa
ancorada em `client_id` conta metade da história.

**A regra que impede a mescla errada:** `phone_key` NÃO é único de propósito — marido e mulher
compartilham telefone (ver `crm/service._find_existing`). Agrupar só por telefone juntaria duas
PESSOAS num card só, que é pior que o problema. Por isso `find_duplicate_groups` exige também
nome equivalente, e nunca decide sozinha: propõe, e quem executa é uma chamada explícita.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.db.registry import Base
from app.modules.crm.models import Client

# Campos que o sobrevivente COMPLEMENTA a partir do absorvido quando estiver vazio. Mesma regra
# de `absorb_lead`: preenche buraco, nunca sobrescreve o que já tem valor.
_CAMPOS_COMPLEMENTAVEIS = ("email", "phone", "document", "gender", "birthdate")


def _chave_de_nome(nome: str | None) -> str:
    """Forma comparável do nome: sem acento, sem caixa, sem espaço repetido.

    Não é dedup por nome — é só o guarda que impede "Flavio Kato" e "Maria Kato" (mesmo
    telefone da casa) de virarem um contato só."""
    bruto = unicodedata.normalize("NFKD", nome or "")
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def tabelas_que_apontam_para_cliente() -> list[str]:
    """Toda tabela com coluna `client_id`, DESCOBERTA e não listada à mão.

    Mesmo motivo da purga dinâmica em `platform/service._business_table_names`: uma lista
    escrita à mão esquece o módulo seguinte, e aqui esquecer significa deixar cobrança, contrato
    ou conversa apontando para um card que acabou de ser apagado."""
    tabelas = {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if "client_id" in mapper.columns
    }
    return sorted(tabelas)


@dataclass
class GrupoDuplicado:
    phone_key: str
    nome: str
    sobrevivente: Client
    absorvidos: list[Client] = field(default_factory=list)


def find_duplicate_groups(db: Session) -> list[GrupoDuplicado]:
    """Grupos de cards que são a MESMA pessoa: mesmo telefone normalizado E mesmo nome.

    O sobrevivente é o MAIS ANTIGO (`created_at`, desempatando por `id`) — exatamente o critério
    de `crm/service._find_existing`. Tem que ser o mesmo: se divergisse, `absorb_lead` passaria a
    escolher um card e a mescla outro, e o próximo lead recriaria a divisão que esta função
    acabou de desfazer."""
    por_chave: dict[tuple[str, str], list[Client]] = {}
    for cliente in db.scalars(
        select(Client).where(Client.phone_key.is_not(None)).order_by(
            Client.created_at, Client.id
        )
    ).all():
        por_chave.setdefault((cliente.phone_key or "", _chave_de_nome(cliente.name)), []).append(
            cliente
        )
    return [
        GrupoDuplicado(
            phone_key=chave, nome=cards[0].name, sobrevivente=cards[0], absorvidos=cards[1:]
        )
        for (chave, _nome), cards in sorted(por_chave.items())
        if len(cards) > 1
    ]


def merge_clients(
    db: Session, *, tenant_id: str, actor: str, survivor_id: str, absorbed_ids: list[str]
) -> dict:
    """Repõe tudo que apontava para os absorvidos no sobrevivente e apaga os absorvidos.

    NÃO commita — quem chama decide, mesmo padrão de `receivables.build_charge`. Devolve o que
    foi movido, por tabela, para que o chamador possa relatar em vez de afirmar sucesso mudo.

    Ordem importa: repontar ANTES de apagar. O inverso deixaria órfãos por um instante e, se a
    transação falhasse no meio, o histórico apontaria para um card inexistente."""
    sobrevivente = db.get(Client, survivor_id)
    if sobrevivente is None:
        raise ValueError(f"contato sobrevivente {survivor_id} não encontrado")
    absorvidos = [c for c in (db.get(Client, cid) for cid in absorbed_ids) if c is not None]
    if not absorvidos:
        return {"movidos": {}, "absorvidos": 0}

    antigos = [c.id for c in absorvidos]
    movidos: dict[str, int] = {}
    for tabela in tabelas_que_apontam_para_cliente():
        resultado = db.execute(
            text(
                f"UPDATE {tabela} SET client_id = :novo "  # noqa: S608 — nome vem do registry
                "WHERE client_id IN :antigos"
            ).bindparams(
                # `expanding=True` é obrigatório num `IN` com lista: sem ele o SQLAlchemy manda a
                # tupla como UM parâmetro só e o banco recusa a query.
                bindparam("antigos", expanding=True),
            ),
            {"novo": survivor_id, "antigos": antigos},
        )
        if resultado.rowcount:
            movidos[tabela] = resultado.rowcount

    # Complementa buracos do sobrevivente (nunca sobrescreve) e junta as tags.
    for absorvido in absorvidos:
        for campo in _CAMPOS_COMPLEMENTAVEIS:
            if not getattr(sobrevivente, campo, None):
                valor = getattr(absorvido, campo, None)
                if valor:
                    setattr(sobrevivente, campo, valor)
        if absorvido.tags:
            sobrevivente.tags = sorted({*(sobrevivente.tags or []), *absorvido.tags})
        # Observação do dono é texto escrito à mão: perder seria pior que duplicar. Só entra o
        # que ainda não está lá, e sempre ANEXADO — nunca por cima.
        nota = (absorvido.notes or "").strip()
        if nota and nota not in (sobrevivente.notes or ""):
            atual = (sobrevivente.notes or "").rstrip()
            sobrevivente.notes = f"{atual}\n{nota}".strip() if atual else nota

    for absorvido in absorvidos:
        db.delete(absorvido)

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="crm.client.merge", target=survivor_id
    )
    return {"movidos": movidos, "absorvidos": len(absorvidos)}
