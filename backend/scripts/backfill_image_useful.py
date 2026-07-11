"""一次性回填：按启发式给已存在文档的图片重标 is_useful（无需重新 OCR）。

用法（在 backend 目录下）：
    uv run python -m scripts.backfill_image_useful
"""

from sqlmodel import Session, select

from app.db import engine
from app.models import Document
from app.services.study_content_service import reclassify_document_images


def main() -> None:
    with Session(engine) as session:
        documents = session.exec(select(Document)).all()
        total = 0
        for document in documents:
            if document.id is None:
                continue
            changed = reclassify_document_images(session, document.id)
            total += changed
            print(f"文档 {document.id} 《{document.filename}》：改动 {changed} 条")
        print(f"完成，共改动 {total} 条 is_useful。")


if __name__ == "__main__":
    main()
