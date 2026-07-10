import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Document, DocumentPage, ImageAsset
from app.schemas.document import ImageAssetRead, PageRead, PageUpdate

router = APIRouter(tags=["pages"])


def _get_document(document_id: int, session: Session) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return document


def _get_page(document_id: int, page_number: int, session: Session) -> DocumentPage:
    _get_document(document_id, session)
    page = session.exec(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .where(DocumentPage.page_number == page_number)
    ).first()
    if page is None:
        raise HTTPException(status_code=404, detail="页面不存在或尚未解析")
    return page


def _read_page(page: DocumentPage, session: Session) -> PageRead:
    if page.id is None:
        raise RuntimeError("页面尚未持久化")
    image_ids = [
        image_id
        for image_id in session.exec(
            select(ImageAsset.id)
            .where(ImageAsset.page_id == page.id)
            .order_by(ImageAsset.image_index)
        ).all()
        if image_id is not None
    ]
    return PageRead.from_model(page, image_ids)


@router.get("/documents/{document_id}/pages", response_model=list[PageRead])
def list_pages(
    document_id: int, session: Session = Depends(get_session)
) -> list[PageRead]:
    _get_document(document_id, session)
    pages = session.exec(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    ).all()
    return [_read_page(page, session) for page in pages]


@router.get("/documents/{document_id}/pages/{page_number}", response_model=PageRead)
def get_page(
    document_id: int,
    page_number: int,
    session: Session = Depends(get_session),
) -> PageRead:
    return _read_page(_get_page(document_id, page_number, session), session)


@router.patch(
    "/documents/{document_id}/pages/{page_number}", response_model=PageRead
)
def update_page(
    document_id: int,
    page_number: int,
    body: PageUpdate,
    session: Session = Depends(get_session),
) -> PageRead:
    page = _get_page(document_id, page_number, session)
    if body.summary is not None:
        page.summary = body.summary
    page.updated_at = datetime.now(timezone.utc)
    session.add(page)
    session.commit()
    session.refresh(page)
    return _read_page(page, session)


@router.get("/documents/{document_id}/pages/{page_number}/text")
def get_page_text(
    document_id: int,
    page_number: int,
    session: Session = Depends(get_session),
) -> dict:
    page = _get_page(document_id, page_number, session)
    return {"page_number": page_number, "text": page.text, "markdown": page.markdown}


@router.get("/documents/{document_id}/pages/{page_number}/json")
def get_page_json(
    document_id: int,
    page_number: int,
    session: Session = Depends(get_session),
) -> dict:
    page = _get_page(document_id, page_number, session)
    return json.loads(page.raw_json)


@router.get(
    "/documents/{document_id}/pages/{page_number}/images",
    response_model=list[ImageAssetRead],
)
def get_page_images(
    document_id: int,
    page_number: int,
    useful: bool | None = None,
    session: Session = Depends(get_session),
) -> list[ImageAssetRead]:
    page = _get_page(document_id, page_number, session)
    statement = (
        select(ImageAsset)
        .where(ImageAsset.page_id == page.id)
        .order_by(ImageAsset.image_index)
    )
    if useful is not None:
        statement = statement.where(ImageAsset.is_useful == useful)
    assets = session.exec(statement).all()
    return [ImageAssetRead.from_model(asset) for asset in assets]


@router.get("/documents/{document_id}/pages/{page_number}/images/{image_index}")
def get_page_image(
    document_id: int,
    page_number: int,
    image_index: int,
    session: Session = Depends(get_session),
) -> FileResponse:
    page = _get_page(document_id, page_number, session)
    image = session.exec(
        select(ImageAsset)
        .where(ImageAsset.page_id == page.id)
        .where(ImageAsset.image_index == image_index)
    ).first()
    if image is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    image.retrieval_count += 1
    session.add(image)
    session.commit()
    return FileResponse(
        image.stored_path, media_type=image.mime_type, filename=image.filename
    )


@router.get("/documents/{document_id}/pages/{page_number}/render")
def render_page(
    document_id: int,
    page_number: int,
    session: Session = Depends(get_session),
) -> FileResponse:
    page = _get_page(document_id, page_number, session)
    if not page.render_path:
        raise HTTPException(status_code=404, detail="PaddleOCR 未返回页面渲染图")
    return FileResponse(page.render_path)
