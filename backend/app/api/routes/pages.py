import base64
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.db import get_session
from app.models import Document
from app.services import pdf_service

router = APIRouter(
    prefix="/documents/{document_id}/pages/{page_number}", tags=["pages"]
)


def get_page_document(
    document_id: int, page_number: int, session: Session = Depends(get_session)
) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not 1 <= page_number <= document.page_count:
        raise HTTPException(
            status_code=404, detail=f"页码超出范围（1-{document.page_count}）"
        )
    return document


@router.get("/text")
def get_page_text(
    page_number: int, document: Document = Depends(get_page_document)
) -> dict:
    text = pdf_service.get_page_text(Path(document.stored_path), page_number)
    return {"page_number": page_number, "text": text}


@router.get("/images")
def get_page_images(
    page_number: int, document: Document = Depends(get_page_document)
) -> list[dict]:
    images = pdf_service.get_page_images(Path(document.stored_path), page_number)
    return [
        {
            "index": image["index"],
            "ext": image["ext"],
            "data": base64.b64encode(image["data"]).decode(),
        }
        for image in images
    ]


@router.get("/render")
def render_page(
    page_number: int, document: Document = Depends(get_page_document)
) -> Response:
    png = pdf_service.render_page_as_image(Path(document.stored_path), page_number)
    return Response(content=png, media_type="image/png")
