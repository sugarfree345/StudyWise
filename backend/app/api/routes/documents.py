from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.core.config import settings
from app.db import get_session
from app.models import Document
from app.services import pdf_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=Document, status_code=201)
async def upload_document(
    file: UploadFile, session: Session = Depends(get_session)
) -> Document:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    stored_path = settings.upload_dir / f"{uuid4().hex}.pdf"
    stored_path.write_bytes(await file.read())

    document = Document(
        filename=file.filename or stored_path.name,
        stored_path=str(stored_path),
        page_count=pdf_service.get_page_count(stored_path),
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


@router.get("", response_model=list[Document])
def list_documents(session: Session = Depends(get_session)) -> list[Document]:
    return list(session.exec(select(Document).order_by(Document.id.desc())).all())


@router.get("/{document_id}", response_model=Document)
def get_document(
    document_id: int, session: Session = Depends(get_session)
) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return document


@router.get("/{document_id}/file")
def get_document_file(
    document_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    document = get_document(document_id, session)
    return FileResponse(
        document.stored_path,
        media_type="application/pdf",
        filename=document.filename,
        content_disposition_type="inline",
    )
