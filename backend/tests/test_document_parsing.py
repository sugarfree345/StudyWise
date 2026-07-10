import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.models import (
    Document,
    DocumentPage,
    DocumentProcessing,
    ImageAsset,
    Project,
)
from app.services.document_parser import (
    ParseJobStatus,
    RemoteFile,
    RemotePage,
    StoredImage,
    StoredPage,
)
from app.services.document_processing import DocumentProcessingManager
from app.services.paddleocr_service import PaddleOCRDocumentParser
from app.services.page_content_store import PageContentStore


class PaddleOCRParserTests(unittest.TestCase):
    def test_job_api_and_jsonl_results(self):
        result_line = json.dumps(
            {
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {
                                "text": "# 标题\n\n![图](imgs/a.png)",
                                "images": {"imgs/a.png": "https://files/image"},
                            },
                            "outputImages": {
                                "layout": "https://files/render"
                            },
                        }
                    ]
                }
            }
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(200, json={"data": {"jobId": "job-1"}})
            if str(request.url).endswith("/job-1"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "state": "done",
                            "extractProgress": {
                                "totalPages": 1,
                                "extractedPages": 1,
                            },
                            "resultUrl": {"jsonUrl": "https://files/result"},
                        }
                    },
                )
            if str(request.url) == "https://files/result":
                return httpx.Response(200, text=result_line)
            return httpx.Response(
                200, content=b"image", headers={"content-type": "image/png"}
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        parser = PaddleOCRDocumentParser(client)
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "lesson.pdf"
            pdf_path.write_bytes(b"%PDF-test")
            with patch.object(settings, "paddleocr_api_token", "test-token"):
                job_id = parser.submit(pdf_path)
                status = parser.get_status(job_id)
                pages = list(parser.iter_pages(status.result_url or ""))
                data, mime_type = parser.download(pages[0].images[0].url)

        self.assertEqual(job_id, "job-1")
        self.assertEqual(status.total_pages, 1)
        self.assertEqual(pages[0].markdown, "# 标题\n\n![图](imgs/a.png)")
        self.assertEqual(pages[0].images[0].source_name, "imgs/a.png")
        self.assertEqual(data, b"image")
        self.assertEqual(mime_type, "image/png")


class PageContentStoreTests(unittest.TestCase):
    def test_writes_and_reads_page_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PageContentStore(Path(directory))
            store.reset_document(3)
            page = StoredPage(
                page_number=2,
                structure={"type": "page"},
                markdown="# 第二页",
                images=[
                    StoredImage(
                        index=1,
                        source_name="imgs/source.png",
                        filename="d000003_p0002_img001.png",
                        mime_type="image/png",
                        data=b"image-bytes",
                    )
                ],
                render_filename="d000003_p0002_render.jpg",
                render_mime_type="image/jpeg",
                render_data=b"render-bytes",
            )

            store.write_page(3, page)

            self.assertEqual(store.read_markdown(3, 2), "# 第二页")
            self.assertEqual(store.read_json(3, 2), {"type": "page"})
            image_path = store.image_path(3, "d000003_p0002_img001.png")
            self.assertEqual(image_path.read_bytes(), b"image-bytes")
            render_path = store.render_path(3, "d000003_p0002_render.jpg")
            self.assertEqual(render_path.read_bytes(), b"render-bytes")
            json.loads(
                (Path(directory) / "3" / "pages" / "0002.json").read_text(
                    encoding="utf-8"
                )
            )

    def test_rejects_image_path_traversal(self):
        store = PageContentStore(Path("unused"))
        with self.assertRaisesRegex(ValueError, "非法"):
            store.image_path(1, "../secret.png")


class DocumentProcessingTests(unittest.TestCase):
    def test_downloads_remote_assets_and_rewrites_markdown(self):
        class Parser:
            def download(self, url: str):
                return (url.encode(), "image/png")

        with tempfile.TemporaryDirectory() as directory:
            manager = DocumentProcessingManager(
                parser_factory=lambda: Parser(),  # type: ignore[arg-type]
                store=PageContentStore(Path(directory)),
            )
            page = RemotePage(
                page_number=3,
                structure={"markdown": {}},
                markdown="![示意图](imgs/chart.png)",
                images=[
                    RemoteFile(
                        index=1,
                        source_name="imgs/chart.png",
                        url="https://files/chart",
                    )
                ],
                output_images=[
                    RemoteFile(
                        index=1,
                        source_name="layout.jpg",
                        url="https://files/layout",
                    )
                ],
            )

            stored = manager._download_page(9, page, Parser())  # type: ignore[arg-type]

        self.assertIn("d000009_p0003_img001.png", stored.markdown)
        self.assertEqual(stored.images[0].data, b"https://files/chart")
        self.assertEqual(stored.render_filename, "d000009_p0003_render.jpg")
        self.assertEqual(stored.structure["_studywise"]["page_number"], 3)

    def test_full_job_persists_document_page_and_image_models(self):
        class Parser:
            def submit(self, pdf_path: Path):
                return "job-1"

            def get_status(self, job_id: str):
                return ParseJobStatus(
                    state="done",
                    total_pages=1,
                    processed_pages=1,
                    result_url="https://files/result",
                )

            def iter_pages(self, result_url: str):
                yield RemotePage(
                    page_number=1,
                    structure={"type": "page"},
                    markdown="# 第一页\n\n![图](imgs/a.png)",
                    images=[
                        RemoteFile(1, "imgs/a.png", "https://files/image")
                    ],
                    output_images=[],
                )

            def download(self, url: str):
                return b"png", "image/png"

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "test.db"
            test_engine = create_engine(
                f"sqlite:///{database_path}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(test_engine)
            pdf_path = Path(directory) / "source.pdf"
            pdf_path.write_bytes(b"%PDF")
            with Session(test_engine) as session:
                session.add(Project(id=1, name="测试项目"))
                document = Document(
                    project_id=1,
                    filename="source.pdf",
                    stored_path=str(pdf_path),
                )
                session.add(document)
                session.commit()
                session.refresh(document)
                self.assertIsNotNone(document.id)
                session.add(DocumentProcessing(document_id=document.id))
                session.commit()
                document_id = document.id

            manager = DocumentProcessingManager(
                parser_factory=lambda: Parser(),  # type: ignore[arg-type]
                store=PageContentStore(Path(directory) / "parsed"),
            )
            with patch("app.services.document_processing.engine", test_engine):
                manager._process_document(document_id)  # type: ignore[arg-type]

            with Session(test_engine) as session:
                processing = session.get(DocumentProcessing, document_id)
                page = session.exec(select(DocumentPage)).first()
                image = session.exec(select(ImageAsset)).first()

            self.assertIsNotNone(processing)
            self.assertIsNotNone(page)
            self.assertIsNotNone(image)
            self.assertEqual(processing.status, "ready")
            self.assertEqual(page.markdown, "# 第一页\n\n![图](../images/d000001_p0001_img001.png)")
            self.assertEqual(image.page_id, page.id)
            self.assertTrue(Path(image.stored_path).exists())
            test_engine.dispose()


if __name__ == "__main__":
    unittest.main()
