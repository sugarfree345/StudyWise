"""文档删除接口测试：删干净数据库记录与源文件。"""

import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from app.api.routes.documents import delete_document
from app.models import Document, DocumentPage, DocumentProcessing, ImageAsset, Project


class DeleteDocumentTests(unittest.TestCase):
    def test_delete_removes_rows_and_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            engine = create_engine(
                f"sqlite:///{root / 'test.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            pdf_path = root / "source.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")

            with Session(engine) as session:
                session.add(Project(id=1, name="p"))
                session.add(Document(id=1, project_id=1, filename="a.pdf",
                                     stored_path=str(pdf_path), page_count=1))
                session.add(DocumentProcessing(document_id=1, status="ready"))
                session.add(DocumentPage(id=1, document_id=1, page_number=1,
                                         markdown="x"))
                session.add(ImageAsset(document_id=1, page_id=1, page_number=1,
                                       image_index=1, filename="i.png"))
                session.commit()

                # 删除时用测试引擎的会话；解析产物目录不存在会被安全跳过
                response = delete_document(1, session=session)
                self.assertEqual(response.status_code, 204)

                self.assertIsNone(session.get(Document, 1))
                self.assertIsNone(session.get(DocumentProcessing, 1))
                self.assertEqual(
                    session.exec(select(DocumentPage)).all(), []
                )
                self.assertEqual(session.exec(select(ImageAsset)).all(), [])

            self.assertFalse(pdf_path.exists())  # 源文件已删除
            engine.dispose()

    def test_delete_missing_document_404(self):
        from fastapi import HTTPException

        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'test.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                with self.assertRaises(HTTPException) as ctx:
                    delete_document(999, session=session)
                self.assertEqual(ctx.exception.status_code, 404)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
