"""Testes da resolução de tenant por subdomínio (Story 4.4, Task 3).

Cobre a função pura `extract_tenant_slug` (sem necessidade de banco). O núcleo de segurança
desta story é essa função de parsing + a garantia de que o slug do Host NUNCA vira fonte de
RLS (isso é validado por revisão de código/quality gate, não por teste — ver Dev Notes).
"""
from app.core.subdomain import extract_tenant_slug

ROOT = "e1p.com"


def test_valid_subdomain_returns_slug():
    assert extract_tenant_slug("joaosilva.e1p.com", ROOT) == "joaosilva"


def test_root_domain_exact_returns_none():
    # Domínio único (IV1/IV3): Host não bate no wildcard → None (comportamento atual).
    assert extract_tenant_slug("e1p.com", ROOT) is None


def test_www_returns_none():
    assert extract_tenant_slug("www.e1p.com", ROOT) is None


def test_host_with_port_strips_port():
    # Cenário de dev local (`slug.e1p.com:8000`).
    assert extract_tenant_slug("joaosilva.e1p.com:8000", ROOT) == "joaosilva"


def test_different_domain_returns_none():
    assert extract_tenant_slug("outrapagina.com", ROOT) is None


def test_nested_subdomain_takes_first_label():
    # Escolha simples: primeiro rótulo. O produto não suporta subdomínios aninhados.
    assert extract_tenant_slug("a.b.e1p.com", ROOT) == "a"


def test_case_insensitive_host():
    assert extract_tenant_slug("JoaoSilva.E1P.Com", ROOT) == "joaosilva"


def test_uppercase_root_domain():
    assert extract_tenant_slug("joaosilva.e1p.com", "E1P.COM") == "joaosilva"


def test_empty_host_returns_none():
    assert extract_tenant_slug("", ROOT) is None


def test_empty_root_domain_returns_none():
    assert extract_tenant_slug("joaosilva.e1p.com", "") is None


def test_root_domain_with_trailing_dot():
    # FQDN com ponto final não deve quebrar a comparação.
    assert extract_tenant_slug("joaosilva.e1p.com", "e1p.com.") == "joaosilva"


def test_similar_but_not_subdomain_returns_none():
    # `note1p.com` termina em `1p.com` mas NÃO em `.e1p.com` — não é subdomínio.
    assert extract_tenant_slug("note1p.com", ROOT) is None
