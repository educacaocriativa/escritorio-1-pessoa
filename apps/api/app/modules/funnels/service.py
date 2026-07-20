"""Funil de Vendas: catálogo de componentes (paleta) + CRUD do grafo."""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.modules.funnels.models import Funnel
from app.modules.funnels.schemas import FunnelCreate, FunnelUpdate


def _i(key: str, label: str, description: str) -> dict:
    return {"key": key, "label": label, "description": description}


# Paleta de componentes do funil (fiel ao markdown do usuário).
CATALOG: list[dict] = [
    {
        "category": "gatilhos", "label": "Gatilhos", "color": "#3B82F6",
        "items": [
            _i("pagina-vendas", "Página de Vendas", "Página de vendas de alta conversão."),
            _i("pagina-captura", "Página de Captura", "Captura de novos leads e e-mails."),
            _i("pagina-obrigado", "Página de Obrigado", "Agradecimento após a conversão."),
            _i("obrigado-countdown", "Obrigado + Countdown",
               "Agradecimento com contagem regressiva."),
            _i("obrigado-video", "Obrigado + Vídeo", "Agradecimento com vídeo explicativo."),
            _i("pagina-download", "Página de Download", "Entrega de materiais e arquivos."),
            _i("checkout", "Checkout", "Gateway de checkout para pagamentos."),
            _i("area-membros", "Área de Membros", "Área de membros nativa da plataforma."),
            _i("aplicativo", "Aplicativo", "Visualizador mobile e app web do produto."),
            _i("modulo", "Módulo", "Módulo de conteúdo da área de membros."),
            _i("aula", "Aula", "Aula de vídeo, texto ou arquivo."),
            _i("live", "Live ao Vivo", "Evento de transmissão ao vivo."),
            _i("webinar", "Página de Webinar", "Inscrição ou acesso ao webinar."),
            _i("replay-webinar", "Replay de Webinar", "Página de replay do webinar gravado."),
            _i("lancamento", "Lançamento Tradicional", "Série de 4 aulas conectadas."),
            _i("agendar-reuniao", "Agendar Reunião", "Ação de agendamento de reunião."),
            _i("pagina-pedido", "Página de Pedido", "Página final para fechamento da compra."),
            _i("upsell", "Upsell", "Oferta adicional após a compra."),
            _i("downsell", "Downsell", "Oferta alternativa com valor reduzido."),
            _i("order-bump", "Order Bump", "Oferta complementar no checkout."),
            _i("pesquisa-seg", "Pesquisa", "Pesquisa inicial para segmentação."),
            _i("avaliacao", "Avaliação", "Bloco de avaliação e feedback."),
            _i("blog", "Blog", "Entrada de conteúdo em blog."),
            _i("ebook", "Ebook", "Entrega ou captação via ebook."),
            _i("certificado", "Certificado", "Entrega de certificado ao usuário."),
            _i("comunidade", "Comunidade", "Acesso a comunidade fechada."),
            _i("briefing", "Briefing", "Formulário ou etapa de briefing."),
            _i("webhook", "Webhook", "Dispara a partir de um webhook da plataforma."),
            _i("plataforma-vendas-g", "Plataforma de Vendas",
               "Dispara via integração de plataforma."),
        ],
    },
    {
        "category": "logica", "label": "Lógica", "color": "#F59E0B",
        "items": [
            _i("se-ou", "Se/Ou", "Condicional de decisão entre caminhos."),
            _i("play", "Play", "Disparo lógico de execução."),
        ],
    },
    {
        "category": "acoes", "label": "Ações", "color": "#10B981",
        "items": [
            _i("lead", "Lead", "Marcação ou criação de lead."),
            _i("compra", "Compra", "Registro de evento de compra."),
            _i("trafego-pago", "Tráfego Pago", "Ação de campanha paga."),
            _i("remarketing", "Remarketing", "Ação de retargeting para audiência."),
            _i("audiencia", "Audiência", "Atualiza audiência alvo."),
            _i("tag", "Tag", "Aplica ou remove tags de contato."),
            _i("add-crm", "Adicionado ao CRM", "Move ou cria contato no CRM."),
            _i("esperar", "Esperar", "Configura atraso para continuar a automação."),
            _i("carrinho-abandonado", "Carrinho Abandonado", "Detecta abandono de carrinho."),
            _i("recuperacao", "Recuperação", "Fluxo de recuperação de venda."),
            _i("reembolso", "Reembolso", "Disparo em caso de reembolso."),
            _i("follow-up", "Follow-up", "Seguimento com cliente ou lead."),
            _i("reuniao-online", "Reunião Online", "Reunião remota com clientes ou leads."),
            _i("reuniao-presencial", "Reunião Presencial", "Encontro presencial com cliente."),
            _i("clique", "Clique", "Evento de clique em link ou botão."),
            _i("envio-arquivo", "Envio de Arquivo", "Entrega de arquivo ao contato."),
            _i("dm-instagram", "DM Instagram", "Envio de mensagem direta no Instagram."),
            _i("automacao", "Automação", "Entrada em fluxo de automação."),
            _i("manychat", "Manychat", "Integração com fluxo do Manychat."),
            _i("emissao-proposta", "Emissão de Proposta", "Gera proposta comercial."),
            _i("emissao-boleto", "Emissão de Boleto", "Gera boleto de pagamento."),
            _i("gerou-pix", "Gerou Pix", "Evento de geração de Pix."),
            _i("nota-fiscal", "Nota Fiscal", "Emissão de nota fiscal."),
        ],
    },
    {
        "category": "comunicacao", "label": "Comunicação", "color": "#8B5CF6",
        "items": [
            _i("email-base", "E-mail (Base)", "Base de comunicação por e-mail."),
            _i("enviar-email", "Enviar E-mail", "Disparo de e-mail único."),
            _i("sequencia-email", "Sequência de E-mail", "Conjunto conectado de e-mails."),
            _i("whatsapp", "WhatsApp", "Mensagem de WhatsApp única."),
            _i("sequencia-whatsapp", "Sequência de WhatsApp", "Mensagens conectadas no WhatsApp."),
            _i("criativo", "Criativo", "Bloco de criativo para campanha."),
        ],
    },
    {
        "category": "trafego", "label": "Tráfego", "color": "#EC4899",
        "items": [
            _i("instagram-base", "Instagram (Base)", "Canal base de Instagram."),
            _i("instagram-pago", "Instagram (Pago)", "Campanha paga no Instagram."),
            _i("perfil-instagram", "Perfil Instagram", "Link para perfil do Instagram."),
            _i("post-instagram", "Post Instagram", "Publicação no feed do Instagram."),
            _i("carrossel-instagram", "Carrossel Instagram", "Criativo de carrossel no Instagram."),
            _i("story-instagram", "Story Instagram", "Criativo de stories no Instagram."),
            _i("youtube", "YouTube", "Canal ou campanha no YouTube."),
            _i("active-campaign", "Active Campaign", "Integração com Active Campaign."),
            _i("stripe", "Stripe", "Integração com Stripe."),
            _i("supabase", "Supabase", "Integração com Supabase."),
            _i("shopify", "Shopify", "Integração com Shopify."),
            _i("mailchimp", "Mailchimp", "Integração com Mailchimp."),
            _i("wordpress", "WordPress", "Integração com WordPress."),
            _i("tiktok", "TikTok", "Canal de tráfego no TikTok."),
            _i("telegram", "Telegram", "Canal de tráfego no Telegram."),
            _i("ligacao", "Ligação", "Contato por chamada telefônica."),
            _i("sms", "SMS", "Contato por mensagem SMS."),
            _i("pesquisa", "Pesquisa", "Origem de busca e pesquisa."),
            _i("pinterest", "Pinterest", "Canal de tráfego no Pinterest."),
            _i("google", "Google", "Canal de tráfego do Google."),
            _i("meta-ads", "Meta Ads", "Campanhas na rede Meta Ads."),
            _i("pixel-meta", "Pixel Meta", "Monitoramento via Pixel Meta."),
            _i("google-analytics", "Google Analytics", "Análise de dados via GA."),
            _i("linkedin", "LinkedIn", "Canal de tráfego no LinkedIn."),
            _i("google-meet", "Google Meet", "Reuniões pelo Google Meet."),
            _i("zoom", "Zoom", "Reuniões pelo Zoom."),
            _i("google-meu-negocio", "Google Meu Negócio", "Presença no Google Meu Negócio."),
            _i("substack", "Substack", "Canal de newsletter no Substack."),
        ],
    },
]


# Componentes que são "páginas" (renderizados quadrados, com mockup de página no front).
# Os demais são "nós" redondos (ações/lógica/comunicação/tráfego e gatilhos de evento).
PAGE_KEYS = {
    "pagina-vendas", "pagina-captura", "pagina-obrigado", "obrigado-countdown", "obrigado-video",
    "pagina-download", "checkout", "area-membros", "aplicativo", "modulo", "aula", "webinar",
    "replay-webinar", "lancamento", "pagina-pedido", "upsell", "downsell", "order-bump",
    "pesquisa-seg", "avaliacao", "blog", "ebook", "certificado", "comunidade", "briefing",
}

# Componentes que EXECUTAM uma ação interna de verdade (sem integração externa).
ACTION_BY_KEY = {
    "lead": "create_client",
    "add-crm": "create_client",
    "tag": "add_tag",
    "emissao-proposta": "create_quote",
    "emissao-boleto": "create_charge",
    "gerou-pix": "create_charge",
    "enviar-email": "send_email",
    "sequencia-email": "send_email",
    "email-base": "send_email",
    "whatsapp": "send_message",
    "sequencia-whatsapp": "send_message",
    "dm-instagram": "send_message",
    "telegram": "send_message",
    "manychat": "send_message",
    "sms": "send_message",
}

for _cat in CATALOG:
    for _item in _cat["items"]:
        _item["shape"] = "page" if _item["key"] in PAGE_KEYS else "node"
        _item["action"] = ACTION_BY_KEY.get(_item["key"], "")


class FunnelError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ── WhatsApp/E-mail: resolução de placeholders ({{cliente.*}} ou texto literal) ──
_CLIENT_KEYWORDS = {
    "cliente.nome": lambda c: c.name,
    "cliente.telefone": lambda c: c.phone or "",
    "cliente.email": lambda c: c.email or "",
    # Bloco de Observações do lead — já traz as respostas de campos customizados de
    # formulários (Sites/Integrações), sem precisar de uma keyword por campo (que varia
    # de página pra página).
    "cliente.notas": lambda c: c.notes or "",
}
_KEYWORD_PATTERN = re.compile(r"\{\{\s*(cliente\.\w+)\s*\}\}")


def _resolve_template_variable(raw: str, client) -> str:
    if raw.startswith("{{") and raw.endswith("}}"):
        key = raw[2:-2].strip()
        resolver = _CLIENT_KEYWORDS.get(key)
        if resolver is not None:
            return resolver(client) or ""
    return raw  # texto fixo, literal


def _render_client_placeholders(text: str, client) -> str:
    """Substitui `{{cliente.*}}` NO MEIO de um texto livre (assunto/corpo de e-mail) — ao
    contrário de `_resolve_template_variable` (variável posicional inteira do WhatsApp), aqui
    o placeholder pode aparecer misturado com texto fixo."""

    def _sub(m: re.Match[str]) -> str:
        resolver = _CLIENT_KEYWORDS.get(m.group(1))
        return (resolver(client) or "") if resolver else m.group(0)

    return _KEYWORD_PATTERN.sub(_sub, text)


def _render_template_preview(body_text: str, variables: list[str]) -> str:
    """Substitui {{1}}, {{2}}, ... no corpo do template pelos valores já resolvidos."""
    rendered = body_text
    for i, value in enumerate(variables, start=1):
        rendered = rendered.replace(f"{{{{{i}}}}}", value)
    return rendered


# ── IA: compõe o conteúdo de um nó (e-mail / mensagem / texto) ──────────────
_COMPOSE_SYSTEM = {
    "email": (
        "Você é redator de e-mail marketing (pt-BR). Escreva um e-mail curto e persuasivo. "
        "Responda APENAS com JSON {\"subject\": \"...\", \"body\": \"...\"}. Assunto curto."
    ),
    "whatsapp": (
        "Você escreve mensagens de WhatsApp (pt-BR), curtas, calorosas e diretas, com 1 emoji. "
        "Responda APENAS com JSON {\"body\": \"...\"}."
    ),
    "sms": (
        "Você escreve SMS (pt-BR) com no máximo 160 caracteres, direto ao ponto. "
        "Responda APENAS com JSON {\"body\": \"...\"}."
    ),
    "generic": (
        "Você escreve um texto curto e claro (pt-BR) para esta etapa de um funil de vendas. "
        "Responda APENAS com JSON {\"body\": \"...\"}."
    ),
}


def _compose_fallback(kind: str, prompt: str) -> dict:
    if kind == "email":
        return {"subject": prompt.strip()[:60], "body": f"Olá!\n\nSobre {prompt}.\n\nAbraço."}
    return {"subject": "", "body": f"Sobre {prompt}."}


def ai_compose(kind: str, prompt: str) -> dict:
    """Gera o conteúdo do nó com IA; cai para um rascunho simples sem chave/parsing."""
    system = _COMPOSE_SYSTEM.get(kind, _COMPOSE_SYSTEM["generic"])
    if not settings.anthropic_api_key:
        return _compose_fallback(kind, prompt)
    try:
        text = ai.complete(system=system, user_message=prompt, max_tokens=800).text
        cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        data = json.loads(cleaned)
        return {
            "subject": str(data.get("subject", ""))[:200],
            "body": str(data.get("body", ""))[:4000],
        }
    except Exception:
        return _compose_fallback(kind, prompt)


def create_funnel(db: Session, *, tenant_id: str, actor: str, data: FunnelCreate) -> Funnel:
    funnel = Funnel(tenant_id=tenant_id, name=data.name, nodes=data.nodes, edges=data.edges)
    db.add(funnel)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.create", target=funnel.id)
    db.commit()
    db.refresh(funnel)
    return funnel


def get_funnel(db: Session, funnel_id: str) -> Funnel:
    f = db.get(Funnel, funnel_id)
    if f is None:
        raise FunnelError("Funil não encontrado", 404)
    return f


def list_funnels(db: Session) -> list[Funnel]:
    return list(db.scalars(select(Funnel).order_by(Funnel.created_at.desc())).all())


def update_funnel(
    db: Session, *, funnel_id: str, tenant_id: str, actor: str, data: FunnelUpdate
) -> Funnel:
    f = get_funnel(db, funnel_id)
    if data.name is not None:
        f.name = data.name
    if data.nodes is not None:
        f.nodes = data.nodes
    if data.edges is not None:
        f.edges = data.edges
    audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.update", target=f.id)
    db.commit()
    db.refresh(f)
    return f


def delete_funnel(db: Session, *, funnel_id: str, tenant_id: str, actor: str) -> None:
    f = get_funnel(db, funnel_id)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.delete", target=f.id)
    db.delete(f)
    db.commit()


# ── Execução de um nó: dispara a AÇÃO REAL interna (CRM/Proposta/Cobrança/Mensagem) ──
MAX_CENTS = 100_000_000_00  # teto defensivo: R$ 100 milhões (evita estouro/valor absurdo)


def _cents(params: dict) -> int:
    try:
        return int(params.get("amount_cents") or 0)
    except (TypeError, ValueError):
        return 0


def _valid_amount(params: dict) -> int:
    amount = _cents(params)
    if amount <= 0 or amount > MAX_CENTS:
        raise FunnelError("Informe um valor válido (acima de zero e abaixo do limite)", 422)
    return amount


def run_node(
    db: Session, *, tenant_id: str, actor: str, action: str, client_id: str | None, params: dict
) -> dict:
    from datetime import UTC, datetime, timedelta

    from app.core import email, whatsapp
    from app.modules.auth.models import User
    from app.modules.crm import service as crm_service
    from app.modules.crm.models import Client
    from app.modules.crm.schemas import ClientCreate
    from app.modules.notifications.models import Notification
    from app.modules.quotes import service as quotes_service
    from app.modules.quotes.schemas import QuoteCreate, QuoteItem
    from app.modules.receivables import service as receivables_service
    from app.modules.receivables.schemas import ChargeCreate
    from app.modules.settings import service as settings_service
    from app.modules.whatsapp_templates.models import STATUS_APPROVED, WhatsappTemplate

    def _client() -> Client:
        c = db.get(Client, client_id) if client_id else None
        if c is None:
            raise FunnelError("Selecione um cliente para executar esta ação", 422)
        return c

    def _team_owner() -> User | None:
        return db.scalar(select(User).where(User.tenant_id == tenant_id, User.role == "owner"))

    def _team_email() -> str:
        """E-mail da equipe (nó com destinatário="team"): TenantProfile.email → User.email
        do owner (fallback — sempre existe, garante que o nó funcione mesmo sem configurar)."""
        profile = settings_service.get_profile(db, tenant_id)
        if profile.email:
            return profile.email
        owner = _team_owner()
        return owner.email if owner else ""

    def _team_phone() -> str:
        """Telefone da equipe (nó com destinatário="team"): TenantProfile.phone → User.phone
        do owner."""
        profile = settings_service.get_profile(db, tenant_id)
        if profile.phone:
            return profile.phone
        owner = _team_owner()
        return (owner.phone or "") if owner else ""

    if action == "create_client":
        name = (params.get("name") or "").strip()
        if not name:
            raise FunnelError("Informe o nome do contato", 422)
        c = crm_service.create_client(
            db, tenant_id=tenant_id, actor=actor, data=ClientCreate(name=name)
        )
        return {"message": f"Contato “{name}” criado no CRM", "kind": "client", "ref_id": c.id}

    if action == "add_tag":
        c = _client()
        tag = (params.get("tag") or "").strip()
        if not tag:
            raise FunnelError("Informe a tag", 422)
        if tag not in c.tags:
            c.tags = [*c.tags, tag]
        audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.run.tag", target=c.id)
        db.commit()
        return {"message": f"Tag “{tag}” aplicada a {c.name}", "kind": "client", "ref_id": c.id}

    if action == "create_quote":
        c = _client()
        amount = _valid_amount(params)
        title = (params.get("title") or "Proposta").strip()
        q = quotes_service.create_quote(
            db, tenant_id=tenant_id, actor=actor,
            data=QuoteCreate(
                client_id=c.id, title=title,
                items=[QuoteItem(description=title, quantity=1, unit_price_cents=amount)],
            ),
        )
        return {"message": f"Orçamento “{title}” criado para {c.name}", "kind": "quote",
                "ref_id": q.id}

    if action == "create_charge":
        c = _client()
        amount = _valid_amount(params)
        method = params.get("method") if params.get("method") in {"boleto", "pix"} else "boleto"
        desc = (params.get("description") or "Cobrança do funil").strip()
        ch = receivables_service.create_charge(
            db, tenant_id=tenant_id, actor=actor,
            data=ChargeCreate(
                client_id=c.id, description=desc, kind="service", method=method,
                amount_cents=amount, due_date=datetime.now(UTC).date() + timedelta(days=7),
            ),
        )
        return {"message": f"Cobrança ({method}) criada para {c.name}", "kind": "charge",
                "ref_id": ch.id}

    if action == "send_email":
        c = _client()
        msg = (params.get("message") or "").strip()
        if not msg:
            raise FunnelError("Escreva a mensagem (ou gere com IA) antes de enviar", 422)
        to_team = params.get("recipient") == "team"
        recipient = _team_email() if to_team else (c.email or c.name)
        subject = _render_client_placeholders((params.get("subject") or "Mensagem").strip(), c)
        msg = _render_client_placeholders(msg, c)
        status = email.send_email(to=recipient, subject=subject, body=msg)
        db.add(Notification(
            tenant_id=tenant_id, channel="email", recipient=recipient,
            client_id=c.id, message=msg, status=status,
        ))
        audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.run.message", target=c.id)
        db.commit()
        who = "equipe" if to_team else c.name
        return {"message": f"Mensagem registrada para {who} (email)", "kind": "message",
                "ref_id": c.id}

    if action == "send_message":
        c = _client()
        template_id = params.get("template_id")
        if not template_id:
            raise FunnelError("Selecione um template de WhatsApp aprovado", 422)
        tpl = db.get(WhatsappTemplate, template_id)
        if tpl is None or tpl.status != STATUS_APPROVED:
            raise FunnelError("Template não encontrado ou ainda não aprovado pela Meta", 422)
        to_team = params.get("recipient") == "team"
        to_phone = _team_phone() if to_team else (c.phone or "")
        recipient = to_phone or c.name
        resolved_vars = [_resolve_template_variable(v, c) for v in (params.get("variables") or [])]
        profile = settings_service.get_profile(db, tenant_id)
        status = whatsapp.send_template(
            to=to_phone, token=profile.whatsapp_token or "",
            phone_id=profile.whatsapp_phone_id or "",
            template_name=tpl.name, language=tpl.language, variables=resolved_vars,
        )
        rendered = _render_template_preview(tpl.body_text, resolved_vars)
        db.add(Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=c.id, message=rendered, status=status,
        ))
        audit.record(db, tenant_id=tenant_id, actor=actor, action="funnel.run.message", target=c.id)
        db.commit()
        who = "equipe" if to_team else c.name
        return {"message": f"Mensagem registrada para {who} (whatsapp)", "kind": "message",
                "ref_id": c.id}

    raise FunnelError("Este componente ainda não executa uma ação automática", 400)
