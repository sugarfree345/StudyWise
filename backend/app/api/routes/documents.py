from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.core.config import settings
from app.db import get_session
from app.models import Document, DocumentPage, DocumentProcessing, ImageAsset, Project
from app.schemas.document import DocumentRead, DocumentUpdate
from app.services.document_processing import document_processing_manager
from app.services.page_content_store import page_content_store

router = APIRouter(prefix="/documents", tags=["documents"])


def _read_document(
    document: Document, session: Session, *, create_processing: bool = True
) -> DocumentRead:
    if document.id is None:
        raise RuntimeError("文档尚未持久化")
    processing = session.get(DocumentProcessing, document.id)
    if processing is None:
        if not create_processing:
            raise RuntimeError("文档解析状态不存在")
        processing = DocumentProcessing(document_id=document.id)
        session.add(processing)
        session.commit()
        session.refresh(processing)
    return DocumentRead.from_models(document, processing)


@router.post("", response_model=DocumentRead, status_code=201)
async def upload_document(
    file: UploadFile, session: Session = Depends(get_session)
) -> DocumentRead:
    return await save_uploaded_document(file, 1, session)


async def save_uploaded_document(
    file: UploadFile, project_id: int, session: Session
) -> DocumentRead:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    stored_path = settings.upload_dir / f"{uuid4().hex}.pdf"
    try:
        size = 0
        with stored_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                output.write(chunk)
        if size == 0:
            raise ValueError("文件为空")
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"PDF 无法保存：{exc}") from exc

    document = Document(
        project_id=project_id,
        filename=file.filename or stored_path.name,
        stored_path=str(stored_path),
        page_count=0,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    if document.id is None:
        raise RuntimeError("文档创建失败")
    processing = DocumentProcessing(document_id=document.id)
    session.add(processing)
    session.commit()
    session.refresh(processing)
    await document_processing_manager.enqueue(document.id)
    return DocumentRead.from_models(document, processing)


@router.get("", response_model=list[DocumentRead])
def list_documents(session: Session = Depends(get_session)) -> list[DocumentRead]:
    documents = session.exec(select(Document).order_by(Document.id.desc())).all()
    return [_read_document(document, session) for document in documents]


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: int, session: Session = Depends(get_session)
) -> DocumentRead:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _read_document(document, session)


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: int,
    body: DocumentUpdate,
    session: Session = Depends(get_session),
) -> DocumentRead:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(document, field, value)
    document.updated_at = datetime.now(timezone.utc)
    session.add(document)
    session.commit()
    session.refresh(document)
    return _read_document(document, session)


@router.post("/{document_id}/reparse", response_model=DocumentRead)
async def reparse_document(
    document_id: int, session: Session = Depends(get_session)
) -> DocumentRead:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    processing = session.get(DocumentProcessing, document_id)
    if processing is None:
        processing = DocumentProcessing(document_id=document_id)
    if processing.status == "processing":
        raise HTTPException(status_code=409, detail="文档正在解析")
    processing.status = "pending"
    processing.processed_pages = 0
    processing.error_message = None
    processing.paddle_job_id = None
    processing.started_at = None
    processing.completed_at = None
    session.add(processing)
    session.commit()
    session.refresh(processing)
    await document_processing_manager.enqueue(document_id)
    return DocumentRead.from_models(document, processing)


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: int, session: Session = Depends(get_session)
) -> Response:
    """删除文档：清掉数据库里的页/图/处理状态与文档记录，并删除源文件和解析产物。"""
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    for image in session.exec(
        select(ImageAsset).where(ImageAsset.document_id == document_id)
    ).all():
        session.delete(image)
    for page in session.exec(
        select(DocumentPage).where(DocumentPage.document_id == document_id)
    ).all():
        session.delete(page)
    processing = session.get(DocumentProcessing, document_id)
    if processing is not None:
        session.delete(processing)
    session.delete(document)
    session.commit()

    # 删除磁盘上的源 PDF 与解析产物；文件缺失不视为错误。
    Path(document.stored_path).unlink(missing_ok=True)
    page_content_store.remove_document(document_id)
    return Response(status_code=204)


@router.get("/{document_id}/file")
def get_document_file(
    document_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return FileResponse(
        document.stored_path,
        media_type="application/pdf",
        filename=document.filename,
        content_disposition_type="inline",
    )
