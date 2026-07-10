from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import Document, DocumentPage, DocumentProcessing, ImageAsset

ProcessingStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentRead(BaseModel):
    id: int
    project_id: int
    filename: str
    page_count: int
    summary: str
    table_of_contents: str
    created_at: datetime
    parse_status: ProcessingStatus
    processed_pages: int
    parse_error: str | None

    @classmethod
    def from_models(
        cls, document: Document, processing: DocumentProcessing
    ) -> "DocumentRead":
        if document.id is None:
            raise ValueError("文档尚未持久化")
        return cls(
            id=document.id,
            project_id=document.project_id,
            filename=document.filename,
            page_count=document.page_count,
            summary=document.summary,
            table_of_contents=document.table_of_contents,
            created_at=document.created_at,
            parse_status=processing.status,  # type: ignore[arg-type]
            processed_pages=processing.processed_pages,
            parse_error=processing.error_message,
        )


class DocumentUpdate(BaseModel):
    summary: str | None = None
    table_of_contents: str | None = None


class ImageAssetRead(BaseModel):
    id: int
    page_id: int | None
    document_id: int
    page_number: int
    image_index: int
    filename: str
    mime_type: str
    summary: str
    is_useful: bool | None
    importance: int
    retrieval_count: int

    @classmethod
    def from_model(cls, image: ImageAsset) -> "ImageAssetRead":
        if image.id is None:
            raise ValueError("图片尚未持久化")
        return cls.model_validate(image, from_attributes=True)


class ImageAssetUpdate(BaseModel):
    summary: str | None = None
    is_useful: bool | None = None
    importance: int | None = Field(default=None, ge=0, le=5)


class PageRead(BaseModel):
    id: int
    document_id: int
    page_number: int
    summary: str
    text: str
    markdown: str
    image_ids: list[int]
    render_available: bool

    @classmethod
    def from_model(
        cls, page: DocumentPage, image_ids: list[int]
    ) -> "PageRead":
        if page.id is None:
            raise ValueError("页面尚未持久化")
        return cls(
            id=page.id,
            document_id=page.document_id,
            page_number=page.page_number,
            summary=page.summary,
            text=page.text,
            markdown=page.markdown,
            image_ids=image_ids,
            render_available=bool(page.render_path),
        )


class PageUpdate(BaseModel):
    summary: str | None = None
