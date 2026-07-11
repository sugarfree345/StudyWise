"""串行后台解析队列与状态机。"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache
import json
import mimetypes
from pathlib import Path
from threading import Event

from loguru import logger
from sqlmodel import Session, select

from app.core.config import settings
from app.db import engine
from app.models import Document, DocumentPage, DocumentProcessing, ImageAsset
from app.services.document_parser import (
    DocumentParser,
    RemotePage,
    StoredImage,
    StoredPage,
    image_filename,
)
from app.services.paddleocr_service import PaddleOCRDocumentParser
from app.services.page_content_store import PageContentStore, page_content_store
from app.services.study_content_service import useful_by_heuristic


def _now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_document_parser() -> DocumentParser:
    return PaddleOCRDocumentParser()


class ProcessingInterrupted(Exception):
    pass


class DocumentProcessingManager:
    def __init__(
        self,
        parser_factory: Callable[[], DocumentParser] = get_document_parser,
        store: PageContentStore = page_content_store,
    ):
        self._parser_factory = parser_factory
        self._store = store
        self._queue: asyncio.Queue[int | None] = asyncio.Queue()
        self._queued: set[int] = set()
        self._worker: asyncio.Task[None] | None = None
        self._stop_requested = Event()

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stop_requested.clear()
        pending_ids = self._recover_jobs()
        self._worker = asyncio.create_task(
            self._run(), name="studywise-document-parser"
        )
        for document_id in pending_ids:
            await self.enqueue(document_id)

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._stop_requested.set()
        await self._queue.put(None)
        await self._worker
        self._worker = None

    async def enqueue(self, document_id: int) -> None:
        if document_id in self._queued:
            return
        self._queued.add(document_id)
        await self._queue.put(document_id)

    def _recover_jobs(self) -> list[int]:
        """补建历史状态，并恢复上次因进程退出而中断的任务。"""
        pending_ids: list[int] = []
        with Session(engine) as session:
            documents = session.exec(select(Document)).all()
            for document in documents:
                if document.id is None:
                    continue
                processing = session.get(DocumentProcessing, document.id)
                if processing is None:
                    processing = DocumentProcessing(document_id=document.id)
                    session.add(processing)
                elif processing.status == "processing":
                    processing.status = "pending"
                    processing.error_message = None
                    processing.updated_at = _now()
                    session.add(processing)
                if processing.status == "pending":
                    pending_ids.append(document.id)
            session.commit()
        return pending_ids

    async def _run(self) -> None:
        while True:
            document_id = await self._queue.get()
            if document_id is None:
                self._queue.task_done()
                return
            try:
                await asyncio.to_thread(self._process_document, document_id)
            finally:
                self._queued.discard(document_id)
                self._queue.task_done()

    def _process_document(self, document_id: int) -> None:
        with Session(engine) as session:
            document = session.get(Document, document_id)
            processing = session.get(DocumentProcessing, document_id)
            if document is None or processing is None:
                logger.warning("跳过不存在的文档解析任务：{}", document_id)
                return
            processing.status = "processing"
            processing.processed_pages = 0
            processing.error_message = None
            processing.started_at = _now()
            processing.completed_at = None
            processing.updated_at = _now()
            session.add(processing)
            session.commit()
            pdf_path = Path(document.stored_path)

        logger.info("开始提交文档 {} 到 PaddleOCR", document_id)
        try:
            parser = self._parser_factory()
            with Session(engine) as session:
                processing = session.get(DocumentProcessing, document_id)
                if processing is None:
                    raise RuntimeError("文档解析状态记录丢失")
                if not processing.paddle_job_id:
                    processing.paddle_job_id = parser.submit(pdf_path)
                    processing.updated_at = _now()
                    session.add(processing)
                    session.commit()
                job_id = processing.paddle_job_id
                if not job_id:
                    raise RuntimeError("PaddleOCR 未返回任务 ID")

            result_url = self._wait_for_result(document_id, job_id, parser)
            remote_pages = list(parser.iter_pages(result_url))
            if not remote_pages:
                raise RuntimeError("PaddleOCR 结果中没有页面")

            self._replace_document_content(document_id, remote_pages, parser)

            with Session(engine) as session:
                document = session.get(Document, document_id)
                processing = session.get(DocumentProcessing, document_id)
                if document is None or processing is None:
                    raise RuntimeError("文档解析状态记录丢失")
                document.page_count = len(remote_pages)
                document.updated_at = _now()
                processing.status = "ready"
                processing.processed_pages = len(remote_pages)
                processing.completed_at = _now()
                processing.updated_at = _now()
                session.add(document)
                session.add(processing)
                session.commit()
            logger.info("文档 {} 解析完成", document_id)
        except ProcessingInterrupted:
            with Session(engine) as session:
                processing = session.get(DocumentProcessing, document_id)
                if processing is not None:
                    processing.status = "pending"
                    processing.updated_at = _now()
                    session.add(processing)
                    session.commit()
        except Exception as exc:
            logger.exception("文档 {} 解析失败", document_id)
            with Session(engine) as session:
                processing = session.get(DocumentProcessing, document_id)
                if processing is not None:
                    processing.status = "failed"
                    processing.error_message = str(exc)[:2000]
                    processing.updated_at = _now()
                    session.add(processing)
                    session.commit()

    def _wait_for_result(
        self, document_id: int, job_id: str, parser: DocumentParser
    ) -> str:
        while not self._stop_requested.is_set():
            status = parser.get_status(job_id)
            with Session(engine) as session:
                document = session.get(Document, document_id)
                processing = session.get(DocumentProcessing, document_id)
                if document is None or processing is None:
                    raise RuntimeError("文档解析状态记录丢失")
                if status.total_pages:
                    document.page_count = status.total_pages
                    document.updated_at = _now()
                    session.add(document)
                processing.processed_pages = status.processed_pages
                processing.updated_at = _now()
                session.add(processing)
                session.commit()

            if status.state == "done":
                if not status.result_url:
                    raise RuntimeError("PaddleOCR 已完成但未返回 JSONL 地址")
                return status.result_url
            if status.state == "failed":
                raise RuntimeError(status.error_message or "PaddleOCR 任务失败")
            if status.state not in {"pending", "running"}:
                raise RuntimeError(f"未知 PaddleOCR 任务状态：{status.state}")
            if self._stop_requested.wait(settings.paddleocr_poll_interval_seconds):
                break
        raise ProcessingInterrupted

    def _replace_document_content(
        self,
        document_id: int,
        remote_pages: list[RemotePage],
        parser: DocumentParser,
    ) -> None:
        self._store.reset_document(document_id)
        page_numbers: set[int] = set()
        image_keys: set[tuple[int, int]] = set()
        for remote_page in remote_pages:
            stored_page = self._download_page(document_id, remote_page, parser)
            self._store.write_page(document_id, stored_page)
            page_numbers.add(stored_page.page_number)
            with Session(engine) as session:
                page_model = session.exec(
                    select(DocumentPage)
                    .where(DocumentPage.document_id == document_id)
                    .where(DocumentPage.page_number == stored_page.page_number)
                ).first()
                if page_model is None:
                    page_model = DocumentPage(
                        document_id=document_id,
                        page_number=stored_page.page_number,
                    )
                page_model.text = stored_page.markdown
                page_model.markdown = stored_page.markdown
                page_model.raw_json = json.dumps(
                    stored_page.structure, ensure_ascii=False
                )
                page_model.render_path = (
                    str(
                        self._store.render_path(
                            document_id, stored_page.render_filename
                        )
                    )
                    if stored_page.render_filename
                    else None
                )
                page_model.updated_at = _now()
                session.add(page_model)
                session.flush()
                for image in stored_page.images:
                    image_keys.add((stored_page.page_number, image.index))
                    image_model = session.exec(
                        select(ImageAsset)
                        .where(ImageAsset.document_id == document_id)
                        .where(ImageAsset.page_number == stored_page.page_number)
                        .where(ImageAsset.image_index == image.index)
                    ).first()
                    if image_model is None:
                        image_model = ImageAsset(
                            document_id=document_id,
                            page_number=stored_page.page_number,
                            image_index=image.index,
                        )
                    image_model.page_id = page_model.id
                    image_model.source_name = image.source_name
                    image_model.filename = image.filename
                    image_model.stored_path = str(
                        self._store.image_path(document_id, image.filename)
                    )
                    image_model.mime_type = image.mime_type
                    # 解析时打有用性基线：正文引用的图 / 较大的图判为有用，
                    # 未引用的小图（校徽、图标）判为装饰。
                    referenced = image.filename in stored_page.markdown
                    image_model.is_useful = useful_by_heuristic(
                        referenced, len(image.data)
                    )
                    image_model.updated_at = _now()
                    session.add(image_model)
                session.commit()

        with Session(engine) as session:
            for asset in session.exec(
                select(ImageAsset).where(ImageAsset.document_id == document_id)
            ).all():
                if (asset.page_number, asset.image_index) not in image_keys:
                    session.delete(asset)
            for page in session.exec(
                select(DocumentPage).where(DocumentPage.document_id == document_id)
            ).all():
                if page.page_number not in page_numbers:
                    session.delete(page)
            session.commit()

    def _download_page(
        self,
        document_id: int,
        page: RemotePage,
        parser: DocumentParser,
    ) -> StoredPage:
        markdown = page.markdown
        images: list[StoredImage] = []
        metadata: list[dict] = []
        for remote_image in page.images:
            data, mime_type = parser.download(remote_image.url)
            extension = _extension(remote_image.source_name, mime_type)
            filename = image_filename(
                document_id, page.page_number, remote_image.index, extension
            )
            markdown = markdown.replace(
                remote_image.source_name, f"../images/{filename}"
            )
            images.append(
                StoredImage(
                    index=remote_image.index,
                    source_name=remote_image.source_name,
                    filename=filename,
                    mime_type=mime_type,
                    data=data,
                )
            )
            metadata.append(
                {
                    "index": remote_image.index,
                    "source_name": remote_image.source_name,
                    "filename": filename,
                }
            )

        render_filename = None
        render_mime_type = None
        render_data = None
        if page.output_images:
            output = page.output_images[0]
            render_data, render_mime_type = parser.download(output.url)
            extension = _extension(output.source_name, render_mime_type)
            render_filename = (
                f"d{document_id:06d}_p{page.page_number:04d}_render.{extension}"
            )

        structure = dict(page.structure)
        structure["_studywise"] = {
            "document_id": document_id,
            "page_number": page.page_number,
            "images": metadata,
        }
        return StoredPage(
            page_number=page.page_number,
            structure=structure,
            markdown=markdown,
            images=images,
            render_filename=render_filename,
            render_mime_type=render_mime_type,
            render_data=render_data,
        )


def _extension(source_name: str, mime_type: str) -> str:
    suffix = Path(source_name).suffix.lower().lstrip(".")
    if suffix and len(suffix) <= 5:
        return suffix
    guessed = mimetypes.guess_extension(mime_type) or ".bin"
    if guessed in {".jpe", ".jpeg"}:
        return "jpg"
    return guessed.lstrip(".")


document_processing_manager = DocumentProcessingManager()
