"""供 HTTP API 和 LLM tools 复用的学习内容查询服务。"""

from datetime import datetime, timezone
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


def _image_meta(image: ImageAsset) -> dict:
    """图片的轻量元数据，供工具以纯文本返回，避免动辄回传原图。"""
    return {
        "id": image.id,
        "page_number": image.page_number,
        "image_index": image.image_index,
        "summary": image.summary,
        "is_useful": image.is_useful,
        "importance": image.importance,
    }


def list_page_images(
    session: Session, document_id: int, page_number: int
) -> list[dict]:
    """某页全部图片的元数据（不含原图字节）。"""
    images = session.exec(
        select(ImageAsset)
        .where(ImageAsset.document_id == document_id)
        .where(ImageAsset.page_number == page_number)
        .order_by(ImageAsset.image_index)
    ).all()
    return [_image_meta(image) for image in images]


def get_page_render_path(
    session: Session, document_id: int, page_number: int
) -> Path:
    """整页渲染图路径；未解析或 PaddleOCR 未产出渲染图时抛 LookupError。"""
    page = session.exec(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .where(DocumentPage.page_number == page_number)
    ).first()
    if page is None:
        raise LookupError("页面不存在")
    if not page.render_path:
        raise LookupError("该页没有渲染图")
    path = Path(page.render_path)
    if not path.exists():
        raise LookupError("渲染图文件缺失")
    return path


_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def guess_image_mime(path: Path, fallback: str = "") -> str:
    """按扩展名推断图片 MIME；解析器写入的 mime_type 常是通用的
    application/octet-stream，多模态接口会拒收，故以扩展名为准。"""
    mime = _IMAGE_MIME_BY_SUFFIX.get(path.suffix.lower())
    if mime:
        return mime
    if fallback.startswith("image/"):
        return fallback
    return "image/png"


def read_image_bytes(session: Session, image_id: int) -> tuple[bytes, str, dict]:
    """读取原图字节，并累加检索次数。返回 (data, mime_type, meta)。"""
    image = session.get(ImageAsset, image_id)
    if image is None:
        raise LookupError("图片不存在")
    path = Path(image.stored_path)
    if not path.exists():
        raise LookupError("图片文件缺失")
    data = path.read_bytes()
    image.retrieval_count += 1
    session.add(image)
    session.commit()
    return data, guess_image_mime(path, image.mime_type), _image_meta(image)


def classify_image(
    session: Session,
    image_id: int,
    *,
    is_useful: bool,
    summary: str,
    importance: int,
) -> dict:
    """写入大模型对图片的首次判定：是否有用、简介、重要性。"""
    image = session.get(ImageAsset, image_id)
    if image is None:
        raise LookupError("图片不存在")
    image.is_useful = is_useful
    image.summary = summary
    image.importance = importance
    image.updated_at = datetime.now(timezone.utc)
    session.add(image)
    session.commit()
    session.refresh(image)
    return _image_meta(image)


def get_image_meta(session: Session, image_id: int) -> dict:
    image = session.get(ImageAsset, image_id)
    if image is None:
        raise LookupError("图片不存在")
    return _image_meta(image)


def get_pages_markdown(
    session: Session, document_id: int, first_page: int, last_page: int
) -> list[dict]:
    """取 [first_page, last_page] 区间内已解析页的 Markdown（按页码升序）。

    传入顺序颠倒时自动纠正；区间内没有任何已解析页时抛 LookupError。
    """
    low, high = sorted((first_page, last_page))
    pages = session.exec(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .where(DocumentPage.page_number >= low)
        .where(DocumentPage.page_number <= high)
        .order_by(DocumentPage.page_number)
    ).all()
    if not pages:
        raise LookupError(f"第 {low}~{high} 页没有已解析内容")
    return [
        {"page_number": page.page_number, "markdown": page.markdown} for page in pages
    ]


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
