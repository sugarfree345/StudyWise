"""页面与图片工具：让大模型按需读取某页正文、图片和整页渲染图，
并为首次读到的图片写入判定（是否有用 / 简介 / 重要性）。

图片语义遵循 ``ImageAsset`` 的约定：装饰性图片（is_useful=False）首次判定后
不再回传原图，只用一句 summary 代替，以节省 token。
"""

from __future__ import annotations

import json

from app.services import study_content_service as content
from app.services.llm.tools.base import (
    ToolContext,
    ToolImage,
    ToolResult,
    register,
)

_PAGE_NUMBER = {
    "type": "integer",
    "description": "页码，从 1 开始。",
    "minimum": 1,
}

_MAX_TEXT_PAGES = 8


def _join_pages(pages: list[dict]) -> str:
    """把多页 Markdown 拼成一段，每页前标注页码（Markdown 本身不含页码）。"""
    return "\n\n".join(
        f"## 第 {page['page_number']} 页\n\n{page['markdown']}".rstrip()
        for page in pages
    )


@register(
    name="get_full_pdf_text",
    description=(
        "获取整份 PDF 全部页拼接后的 Markdown 全文（每页前带页码标注）。"
        "这是高成本工具：只在用户明确要求整本通读/全书总结/全局对比，"
        "且目录、摘要、search_document 和分页 get_text 无法合理完成时才调用。"
        "不要仅因为对话刚开始或你尚不了解文档就通读全文。"
        "只需一页、数页或某个主题时，分别使用 get_text 或 search_document。"
    ),
    parameters={"type": "object", "properties": {}},
)
def get_full_pdf_text(ctx: ToolContext, args: dict) -> ToolResult:
    pages = content.get_document_markdown(ctx.session, ctx.document_id)
    return ToolResult(
        text=_join_pages(pages),
        page_numbers=[page["page_number"] for page in pages],
    )


@register(
    name="get_text",
    description=(
        "读取一个连续页码区间的 Markdown 正文（含首尾页），结果中每页明确标注页码。"
        "当问题依赖已知页面的文字、公式、题目、条件或推导，"
        "或 search_document 已经找到候选页时使用。"
        "已知准确页码时先读最小范围；单页时 first_page 与 last_page 相同。"
        "一次最多返回从起始页开始的连续 8 页；即使 last_page 更大，也会在第 8 页处截断。"
        "获得结果后，如果页面是解答/证明/推导/续页，出现「由上式/根据前文」，"
        "或缺少题目、定义、符号、条件、图表，必须继续读取最少必要的相关页，"
        "通常先扩展相邻 1–2 页。当问题、必要前提和结论已齐全时停止，不要无限扩大范围。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "first_page": {**_PAGE_NUMBER, "description": "起始页码（含），从 1 开始。"},
            "last_page": {**_PAGE_NUMBER, "description": "结束页码（含）。单页时与 first_page 相同。"},
        },
        "required": ["first_page", "last_page"],
    },
)
def get_text(ctx: ToolContext, args: dict) -> ToolResult:
    first_page = int(args["first_page"])
    last_page = int(args["last_page"])
    if last_page < first_page:
        first_page, last_page = last_page, first_page
    requested_last_page = last_page
    last_page = min(requested_last_page, first_page + _MAX_TEXT_PAGES - 1)
    pages = content.get_pages_markdown(
        ctx.session, ctx.document_id, first_page, last_page
    )
    text = _join_pages(pages)
    if requested_last_page > last_page:
        text += (
            f"\n\n[单次最多读取 {_MAX_TEXT_PAGES} 页：原请求结束于第 {requested_last_page} 页，"
            f"本次只返回第 {first_page}–{last_page} 页。如仍需要后续内容，请再次调用 get_text。]"
        )
    return ToolResult(
        text=text,
        page_numbers=[page["page_number"] for page in pages],
    )


@register(
    name="search_document",
    description=(
        "按关键词在整份 PDF 的已解析 Markdown 中定位相关页，返回页码和短片段，不返回全文。"
        "当问题依赖文档中的概念、公式、术语或原句，但准确页码未知且对话历史无法定位时使用。"
        "已知页码时直接用 get_text，不要搜索；也不要因为界面停在某页就把该页当作搜索结果。"
        "query 应是有区分度的术语、公式变量或短语，不要传整段问题。"
        "命中只是候选：必须再调用 get_text 阅读命中页，"
        "并根据题目、定义、推导是否完整决定是否补读相邻页。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用于定位的独特术语、公式变量或短语；不要传整段长问题。",
                "minLength": 1,
            }
        },
        "required": ["query"],
    },
)
def search_document(ctx: ToolContext, args: dict) -> ToolResult:
    query = str(args["query"])
    matches = content.search_document_markdown(ctx.session, ctx.document_id, query)
    return ToolResult.json({"query": query, "matches": matches})


@register(
    name="get_page_content",
    description=(
        "获取指定页的 Markdown 正文和该页图片的元数据列表。"
        "当回答同时需要页面正文与图片索引时使用；只需文字时优先 get_text。"
        "先看图片元数据中的 summary 决定是否需要 get_image 原图，避免无意义的图像回传。"
    ),
    parameters={
        "type": "object",
        "properties": {"page_number": _PAGE_NUMBER},
        "required": ["page_number"],
    },
)

def get_page_content(ctx: ToolContext, args: dict) -> ToolResult:
    page_number = int(args["page_number"])
    page = content.get_page_content(ctx.session, ctx.document_id, page_number)
    images = content.list_page_images(ctx.session, ctx.document_id, page_number)
    result = ToolResult.json(
        {"page_number": page_number, "markdown": page["markdown"], "images": images}
    )
    result.page_numbers = [page_number]
    return result


@register(
    name="get_image",
    description=(
        "按 id 获取一张图片的原图。若该图已被判定为装饰性（is_useful=false），"
        "则只返回它的文字简介以节省 token。"
    ),
    parameters={
        "type": "object",
        "properties": {"image_id": {"type": "integer", "description": "图片 id。"}},
        "required": ["image_id"],
    },
)
def get_image(ctx: ToolContext, args: dict) -> ToolResult:
    image_id = int(args["image_id"])
    meta = content.get_image_meta(ctx.session, image_id)
    # 已判定为装饰性的图片不再回传原图，用简介代替。
    if meta["is_useful"] is False:
        return ToolResult.json(
            {
                "image_id": image_id,
                "is_useful": False,
                "note": "装饰性图片，已用简介代替原图。",
                "summary": meta["summary"],
            }
        )
    data, mime_type, _ = content.read_image_bytes(ctx.session, image_id)
    return ToolResult(
        text=json.dumps({"image_id": image_id, **meta}, ensure_ascii=False),
        image=ToolImage(data=data, mime_type=mime_type),
    )


@register(
    name="get_useful_images",
    description="获取指定页中已被判定为有用（is_useful=true）的图片元数据列表。",
    parameters={
        "type": "object",
        "properties": {"page_number": _PAGE_NUMBER},
        "required": ["page_number"],
    },
)
def get_useful_images(ctx: ToolContext, args: dict) -> ToolResult:
    page_number = int(args["page_number"])
    images = content.get_useful_images(ctx.session, ctx.document_id, page_number)
    return ToolResult.json({"page_number": page_number, "images": images})


@register(
    name="get_page_render",
    description=(
        "获取整页的渲染大图（含版式与图文）。当页面排版复杂、"
        "Markdown/OCR 内容缺失或乱序，或需要理解公式排版、图表空间关系时使用。"
        "如果 get_text 已能完整回答，不要再取整页图。"
    ),
    parameters={
        "type": "object",
        "properties": {"page_number": _PAGE_NUMBER},
        "required": ["page_number"],
    },
)
def get_page_render(ctx: ToolContext, args: dict) -> ToolResult:
    page_number = int(args["page_number"])
    path = content.get_page_render_path(ctx.session, ctx.document_id, page_number)
    return ToolResult(
        text=json.dumps({"page_number": page_number}, ensure_ascii=False),
        image=ToolImage(data=path.read_bytes(), mime_type=content.guess_image_mime(path)),
    )


@register(
    name="classify_image",
    description=(
        "为一张首次读到的图片写入判定：是否有用、一句话简介、重要性评分。"
        "装饰性/无信息量的图片请标 is_useful=false，之后系统不再回传其原图。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_id": {"type": "integer", "description": "图片 id。"},
            "is_useful": {
                "type": "boolean",
                "description": "是否含有对学习有价值的信息。",
            },
            "summary": {"type": "string", "description": "一句话概括图片内容。"},
            "importance": {
                "type": "integer",
                "description": "重要性评分，0（无关）到 5（关键）。",
                "minimum": 0,
                "maximum": 5,
            },
        },
        "required": ["image_id", "is_useful", "summary", "importance"],
    },
)
def classify_image(ctx: ToolContext, args: dict) -> ToolResult:
    meta = content.classify_image(
        ctx.session,
        int(args["image_id"]),
        is_useful=bool(args["is_useful"]),
        summary=str(args["summary"]),
        importance=int(args["importance"]),
    )
    return ToolResult.json({"ok": True, **meta})
