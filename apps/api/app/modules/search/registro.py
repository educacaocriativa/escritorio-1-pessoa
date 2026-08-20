"""As entidades que a busca global enxerga — declarativas, num lugar só.

Acrescentar um tipo é acrescentar uma entrada. O que NÃO entra aqui: lista sem endereço que saiba
receber uma busca. Cobranças e produtos ficam de fora por isso — nenhuma das duas hidrata o recorte
a partir da URL, e mandar o clique para uma lista que ignora o filtro é pior que não oferecer o
resultado (spec §2). Contas a pagar SAIU dessa lista: o PR #143 (issue #138) fez `/pagar` hidratar
`q`, `status`, `de`/`ate`, `centro` e `categoria` do endereço, e por isso ela é a oitava entrada.

A ORDEM das entradas é a ordem dos grupos na tela: gente primeiro, depois o diálogo, depois
compromisso e dinheiro, depois o que se constrói. Ela mora aqui, e só aqui.

`modulo` não é decoração. A RLS garante que o tenant é o certo; ela NÃO garante que este usuário
pode ver este módulo — isso é `require_module`. Sem este campo, a busca seria a porta dos fundos do
RBAC: um sub-usuário sem acesso a Jurídico digitaria três letras e leria títulos de petição
(spec §6.4).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import quote as _percentualiza

from sqlalchemy import or_, select

from app.core.textsearch import ESCAPE
from app.modules.contracts.models import Contract
from app.modules.crm.models import Client
from app.modules.funnels.models import Funnel
from app.modules.juridico.models import LegalDocument
from app.modules.pages.models import Page
from app.modules.payables.models import Payable
from app.modules.quotes.models import Quote
from app.modules.whatsapp_inbox.models import WhatsappChat, WhatsappMessage


@dataclass(frozen=True)
class Entidade:
    """Uma linha do registro. Tudo que a busca precisa saber sobre um tipo."""

    tipo: str
    modelo: Any
    #: O mesmo nome que `require_module` usa nas rotas do módulo — copiar outro nome aqui
    #: criaria uma segunda definição de "pode ver", e as duas divergiriam.
    modulo: str
    campos_rasos: tuple
    campos_fundos: tuple
    #: A coluna que decide "prefixo vem antes de casamento no meio" na ordenação.
    principal: Any
    recencia: Any
    titulo: Callable[[Any], str]
    subtitulo: Callable[[Any], str]
    rota: Callable[[Any], str]
    #: Predicado alternativo, para quem casa por JOIN e não por coluna própria. Só `conversation`
    #: usa. Assinatura: `(padrao, escape, fundo, corte) -> ClauseElement`.
    predicado: Callable[[str, str, bool, datetime | None], Any] | None = field(default=None)


def _predicado_da_conversa(padrao: str, escape: str, fundo: bool, corte: datetime | None):
    """Conversa casa pelo título OU pelo cliente vinculado OU (na camada funda) pelas mensagens.

    `WhatsappChat.title` é nullable e curto: grupo sem assunto conhecido, `@lid` sem telefone. E
    `client_id` também é nullable — grupo não vira contato do CRM. Nenhum dos dois sozinho acha a
    conversa que o dono procura, então os dois entram.

    A subquery das mensagens devolve **chat_id**, não mensagens: é isso que faz quarenta mensagens
    casando virarem UMA linha em vez de afogarem os outros sete tipos com o mesmo diálogo repetido.
    """
    clientes = select(Client.id).where(Client.name.ilike(padrao, escape=escape))
    condicoes = [
        WhatsappChat.title.ilike(padrao, escape=escape),
        WhatsappChat.client_id.in_(clientes),
    ]
    if fundo:
        mensagens = select(WhatsappMessage.chat_id).where(
            WhatsappMessage.text_body.ilike(padrao, escape=escape)
        )
        # O recorte de meses vale SÓ aqui: mensagem é a única tabela cujo volume o justifica.
        if corte is not None:
            mensagens = mensagens.where(WhatsappMessage.created_at >= corte)
        condicoes.append(WhatsappChat.id.in_(mensagens))
    return or_(*condicoes)


def _titulo_da_conta(p) -> str:
    """A descrição é o rótulo da conta; sem ela, o fornecedor é quem a identifica.

    As duas colunas nascem `""` (não NULL), então o `or` encadeado é o teste certo — e o último
    degrau existe porque uma conta só de valor e vencimento ainda precisa de linha legível.
    """
    return p.description or p.supplier or "Conta a pagar"


def _subtitulo_da_conta(p) -> str:
    """O fornecedor, quando ele já não É o título. Repetir a mesma palavra em duas linhas não
    informa nada — nesse caso a categoria é o que diferencia duas contas do mesmo fornecedor."""
    return (p.supplier if p.description else "") or p.category


def _rota_da_conta(p) -> str:
    """`/pagar` filtrado NA CONTA encontrada — com o recorte padrão neutralizado de propósito.

    `q` sozinho não bastaria, e a spec §2 já tinha nomeado o motivo ao excluir Contas a Pagar:
    *"a visão padrão é `status ∈ (open, scheduled)` dentro do horizonte, então uma conta paga
    encontrada pela busca não estaria na tela para onde o clique levou"*. A busca não filtra por
    status nem por data; o destino não pode filtrar. Então:

    - `status=` (vazio) → `daUrl` devolve `[]`, que a tela lê como **todos os status**;
    - `ate=` (vazio)   → `daUrl` devolve `null`, que a tela lê como **sem horizonte**.

    Chave presente de valor vazio é o vocabulário que `filtros.ts` já usa para "escolhi vazio"
    (contra "não escolhi", que é chave ausente) — isto não inventa sintaxe, usa a que existe.

    O termo vem da LINHA, não da consulta: `rota` recebe o registro, e a descrição casa consigo
    mesma no `ilike` da lista (que escapa curinga pelo mesmo `padrao_ilike`), então o clique
    sempre aterrissa numa lista que contém a conta clicada.
    """
    termo = p.description or p.supplier or ""
    return f"/pagar?q={_percentualiza(termo, safe='')}&status=&ate="


REGISTRO: tuple[Entidade, ...] = (
    Entidade(
        tipo="client",
        modelo=Client,
        modulo="crm",
        campos_rasos=(Client.name, Client.email, Client.phone, Client.document),
        campos_fundos=(Client.notes,),
        principal=Client.name,
        recencia=Client.updated_at,
        titulo=lambda c: c.name,
        subtitulo=lambda c: c.email or c.phone or "",
        rota=lambda c: f"/crm/clients/{c.id}",
    ),
    Entidade(
        tipo="conversation",
        modelo=WhatsappChat,
        # A caixa de entrada do WhatsApp é guardada como CRM, não como módulo próprio
        # (`whatsapp_inbox/router.py:26`). Seguir o guard que já existe, não inventar outro.
        modulo="crm",
        campos_rasos=(WhatsappChat.title,),
        campos_fundos=(),
        principal=WhatsappChat.title,
        recencia=WhatsappChat.updated_at,
        titulo=lambda ch: ch.title or "Conversa sem nome",
        subtitulo=lambda ch: ch.chat_jid,
        rota=lambda ch: f"/conversas/{ch.id}",
        predicado=_predicado_da_conversa,
    ),
    Entidade(
        tipo="contract",
        modelo=Contract,
        modulo="contracts",
        campos_rasos=(Contract.title, Contract.signer_name),
        campos_fundos=(),
        principal=Contract.title,
        recencia=Contract.updated_at,
        titulo=lambda c: c.title,
        subtitulo=lambda c: c.signer_name or c.status,
        rota=lambda c: f"/contratos/{c.id}",
    ),
    Entidade(
        tipo="quote",
        modelo=Quote,
        modulo="quotes",
        campos_rasos=(Quote.title, Quote.client_name),
        campos_fundos=(Quote.notes,),
        principal=Quote.title,
        recencia=Quote.updated_at,
        titulo=lambda q: q.title,
        subtitulo=lambda q: q.client_name or q.status,
        rota=lambda q: f"/orcamentos/{q.id}",
    ),
    Entidade(
        tipo="payable",
        modelo=Payable,
        # O MESMO nome do guard das rotas do módulo (`payables/router.py:27`).
        modulo="payables",
        # Exatamente as duas colunas que o `q` da LISTA varre (`payables/service.py:355`). Casar
        # aqui por uma terceira coluna (categoria, por exemplo) devolveria um resultado que o
        # destino `/pagar?q=…` não mostraria — a armadilha do endereço inerte, por outra porta.
        campos_rasos=(Payable.description, Payable.supplier),
        # Boleto e código Pix não são prosa: ninguém procura uma conta digitando 44 dígitos, e
        # varrer `payment_code` na camada funda só somaria custo sem somar resposta.
        campos_fundos=(),
        principal=Payable.description,
        recencia=Payable.updated_at,
        titulo=_titulo_da_conta,
        subtitulo=_subtitulo_da_conta,
        rota=_rota_da_conta,
    ),
    Entidade(
        tipo="legal_document",
        modelo=LegalDocument,
        modulo="juridico",
        campos_rasos=(LegalDocument.title, LegalDocument.skill),
        campos_fundos=(LegalDocument.content,),
        principal=LegalDocument.title,
        recencia=LegalDocument.updated_at,
        titulo=lambda d: d.title,
        subtitulo=lambda d: d.skill,
        rota=lambda d: f"/juridico/{d.id}",
    ),
    Entidade(
        tipo="page",
        modelo=Page,
        modulo="pages",
        campos_rasos=(Page.title, Page.public_slug),
        campos_fundos=(),
        principal=Page.title,
        recencia=Page.updated_at,
        titulo=lambda p: p.title,
        subtitulo=lambda p: p.public_slug or p.status,
        rota=lambda p: f"/sites/{p.id}",
    ),
    Entidade(
        tipo="funnel",
        modelo=Funnel,
        modulo="funnels",
        campos_rasos=(Funnel.name,),
        campos_fundos=(),
        principal=Funnel.name,
        recencia=Funnel.updated_at,
        titulo=lambda f: f.name,
        subtitulo=lambda f: "",
        rota=lambda f: f"/funis/{f.id}",
    ),
)

__all__ = ["ESCAPE", "REGISTRO", "Entidade"]
