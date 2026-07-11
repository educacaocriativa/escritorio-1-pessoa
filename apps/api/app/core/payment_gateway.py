"""Gateway de pagamento REAL (Asaas) — cria cobrança REGISTRADA (boleto/Pix) e devolve a linha
digitável / copia-e-cola reais + a URL do boleto bancário.

Padrão idêntico a `core/whatsapp.py` e `core/email.py`: função com contrato estável e
**graceful degradation**. Sem `payment_gateway_api_key` configurada, `is_configured()` devolve
False e o chamador (`receivables.service.build_charge`) mantém o comportamento atual — código
stub (`_payment_code`) + boleto layout-stub (`core/boleto.generate_boleto_pdf`). Isso vale
INCLUSIVE em produção (o gateway é opcional por decisão de produto, ao contrário de
JWT_SECRET/ANTHROPIC_API_KEY, que são bloqueantes).

⚠️ ATENÇÃO (No Invention): os endpoints/campos da API do Asaas usados aqui seguem a documentação
pública do provedor e DEVEM ser revalidados contra a documentação vigente e um ambiente sandbox
real antes do go-live. Nenhuma chamada real foi validada neste ambiente (sem credenciais). O
adapter é fail-safe: qualquer erro de rede/contrato levanta GatewayError e o chamador degrada
para o stub — a criação da cobrança NUNCA quebra por causa do gateway.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx

from app.config import settings

logger = logging.getLogger("e1p.payment_gateway")

PROVIDER_ASAAS = "asaas"

# Endpoint padrão do Asaas (produção). Sobrescreva com PAYMENT_GATEWAY_BASE_URL para o sandbox
# (ex.: https://api-sandbox.asaas.com/v3). Verificar contra a doc vigente antes do go-live.
_ASAAS_DEFAULT_BASE_URL = "https://api.asaas.com/v3"

_TIMEOUT = 15.0

# Mapa método interno -> billingType do Asaas.
_BILLING_TYPE = {
    "pix": "PIX",
    "boleto": "BOLETO",
    "card": "CREDIT_CARD",
}


class GatewayError(Exception):
    """Falha ao falar com o gateway. O chamador deve degradar para o stub (não propagar 500)."""


@dataclass
class GatewayChargeResult:
    """Resultado de uma cobrança registrada no gateway."""

    provider: str
    gateway_charge_id: str  # id da cobrança no provedor (auditoria/suporte)
    payment_code: str  # linha digitável (boleto) / copia-e-cola (Pix) / link (cartão)
    status: str  # status bruto do provedor (ex.: PENDING) — para debug/auditoria
    boleto_url: str | None = None  # URL do boleto bancário registrado (bankSlipUrl)


def _provider() -> str:
    return (settings.payment_gateway_provider or PROVIDER_ASAAS).strip().lower()


def is_configured() -> bool:
    """True apenas quando há chave E o provedor é suportado (hoje: Asaas)."""
    if not settings.payment_gateway_api_key:
        return False
    if _provider() != PROVIDER_ASAAS:
        logger.warning(
            "[payment_gateway] provider não suportado (%s) — usando stub", _provider()
        )
        return False
    return True


def _base_url() -> str:
    return (settings.payment_gateway_base_url or _ASAAS_DEFAULT_BASE_URL).rstrip("/")


def _headers() -> dict[str, str]:
    return {
        "access_token": settings.payment_gateway_api_key,
        "Content-Type": "application/json",
    }


def _reais(amount_cents: int) -> float:
    """Asaas trabalha em reais (float com 2 casas), não em centavos."""
    return round(amount_cents / 100, 2)


def create_registered_charge(
    *,
    method: str,
    amount_cents: int,
    due_date: date,
    payer_name: str,
    payer_document: str | None,
    external_reference: str,
) -> GatewayChargeResult:
    """Cria uma cobrança REGISTRADA no Asaas (boleto/Pix/cartão) e devolve o código de pagamento
    real + a URL do boleto.

    `external_reference` correlaciona o webhook de volta à nossa Charge — carrega
    `f"{tenant_id}:{charge_id}"` (ver receivables.service). NÃO expõe o tenant_id como chave
    previsível ao provedor além do próprio external_reference.

    Levanta GatewayError em qualquer falha (rede, contrato, documento ausente) — o chamador
    degrada para o stub sem quebrar a criação da cobrança.
    """
    billing_type = _BILLING_TYPE.get(method, "UNDEFINED")
    # Boleto/Pix registrados exigem o CPF/CNPJ do pagador para criar o cliente no Asaas.
    if not payer_document:
        raise GatewayError(
            "documento (CPF/CNPJ) do pagador ausente — cobrança registrada requer o documento"
        )
    try:
        with httpx.Client(base_url=_base_url(), headers=_headers(), timeout=_TIMEOUT) as http:
            customer_id = _ensure_customer(http, name=payer_name, document=payer_document)
            payment = _create_payment(
                http,
                customer_id=customer_id,
                billing_type=billing_type,
                amount_cents=amount_cents,
                due_date=due_date,
                external_reference=external_reference,
            )
            payment_id = payment["id"]
            code, boleto_url = _resolve_payment_code(http, method=method, payment=payment)
    except GatewayError:
        raise
    except httpx.HTTPError as exc:
        raise GatewayError(f"falha HTTP no gateway Asaas: {exc}") from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise GatewayError(f"resposta inesperada do gateway Asaas: {exc}") from exc

    return GatewayChargeResult(
        provider=PROVIDER_ASAAS,
        gateway_charge_id=payment_id,
        payment_code=code,
        status=str(payment.get("status") or "PENDING"),
        boleto_url=boleto_url,
    )


def _ensure_customer(http: httpx.Client, *, name: str, document: str) -> str:
    """Cria (ou reaproveita) o cliente no Asaas e devolve o id."""
    doc = "".join(ch for ch in document if ch.isdigit()) or document
    resp = http.post("/customers", json={"name": name or "Cliente", "cpfCnpj": doc})
    resp.raise_for_status()
    data = resp.json()
    customer_id = data.get("id")
    if not customer_id:
        raise GatewayError("Asaas não devolveu o id do cliente")
    return customer_id


def _create_payment(
    http: httpx.Client,
    *,
    customer_id: str,
    billing_type: str,
    amount_cents: int,
    due_date: date,
    external_reference: str,
) -> dict:
    payload = {
        "customer": customer_id,
        "billingType": billing_type,
        "value": _reais(amount_cents),
        "dueDate": due_date.isoformat(),
        "externalReference": external_reference,
    }
    resp = http.post("/payments", json=payload)
    resp.raise_for_status()
    return resp.json()


def _resolve_payment_code(
    http: httpx.Client, *, method: str, payment: dict
) -> tuple[str, str | None]:
    """Busca o código de pagamento real conforme o método. Devolve (payment_code, boleto_url)."""
    payment_id = payment["id"]
    if method == "boleto":
        resp = http.get(f"/payments/{payment_id}/identificationField")
        resp.raise_for_status()
        field = resp.json()
        code = field.get("identificationField") or field.get("barCode") or ""
        return code, payment.get("bankSlipUrl")
    if method == "pix":
        resp = http.get(f"/payments/{payment_id}/pixQrCode")
        resp.raise_for_status()
        qr = resp.json()
        return qr.get("payload") or "", None
    # cartão / outros: o link da fatura já serve como "código" de pagamento.
    return payment.get("invoiceUrl") or "", None
