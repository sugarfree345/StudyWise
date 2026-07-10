"""LLM 对话接口。

设计要点：
- 后端无状态，前端每次带全量对话历史（messages），简单起步，以后再落库。
- 当前页的文字由后端注入成 system 提示，前端不用自己拼上下文。
- 走 SSE 流式返回；provider 抛错时以 error 事件收尾，而不是中途 500。
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session, select

from app.db import engine, get_session
from app.models import Document, DocumentPage
from app.schemas.chat import ChatRequest
from app.services.llm import get_provider
from app.services.llm.profiles import PublicProfile, get_profile, load_profiles
from app.services.llm.tools import ToolContext, run_tool, tool_specs
from app.services.study_content_service import get_page_content

router = APIRouter(tags=["chat"])


@router.get("/models", response_model=list[PublicProfile])
def list_models() -> list[PublicProfile]:
    """列出已配置的模型档案（不含 api_key）。"""
    return [
        PublicProfile(name=p.name, style=p.style, model_id=p.model_id)
        for p in load_profiles().values()
    ]


def _build_system(document: Document, page_number: int, session: Session) -> str:
    if document.id is None:
        raise RuntimeError("文档尚未持久化")
    try:
        page = get_page_content(session, document.id, page_number)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail="该页面正在解析，请稍后再试") from exc
    return (
        f"你是一个学习辅助助手。用户正在阅读《{document.filename}》的第 {page_number} 页。\n"
        f"以下是 PaddleOCR 解析出的本页 Markdown 内容：\n\n{page['markdown']}\n\n"
        f"本页可按 ID 查询的图片：{page['image_ids']}。\n"
        "请围绕本页内容回答用户的提问，必要时可以出小测验。"
    )


def _build_document_system(
    document: Document, session: Session, current_page: int
) -> str:
    """轻量导航式 system 提示：不注入正文，只告诉模型「书是什么、用户看到第几页、
    如何用工具自取内容」。正文由模型按需通过 get_text / get_image 等工具拉取，
    避免每轮把整本文档塞进上下文。"""
    if document.id is None:
        raise RuntimeError("文档尚未持久化")
    has_pages = session.exec(
        select(DocumentPage.id)
        .where(DocumentPage.document_id == document.id)
        .limit(1)
    ).first()
    if has_pages is None:
        raise HTTPException(status_code=409, detail="文档正在解析，请稍后再试")

    lines = [
        f"你是一个学习辅助助手，正在陪用户阅读《{document.filename}》，"
        f"全书共 {document.page_count} 页，用户当前浏览到第 {current_page} 页。",
        "",
        "你默认看不到页面内容，必须主动调用工具按需获取，不要凭空编造：",
        "- get_text(first_page, last_page)：取页码区间的 Markdown 正文，最常用；"
        "单页时首尾页填同一个数。",
        "- get_page_content(page_number)：取某页正文 + 图片元数据（想知道有哪些图时用）。",
        "- get_image(image_id) / get_page_render(page_number)：需要看图或整页版式时用。",
        "- get_useful_images(page_number) / classify_image(...)：查看/标注图片。",
        "",
        f"用户说「这一页/当前页」时通常指第 {current_page} 页。回答前先用工具取到相关页内容；"
        "跨页追问时保持整段对话连贯，必要时可以出小测验。",
    ]
    if document.table_of_contents.strip():
        lines += ["", "文档目录（供你定位页码）：", document.table_of_contents.strip()]
    elif document.summary.strip():
        lines += ["", "文档摘要：", document.summary.strip()]
    return "\n".join(lines)


async def _sse(
    system: str,
    provider,
    messages,
    *,
    tool_document_id: int | None = None,
    tool_current_page: int | None = None,
) -> AsyncIterator[str]:
    """把 provider 的文本增量包成 SSE。

    传入 tool_document_id 时开启工具调用：单独开一个数据库会话贯穿整个流式过程
    （请求级会话在响应体流式期间不保证可用），供工具执行读写。
    """
    tool_session = None
    tools = None
    tool_runner = None
    if tool_document_id is not None:
        tool_session = Session(engine)
        ctx = ToolContext(
            session=tool_session,
            document_id=tool_document_id,
            current_page=tool_current_page or 1,
        )
        tools = tool_specs()

        def tool_runner(name: str, arguments: dict):
            return run_tool(ctx, name, arguments)

    try:
        async for delta in provider.stream_chat(
            system=system, messages=messages, tools=tools, tool_runner=tool_runner
        ):
            yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as exc:  # noqa: BLE001 — 把上游错误变成流内 error 事件
        logger.exception("LLM 流式调用失败")
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
    finally:
        if tool_session is not None:
            tool_session.close()


@router.post("/documents/{document_id}/pages/{page_number}/chat")
def chat(
    document_id: int,
    page_number: int,
    body: ChatRequest,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not 1 <= page_number <= document.page_count:
        raise HTTPException(status_code=404, detail="页码超出范围")

    profile = get_profile(body.profile)
    if profile is None:
        raise HTTPException(status_code=400, detail=f"未配置模型档案：{body.profile}")

    provider = get_provider(profile)
    system = _build_system(document, page_number, session)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    return StreamingResponse(
        _sse(system, provider, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/documents/{document_id}/chat")
def chat_document(
    document_id: int,
    body: ChatRequest,
    page: int = 1,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """整本文档共用的一段对话：注入全文上下文，page 仅表示当前浏览位置。"""
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    profile = get_profile(body.profile)
    if profile is None:
        raise HTTPException(status_code=400, detail=f"未配置模型档案：{body.profile}")

    current_page = min(max(1, page), max(1, document.page_count))
    provider = get_provider(profile)
    system = _build_document_system(document, session, current_page)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    return StreamingResponse(
        _sse(
            system,
            provider,
            messages,
            tool_document_id=document_id,
            tool_current_page=current_page,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
