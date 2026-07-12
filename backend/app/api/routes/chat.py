"""LLM 对话接口。

设计要点：
- 后端无状态，前端每次带全量对话历史（messages），简单起步，以后再落库。
- 当前页随每条用户问题由前端一并写入历史；旧问题的页码永不改写，
  让后续请求严格追加在先前提示之后，利于提示缓存。
- 走 SSE 流式返回；provider 抛错时以 error 事件收尾，而不是中途 500。
"""

import json
from hashlib import sha256
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session, select

from app.db import engine, get_session
from app.models import Document, DocumentPage
from app.schemas.chat import ChatRequest
from app.services.llm import get_provider
from app.services.llm.base import Usage
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

    # 工具清单不写进提示词：模型已从 API 的 tools 参数拿到完整 schema，这里只给行为约定。
    lines = [
        f"你是一个学习辅助助手，正在陪用户阅读《{document.filename}》，"
        f"全书共 {document.page_count} 页。",
        "",
        "你默认看不到页面内容，必须主动调用工具按需获取正文与图片，不要凭空编造。",
        "每条用户消息末尾的 [ui_page=N] 表示该消息发送时界面停留在第 N 页。"
        "当问题需要当前页信息、需要解析「这里/当前页/本页/这个公式」等指代，或规划工具读取范围时，"
        "可将 N 作为定位参考，并结合用户问题、对话历史与已有内容决定应读取当前页、其他页或无需读取文档。",
        "确定需要当前页内容时用 get_text 精确读取第 N 页。若读到的页面是解答、推导、证明、续页，"
        "引用前文/前式，或含有未定义的符号与条件，必须继续用 get_text 补读最少必要的相关页后再回答。",
        "用户提到概念、公式或术语却不知道页码、且历史无法定位时，先用 search_document 找候选页，"
        "再读取命中页；若仍无法唯一确定对象，应简洁追问，不能擅自读取当前页或编造。",
        "跨页追问时保持整段对话连贯。",
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

    usage = Usage()
    try:
        async for delta in provider.stream_chat(
            system=system,
            messages=messages,
            tools=tools,
            tool_runner=tool_runner,
            usage=usage,
            prompt_cache_key=prompt_cache_key,
        ):
            yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        # 一次提问（可能含多轮工具调用）的累计 token 用量，供前端展示。
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "usage",
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cached_tokens": usage.cached_tokens,
                    "total_tokens": usage.total_tokens,
                }
            )
            + "\n\n"
        )
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
    provider = get_provider(profile)
    system = _build_document_system(document, session)  # 静态，利于缓存
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    return StreamingResponse(
        _sse(
            system,
            provider,
            messages,
            tool_document_id=document_id,
            tool_current_page=current_page,
            prompt_cache_key=_document_prompt_cache_key(document_id, profile.model_id),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
