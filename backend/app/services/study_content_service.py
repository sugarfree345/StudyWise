"""供 HTTP API 和后续 LLM tools 复用的学习内容查询服务。"""

from pathlib import Path

from sqlmodel import Session, select

from app.models import Document, DocumentPage, ImageAsset, Project


def get_project_content(session: Session, project_id: int) -> dict:
    project = session.get(Project, project_id)
    if project is None:
        raise LookupError("项目不存在")
    documents = session.exec(
        select(Document).where(Document.project_id == project_id).order_by(Document.id)
    ).all()
    return {
        "id": project.id,
        "name": project.name,
        "summary": project.summary,
        "document_ids": [document.id for document in documents],
    }


def get_document_content(session: Session, document_id: int) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        raise LookupError("文档不存在")
    pages = session.exec(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    ).all()
    return {
        "id": document.id,
        "project_id": document.project_id,
        "filename": document.filename,
        "summary": document.summary,
        "table_of_contents": document.table_of_contents,
        "page_ids": [page.id for page in pages],
    }


def get_page_content(session: Session, document_id: int, page_number: int) -> dict:
    page = session.exec(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .where(DocumentPage.page_number == page_number)
    ).first()
    if page is None:
        raise LookupError("页面不存在")
    images = session.exec(
        select(ImageAsset)
        .where(ImageAsset.page_id == page.id)
        .order_by(ImageAsset.image_index)
    ).all()
    return {
        "id": page.id,
        "document_id": page.document_id,
        "page_number": page.page_number,
        "summary": page.summary,
        "text": page.text,
        "markdown": page.markdown,
        "image_ids": [image.id for image in images],
    }


def get_useful_images(
    session: Session, document_id: int, page_number: int
) -> list[dict]:
    images = session.exec(
        select(ImageAsset)
        .where(ImageAsset.document_id == document_id)
        .where(ImageAsset.page_number == page_number)
        .where(ImageAsset.is_useful == True)  # noqa: E712
        .order_by(ImageAsset.image_index)
    ).all()
    return [
        {
            "id": image.id,
            "summary": image.summary,
            "importance": image.importance,
            "path": image.stored_path,
        }
        for image in images
    ]


def get_image_path(session: Session, image_id: int) -> Path:
    image = session.get(ImageAsset, image_id)
    if image is None:
        raise LookupError("图片不存在")
    return Path(image.stored_path)
