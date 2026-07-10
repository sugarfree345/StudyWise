"""异步文档解析服务的稳定边界。"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ParseJobStatus:
    state: str
    total_pages: int
    processed_pages: int
    result_url: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RemoteFile:
    index: int
    source_name: str
    url: str


@dataclass(frozen=True)
class RemotePage:
    page_number: int
    structure: dict[str, Any]
    markdown: str
    images: list[RemoteFile]
    output_images: list[RemoteFile]


@dataclass(frozen=True)
class StoredImage:
    index: int
    source_name: str
    filename: str
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class StoredPage:
    page_number: int
    structure: dict[str, Any]
    markdown: str
    images: list[StoredImage]
    render_filename: str | None = None
    render_mime_type: str | None = None
    render_data: bytes | None = None


def image_filename(
    document_id: int, page_number: int, image_index: int, extension: str
) -> str:
    safe_extension = extension.lower().lstrip(".") or "png"
    return (
        f"d{document_id:06d}_p{page_number:04d}_img{image_index:03d}."
        f"{safe_extension}"
    )


class DocumentParser(Protocol):
    def submit(self, pdf_path: Path) -> str:
        """提交整份 PDF，返回远程任务 ID。"""
        ...

    def get_status(self, job_id: str) -> ParseJobStatus:
        ...

    def iter_pages(self, result_url: str) -> Iterator[RemotePage]:
        ...

    def download(self, url: str) -> tuple[bytes, str]:
        """下载远程图片，返回二进制和 Content-Type。"""
        ...
