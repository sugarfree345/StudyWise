"""LLM 对话接口。

设计要点：
- 后端无状态，前端每次带全量对话历史（messages），简单起步，以后再落库。
- 当前页随每条用户问题由前端一并写入历史；旧问题的页码永不改写，
  让后续请求严格追加在先前提示之后，利于提示缓存。
- 走 SSE 流式返回；provider 抛错时以 error 事件收尾，而不是中途 500。
"""

import asyncio
import contextlib
import json
import time
from hashlib import sha256
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session, select

from app.db import engine, get_session
from app.models import ChatConversation, Document, DocumentPage
from app.schemas.chat import ChatRequest
from app.services.conversation_page_context import (
    build_recent_page_context,
    record_pages,
)
from app.services.llm import get_provider
from app.services.llm.base import Usage
from app.services.llm.profiles import PublicProfile, get_profile, load_profiles
from app.services.llm.tools import ToolContext, run_tool, tool_specs
from app.services.study_content_service import get_page_content

router = APIRouter(tags=["chat"])

_TOOL_RESULT_PREVIEW_CHARS = 2400


def _tool_result_activity(result) -> dict:
    """把工具结果变成可安全展示的调试摘要。

    原始图像与过长页面不进 SSE/对话库；前端仍能看到工具是否
    返回了图片、原文长度和足以定位问题的文本片段。
    """
    text = result.text or ""
    truncated = len(text) > _TOOL_RESULT_PREVIEW_CHARS
    preview = text[:_TOOL_RESULT_PREVIEW_CHARS]
    if truncated:
        preview = f"{preview}\n……（已截断，原文共 {len(text)} 字符）"
    return {
        "result": preview,
        "result_chars": len(text),
        "truncated": truncated,
        "has_image": result.image is not None,
        "is_error": result.is_error,
    }


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


def _build_document_system(document: Document, session: Session) -> str:
    """轻量导航式 system 提示，**保持完全静态**（不含当前页等易变信息），
    以便作为稳定前缀命中 OpenAI 的提示缓存。每条用户问题都附有其提问时的
    当前页不进 system；每条用户消息用紧凑标签记录其发送时的界面页码。

    正文不注入，由模型按需通过 get_text / get_image 等工具拉取。"""
    if document.id is None:
        raise RuntimeError("文档尚未持久化")
    has_pages = session.exec(
        select(DocumentPage.id)
        .where(DocumentPage.document_id == document.id)
        .limit(1)
    ).first()
    if has_pages is None:
        raise HTTPException(status_code=409, detail="文档正在解析，请稍后再试")

    # 工具清单不写进提示词：模型已从 API 的 tools 参数拿到完整 schema，
    # 这里只定义稳定的决策边界。分区便于模型遵循，也便于后续独立评测和调整。
    lines = [
        f"你是一个学习辅助助手，正在陪用户阅读《{document.filename}》，"
        f"全书共 {document.page_count} 页。",
        "",
        "<document_grounding>",
        "你默认看不到 PDF 正文。只有工具返回的内容、用户明确提供的内容，"
        "以及当前对话中已出现的信息，才可作为文档依据。",
        "当前用户问题之后可能附有「[最近使用页面临时参考]」：它包含本会话最近通过文字工具"
        "读取的页面，最多 8 页、1600 tokens，只用于回答紧接着的上一条问题，不是新的用户请求。",
        "先检查最近使用页面临时参考是否已经足够。如果答案仍依赖其中没有的 PDF 具体定义、"
        "公式、题目、条件、图表、推导或上下文，"
        "而这些依据当前不可见，则必须先调用工具，不得凭常识猜测文档内容。",
        "如果问题属于不依赖本 PDF 的通用知识、翻译、改写或固定格式回复，"
        "且现有信息已足够，则直接回答，不要为了形式而调用工具。",
        "</document_grounding>",
        "",
        "<tool_routing>",
        "每条用户消息末尾的 [ui_page=N] 表示该消息发送时界面停留在第 N 页。"
        "N 只是定位参考：不要默认当前页必然相关，也不要默认它必然无关。",
        "用户指向「当前页/这里/本页/这个公式」且需要正文时，用 get_text 精确读取第 N 页。",
        "已知准确页码时直接用 get_text，不要先搜索。",
        "用户提到概念、公式或术语，但页码不明且历史无法定位时，"
        "先用 search_document 找候选页，再用 get_text 读取命中页。",
        "Markdown 不足以理解公式排版、图表、图像或页面结构时，"
        "再使用 get_page_content、get_image 或 get_page_render。",
        "</tool_routing>",
        "",
        "<context_sufficiency>",
        "每次工具返回页面内容后，在最终回答前必须检查上下文是否充分。",
        "以下任一信号表示尚不充分：页面从半句或推导中间开始；"
        "出现「由上式/根据前文/因此/继续/解得」等承接表达；"
        "公式的符号、目标、输入或约束未定义；"
        "当前页只有解答/证明/推导而缺少题目或前提；"
        "引用了其他页的公式、图、表或结论。",
        "发现上述信号时，继续用 get_text 补读最少必要的相关页，"
        "通常先扩展相邻 1–2 页；结果仍不足时可再次调用。"
        "不要因为第一次结果含有相关关键词就立即停止。",
        "当问题对象、必要定义、前提和相关结论已齐全时停止读取。"
        "不要为了追求绝对完整而读取无关页面或整份 PDF。",
        "</context_sufficiency>",
        "",
        "<tool_examples>",
        "例1：用户问当前页公式；先读第 N 页；若该页以「因此」开头且符号未定义，"
        "再读前 1–2 页，然后结合题目与推导回答。",
        "例2：用户问「之前那个均方误差公式」但无法定位页码；"
        "先 search_document 搜索「均方误差」，再 get_text 读取候选页及必要的相邻页。",
        "例3：用户要求「只回复 yes」；直接回复，不调用文档工具。",
        "</tool_examples>",
        "",
        "<answer_policy>",
        "回答必须以已取得的内容为依据。经过合理检索仍无法确定用户所指对象时，简洁追问。",
        "不要声称看过尚未通过工具取得的页面，不要向用户展示内部的工具选择检查过程。",
        "跨页追问时保持整段对话连贯。",
        "</answer_policy>",
    ]
    if document.table_of_contents.strip():
        lines += ["", "文档目录（供你定位页码）：", document.table_of_contents.strip()]
    elif document.summary.strip():
        lines += ["", "文档摘要：", document.summary.strip()]
    return "\n".join(lines)


def _document_prompt_cache_key(document_id: int, model_id: str) -> str:
    """为同一「文档 + 模型」生成稳定且不暴露原始 ID 的缓存路由键。"""
    identity = f"studywise:document-prompt:v1:{document_id}:{model_id}"
    return f"studywise:{sha256(identity.encode()).hexdigest()[:32]}"


async def _sse(
    system: str,
    provider,
    messages,
    *,
    tool_document_id: int | None = None,
    tool_current_page: int | None = None,
    prompt_cache_key: str | None = None,
    conversation_id: int | None = None,
    conversation_turn: int | None = None,
    reused_pages: list[int] | None = None,
    reused_context_truncated: bool = False,
) -> AsyncIterator[str]:
    """把 provider 的文本增量包成 SSE。

    传入 tool_document_id 时开启工具调用：单独开一个数据库会话贯穿整个流式过程
    （请求级会话在响应体流式期间不保证可用），供工具执行读写。
    """
    started_at = time.perf_counter()
    event_queue: asyncio.Queue[dict | None] = asyncio.Queue()
    tool_session = None
    tools = None
    tool_runner = None
    tool_sequence = 0
    if tool_document_id is not None:
        tool_session = Session(engine)
        ctx = ToolContext(
            session=tool_session,
            document_id=tool_document_id,
            current_page=tool_current_page or 1,
        )
        tools = tool_specs()

        def tool_runner(name: str, arguments: dict):
            nonlocal tool_sequence
            tool_sequence += 1
            activity_id = f"tool-{tool_sequence}"
            event_queue.put_nowait(
                {
                    "type": "activity",
                    "activity": {
                        "kind": "tool_call",
                        "id": activity_id,
                        "tool": name,
                        "arguments": arguments,
                    },
                }
            )
            result = run_tool(ctx, name, arguments)
            if (
                not result.is_error
                and conversation_id is not None
                and conversation_turn is not None
                and result.page_numbers
            ):
                record_pages(
                    tool_session,
                    conversation_id=conversation_id,
                    page_numbers=result.page_numbers,
                    turn=conversation_turn,
                )
            event_queue.put_nowait(
                {
                    "type": "activity",
                    "activity": {
                        "kind": "tool_result",
                        "id": activity_id,
                        "tool": name,
                        **_tool_result_activity(result),
                    },
                }
            )
            event_queue.put_nowait(
                {
                    "type": "activity",
                    "activity": {
                        "kind": "status",
                        "message": "正在结合工具结果并检查上下文",
                    },
                }
            )
            return result

    usage = Usage()
    async def produce_events() -> None:
        answer_started = False
        if reused_pages:
            page_labels = "、".join(str(page) for page in reused_pages)
            suffix = "（已截断至 1600 tokens）" if reused_context_truncated else ""
            event_queue.put_nowait(
                {
                    "type": "activity",
                    "activity": {
                        "kind": "status",
                        "message": f"已附加最近使用的第 {page_labels} 页上下文{suffix}",
                    },
                }
            )
        event_queue.put_nowait(
            {
                "type": "activity",
                "activity": {"kind": "status", "message": "正在分析问题与可用上下文"},
            }
        )
        try:
            async for delta in provider.stream_chat(
                system=system,
                messages=messages,
                tools=tools,
                tool_runner=tool_runner,
                usage=usage,
                prompt_cache_key=prompt_cache_key,
            ):
                if not answer_started:
                    answer_started = True
                    event_queue.put_nowait(
                        {
                            "type": "activity",
                            "activity": {"kind": "status", "message": "正在生成回答"},
                        }
                    )
                event_queue.put_nowait({"type": "delta", "text": delta})
            # 一次提问（可能含多轮工具调用）的累计 token 用量。
            event_queue.put_nowait(
                {
                    "type": "usage",
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cached_tokens": usage.cached_tokens,
                    "total_tokens": usage.total_tokens,
                }
            )
            event_queue.put_nowait(
                {
                    "type": "done",
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                }
            )
        except Exception as exc:  # noqa: BLE001 — 把上游错误变成流内 error 事件
            logger.exception("LLM 流式调用失败")
            event_queue.put_nowait(
                {
                    "type": "error",
                    "message": str(exc),
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                }
            )
        finally:
            event_queue.put_nowait(None)

    producer = asyncio.create_task(produce_events())
    try:
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        if not producer.done():
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer
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
        _sse(
            system,
            provider,
            messages,
            prompt_cache_key=_document_prompt_cache_key(document_id, profile.model_id),
        ),
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
    conversation = None
    if body.conversation_id is not None:
        conversation = session.get(ChatConversation, body.conversation_id)
        if conversation is None or conversation.document_id != document_id:
            raise HTTPException(status_code=404, detail="对话不存在")

    provider = get_provider(profile)
    system = _build_document_system(document, session)  # 静态，利于缓存
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    conversation_turn = len(messages)
    reused_pages: list[int] = []
    reused_context_truncated = False
    if conversation is not None and messages and messages[-1]["role"] == "user":
        recent_context, reused_pages, reused_context_truncated = build_recent_page_context(
            session,
            conversation_id=conversation.id,
            document_id=document_id,
        )
        if recent_context:
            # 动态证据必须放在持久历史 + 当前用户问题之后，且不会被前端存回历史。
            # 如此不同页面仅会影响本轮输入尾部，不破坏稳定历史前缀的缓存。
            messages.append({"role": "user", "content": recent_context})

    return StreamingResponse(
        _sse(
            system,
            provider,
            messages,
            tool_document_id=document_id,
            tool_current_page=current_page,
            prompt_cache_key=_document_prompt_cache_key(document_id, profile.model_id),
            conversation_id=conversation.id if conversation is not None else None,
            conversation_turn=conversation_turn if conversation is not None else None,
            reused_pages=reused_pages,
            reused_context_truncated=reused_context_truncated,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
