"""Assistente Jurídico: gera documentos jurídicos por IA a partir das skills + CRUD.

Fluxo da geração:
  1. carrega o SKILL.md da skill como prompt-sistema (+ protocolo anti-alucinação);
  2. monta a mensagem do usuário com as respostas do formulário e o texto dos anexos;
  3. ANONIMIZA tudo (PII / segredo de justiça) antes de enviar ao Claude;
  4. desanonimiza a resposta localmente e separa o corpo do documento da seção METADADOS;
  5. persiste o LegalDocument (RLS por tenant).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import audit
from app.core.ai import complete
from app.core.anonymizer import anonymizer
from app.modules.auth.models import User
from app.modules.crm.models import Client
from app.modules.juridico import catalog
from app.modules.juridico.models import STATUS_FAILED, STATUS_READY, LegalDocument
from app.modules.juridico.schemas import DocumentCreate

_METADATA_MARKER = "### METADADOS PARA RELATÓRIO"

_ANTI_HALLUCINATION = """

## PROTOCOLO ANTI-ALUCINAÇÃO (OBRIGATÓRIO)

Toda citação de jurisprudência deve ser classificada em 3 níveis:
- **NÍVEL 1 — CONFIRMADO:** Súmula vinculante, Tema Repetitivo ou ADPF com número verificável
- **NÍVEL 2 — PROVÁVEL:** jurisprudência conhecida sem número confirmado — marcar [VERIFICAR]
- **NÍVEL 3 — INCERTO:** tendência sem precedente específico — usar linguagem genérica

**NUNCA** invente números de REsp, AI, HC, Súmulas ou nomes de relatores.

O texto pode conter variáveis como [CPF_1], [EMAIL_1], [FONE_1] — são dados reais mascarados por
segurança. Trate-as como referências válidas e mantenha-as exatamente como estão na resposta.

## ESTRUTURA DO OUTPUT

Ao final do documento gerado, inclua uma seção:
### METADADOS PARA RELATÓRIO
- Skills utilizadas: [liste as skills ativas]
- Frameworks aplicados: [FIRAC-JB / CAPPD / 3 Níveis / etc.]
- Jurisprudências citadas: [lista com NÍVEL de cada uma]
- Avisos de revisão: [pontos que o advogado deve verificar]
"""


class JuridicoError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _build_user_message(skill: str, answers: dict, extracted: str, author: str) -> str:
    cfg = catalog.get_config(skill)
    # labels amigáveis para cada campo (cai para o próprio key)
    labels: dict[str, str] = {}
    for step in (cfg or {}).get("steps", []):
        for field in step.get("fields", []):
            labels[field["key"]] = field.get("label", field["key"])

    parts = [f"**Profissional:** {author}", "", "## Respostas do Formulário"]
    for key, value in answers.items():
        if value in (None, "", [], {}):
            continue
        label = labels.get(key, key.replace("_", " ").title())
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        parts.append(f"**{label}:** {value}")

    if extracted.strip():
        parts += ["", "## Documentos Enviados (texto extraído)", extracted[:50000]]

    parts += [
        "",
        "Gere o documento jurídico completo com base nas informações acima, seguindo "
        "rigorosamente as instruções da skill e o protocolo anti-alucinação.",
    ]
    return "\n".join(parts)


def _title_for(skill: str, answers: dict) -> str:
    cfg = catalog.get_config(skill)
    label = (cfg or {}).get("label", skill)
    # tenta um identificador útil (número do processo, título, nome) entre as respostas
    for k in ("numero_processo", "titulo", "tema", "nome", "assunto"):
        v = answers.get(k)
        if v:
            return f"{label} — {str(v)[:80]}"
    return label


def generate(db: Session, *, tenant_id: str, actor: str, data: DocumentCreate) -> LegalDocument:
    cfg = catalog.get_config(data.skill)
    if cfg is None:
        raise JuridicoError("Skill jurídica desconhecida", 404)
    if data.client_id and db.get(Client, data.client_id) is None:
        raise JuridicoError("Cliente não encontrado", 404)

    user = db.get(User, actor)
    author = user.name if user else "Profissional"

    skill_md = catalog.skill_prompt(data.skill) or (
        f"# Skill: {data.skill}\nGere um documento jurídico profissional, claro e fundamentado."
    )
    system_prompt = skill_md + _ANTI_HALLUCINATION
    user_message = _build_user_message(data.skill, data.answers, data.extracted_text, author)

    # Regra de Ouro: anonimiza ANTES de enviar; desanonimiza a resposta localmente.
    safe_message, mapping = anonymizer.mask(user_message)

    doc = LegalDocument(
        tenant_id=tenant_id,
        skill=data.skill,
        category=cfg.get("category", "core"),
        title=_title_for(data.skill, data.answers),
        client_id=data.client_id,
        answers=data.answers,
    )

    if not settings.anthropic_api_key:
        doc.content = (
            "_Geração por IA indisponível (ANTHROPIC_API_KEY não configurada). "
            "Documento não gerado — configure a chave para usar o Assistente Jurídico._"
        )
        doc.status = STATUS_FAILED
        db.add(doc)
        audit.record(db, tenant_id=tenant_id, actor=actor, action="legal.generate.skipped",
                     target=doc.id)
        db.commit()
        db.refresh(doc)
        return doc

    try:
        result = complete(system=system_prompt, user_message=safe_message, max_tokens=8192)
    except Exception as e:  # noqa: BLE001
        raise JuridicoError(f"Falha na geração por IA: {e}", 502) from e

    full_text = anonymizer.unmask(result.text, mapping)
    if _METADATA_MARKER in full_text:
        body, meta = full_text.split(_METADATA_MARKER, 1)
        doc.content = body.strip()
        doc.metadata_raw = meta.strip()
    else:
        doc.content = full_text.strip()

    doc.input_tokens = result.input_tokens
    doc.output_tokens = result.output_tokens
    doc.status = STATUS_READY

    db.add(doc)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="legal.generate", target=doc.id)
    db.commit()
    db.refresh(doc)
    return doc


def list_documents(db: Session, *, client_id: str | None = None) -> list[LegalDocument]:
    stmt = select(LegalDocument).order_by(LegalDocument.created_at.desc())
    if client_id:
        stmt = stmt.where(LegalDocument.client_id == client_id)
    return list(db.scalars(stmt).all())


def get_document(db: Session, document_id: str) -> LegalDocument:
    doc = db.get(LegalDocument, document_id)
    if doc is None:
        raise JuridicoError("Documento não encontrado", 404)
    return doc


def delete_document(db: Session, *, document_id: str, tenant_id: str, actor: str) -> None:
    doc = get_document(db, document_id)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="legal.delete", target=doc.id)
    db.delete(doc)
    db.commit()


def client_name(db: Session, client_id: str | None) -> str | None:
    if not client_id:
        return None
    c = db.get(Client, client_id)
    return c.name if c else None
