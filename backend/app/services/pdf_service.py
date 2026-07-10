"""PDF 工具函数：按页提取文字 / 图片 / 整页渲染。

这一层后续会作为工具（tools）暴露给大模型调用，
例如 get_useful_images（结合 ImageAsset 元数据只返回有用图片）。
页码 page_number 一律从 1 开始。
"""

from pathlib import Path
from typing import TypedDict

import pymupdf


class ExtractedImage(TypedDict):
    index: int
    ext: str
    data: bytes


def get_page_count(pdf_path: Path) -> int:
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def get_page_text(pdf_path: Path, page_number: int) -> str:
    """获取某页的纯文本。"""
    with pymupdf.open(pdf_path) as doc:
        return doc[page_number - 1].get_text()


def get_page_images(pdf_path: Path, page_number: int) -> list[ExtractedImage]:
    """获取某页内嵌的所有图片（原始二进制）。"""
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_number - 1]
        images: list[ExtractedImage] = []
        for index, info in enumerate(page.get_images(full=True)):
            extracted = doc.extract_image(info[0])
            images.append(
                {"index": index, "ext": extracted["ext"], "data": extracted["image"]}
            )
        return images


def render_page_as_image(pdf_path: Path, page_number: int, dpi: int = 144) -> bytes:
    """把整页渲染成 PNG，适合直接喂给多模态大模型。"""
    with pymupdf.open(pdf_path) as doc:
        pix = doc[page_number - 1].get_pixmap(dpi=dpi)
        return pix.tobytes("png")
