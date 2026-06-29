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


class FunnelError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


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
