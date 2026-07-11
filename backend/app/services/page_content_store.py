"""解析产物的文件存储层。"""

import json
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.document_parser import StoredPage


class PageContentStore:
    def __init__(self, root: Path | None = None):
        self._root = root or settings.parsed_dir

    def document_dir(self, document_id: int) -> Path:
        return self._root / str(document_id)

    def reset_document(self, document_id: int) -> None:
        directory = self.document_dir(document_id)
        if directory.exists():
            shutil.rmtree(directory)
        (directory / "pages").mkdir(parents=True)
        (directory / "images").mkdir()
        (directory / "renders").mkdir()

    def remove_document(self, document_id: int) -> None:
        """彻底删除某文档的全部解析产物（页面、图片、渲染图）。"""
        directory = self.document_dir(document_id)
        if directory.exists():
            shutil.rmtree(directory)

    def write_page(self, document_id: int, page: StoredPage) -> None:
        directory = self.document_dir(document_id)
        pages_dir = directory / "pages"
        images_dir = directory / "images"
        renders_dir = directory / "renders"
        pages_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
        renders_dir.mkdir(parents=True, exist_ok=True)

        stem = f"{page.page_number:04d}"
        self._atomic_write(
            pages_dir / f"{stem}.json",
            json.dumps(page.structure, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        self._atomic_write(
            pages_dir / f"{stem}.md",
            page.markdown.encode("utf-8"),
        )
        for image in page.images:
            self._atomic_write(images_dir / image.filename, image.data)
        if page.render_filename and page.render_data is not None:
            self._atomic_write(
                renders_dir / page.render_filename,
                page.render_data,
            )

    def read_markdown(self, document_id: int, page_number: int) -> str:
        return self._page_path(document_id, page_number, "md").read_text(
            encoding="utf-8"
        )

    def read_json(self, document_id: int, page_number: int) -> dict[str, Any]:
        return json.loads(
            self._page_path(document_id, page_number, "json").read_text(
                encoding="utf-8"
            )
        )

    def image_path(self, document_id: int, filename: str) -> Path:
        # PaddleOCR 生成的名字不含目录；再次约束可避免路径穿越。
        safe_name = Path(filename).name
        if safe_name != filename:
            raise ValueError("非法图片文件名")
        return self.document_dir(document_id) / "images" / safe_name

    def render_path(self, document_id: int, filename: str) -> Path:
        safe_name = Path(filename).name
        if safe_name != filename:
            raise ValueError("非法页面渲染文件名")
        return self.document_dir(document_id) / "renders" / safe_name

    def _page_path(self, document_id: int, page_number: int, suffix: str) -> Path:
        return (
            self.document_dir(document_id)
            / "pages"
            / f"{page_number:04d}.{suffix}"
        )

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)


page_content_store = PageContentStore()
