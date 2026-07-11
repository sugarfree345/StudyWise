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
        "仅在你对这份文档【一无所知】、需要先建立对它整体内容与结构的了解时才调用："
        "典型场景是对话刚开始、你的上下文还是空的，根本不知道这份文档讲什么，"
        "先调它通读一遍。"
        "如果你已经大致了解文档、只想看某一页或某几页，请改用 get_text，不要用本工具，"
        "以免浪费上下文。"
    ),
    parameters={"type": "object", "properties": {}},
)
def get_full_pdf_text(ctx: ToolContext, args: dict) -> ToolResult:
    pages = content.get_document_markdown(ctx.session, ctx.document_id)
    return ToolResult(text=_join_pages(pages))


@register(
    name="get_text",
    description=(
        "获取某个页码区间的 Markdown 正文（含首尾页），多页会按页拼接返回。"
        "这是最常用的取文工具：用户问「当前页/这一页」时，把 first_page 和 "
        "last_page 都设为当前页即可；需要上下文时再扩大区间。"
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
    pages = content.get_pages_markdown(
        ctx.session, ctx.document_id, first_page, last_page
    )
    return ToolResult(text=_join_pages(pages))


@register(
    name="get_current_page_context",
    description=(
        "读取用户界面当前打开的页及其相邻上下文，无需填写页码。"
        "当用户明确提到「当前页/这一页/本页」或需要用当前页面来消解指代时使用。"
        "结果会明确告诉你实际当前页码；若读到的页面依赖前文，可再用 get_text 精确补读。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "before_pages": {
                "type": "integer",
                "description": "额外读取当前页之前的页数，默认 0，最多 5。",
                "minimum": 0,
                "maximum": 5,
            },
            "after_pages": {
                "type": "integer",
                "description": "额外读取当前页之后的页数，默认 0，最多 5。",
                "minimum": 0,
                "maximum": 5,
            },
        },
    },
)
def get_current_page_context(ctx: ToolContext, args: dict) -> ToolResult:
    before_pages = min(5, max(0, int(args.get("before_pages", 0))))
    after_pages = min(5, max(0, int(args.get("after_pages", 0))))
    first_page = max(1, ctx.current_page - before_pages)
    last_page = ctx.current_page + after_pages
    pages = content.get_pages_markdown(
        ctx.session, ctx.document_id, first_page, last_page
    )
    returned_first = pages[0]["page_number"]
    returned_last = pages[-1]["page_number"]
    return ToolResult(
        text=(
            f"用户界面当前为第 {ctx.current_page} 页；本次返回第 {returned_first}~{returned_last} 页。\n\n"
            f"{_join_pages(pages)}"
        )
    )


@register(
    name="search_document",
    description=(
        "按关键词在整份 PDF 的已解析 Markdown 中定位相关页，返回页码和短片段，不返回全文。"
        "当用户提到某个概念、公式或术语却不知道页码，且对话历史也无法定位时先调用本工具；"
        "根据命中结果再调用 get_text 或 get_page_content 阅读必要页面。"
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
        "先看元数据里的 summary 决定是否有必要再调用 get_image 取原图。"
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
    return ToolResult.json(
        {"page_number": page_number, "markdown": page["markdown"], "images": images}
    )


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
        "仅靠 Markdown 无法理解时使用。"
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
