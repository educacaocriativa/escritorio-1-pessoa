"""Rotas do Assistente Jurídico: catálogo de skills, extração de anexos, geração e histórico."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.extract import extract_text
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.juridico import catalog, service
from app.modules.juridico.export import to_docx
from app.modules.juridico.models import LegalDocument
from app.modules.juridico.schemas import (
    DocumentCreate,
    DocumentOut,
    DocumentSummary,
    ExtractResult,
    SkillSummary,
)

router = APIRouter(prefix="/juridico", tags=["juridico"])

_guard = require_module("juridico")


def _err(e: service.JuridicoError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


def _out(doc: LegalDocument, db: Session) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        tenant_id=doc.tenant_id,
        skill=doc.skill,
        category=doc.category,
        title=doc.title,
        client_id=doc.client_id,
        client_name=service.client_name(db, doc.client_id),
        content=doc.content,
        metadata_raw=doc.metadata_raw,
        answers=doc.answers,
        input_tokens=doc.input_tokens,
        output_tokens=doc.output_tokens,
        status=doc.status,
        created_at=doc.created_at,
    )


@router.get("/skills", response_model=list[SkillSummary])
def list_skills(_u: CurrentUser = Depends(_guard)) -> list[SkillSummary]:
    return [SkillSummary(**s) for s in catalog.list_skills()]


@router.get("/skills/{skill}")
def get_skill(skill: str, _u: CurrentUser = Depends(_guard)) -> dict:
    cfg = catalog.get_config(skill)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Skill jurídica desconhecida")
    return cfg


@router.post("/extract", response_model=ExtractResult)
async def extract(
    file: UploadFile = File(...),
    _u: CurrentUser = Depends(_guard),
) -> ExtractResult:
    """Extrai o texto de uma peça enviada (PDF/Word/imagem/txt) — não persiste o arquivo."""
    data = await file.read()
    text = extract_text(data, file.content_type or "", file.filename or "")
    return ExtractResult(filename=file.filename or "arquivo", chars=len(text), text=text)


@router.post("/documents", response_model=DocumentOut, status_code=201)
def create_document(
    data: DocumentCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DocumentOut:
    try:
        doc = service.generate(
            db, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.JuridicoError as e:
        raise _err(e) from e
    return _out(doc, db)


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    client_id: str | None = Query(default=None),
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[DocumentSummary]:
    docs = service.list_documents(db, client_id=client_id)
    return [
        DocumentSummary(
            id=d.id,
            skill=d.skill,
            category=d.category,
            title=d.title,
            client_id=d.client_id,
            client_name=service.client_name(db, d.client_id),
            status=d.status,
            created_at=d.created_at,
        )
        for d in docs
    ]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: str,
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DocumentOut:
    try:
        return _out(service.get_document(db, document_id), db)
    except service.JuridicoError as e:
        raise _err(e) from e


@router.get("/documents/{document_id}/docx")
def download_docx(
    document_id: str,
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    try:
        doc = service.get_document(db, document_id)
    except service.JuridicoError as e:
        raise _err(e) from e
    blob = to_docx(title=doc.title, content=doc.content, metadata_raw=doc.metadata_raw)
    ascii_title = doc.title.encode("ascii", "ignore").decode()
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in ascii_title)[:60].strip()
    return Response(
        content=blob,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{safe or "documento"}.docx"'},
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    try:
        service.delete_document(
            db, document_id=document_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.JuridicoError as e:
        raise _err(e) from e
    return Response(status_code=204)
