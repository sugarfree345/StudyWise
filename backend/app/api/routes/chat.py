"""LLM 对话接口。

设计要点：
- 后端无状态，前端每次带全量对话历史（messages），简单起步，以后再落库。
- 当前页的文字由后端注入成 system 提示，前端不用自己拼上下文。
- 走 SSE 流式返回；provider 抛错时以 error 事件收尾，而不是中途 500。
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session

from app.db import get_session
from app.models import Document
from app.schemas.chat import ChatRequest
from app.services import pdf_service
from app.services.llm import get_provider
from app.services.llm.profiles import PublicProfile, get_profile, load_profiles

router = APIRouter(tags=["chat"])


@router.get("/models", response_model=list[PublicProfile])
def list_models() -> list[PublicProfile]:
    """列出已配置的模型档案（不含 api_key）。"""
    return [
        PublicProfile(name=p.name, style=p.style, model_id=p.model_id)
        for p in load_profiles().values()
    ]


def _build_system(document: Document, page_number: int) -> str:
    text = pdf_service.get_page_text(Path(document.stored_path), page_number)
    return (
        f"你是一个学习辅助助手。用户正在阅读《{document.filename}》的第 {page_number} 页。\n"
        f"以下是本页的文字内容：\n\n{text}\n\n"
        "请围绕本页内容回答用户的提问，必要时可以出小测验。"
    )


async def _sse(system: str, provider, messages) -> AsyncIterator[str]:
    try:
        async for delta in provider.stream_chat(system=system, messages=messages):
            yield f"data: {json.dumps({'type': 'delta', 'text': delta}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as exc:  # noqa: BLE001 — 把上游错误变成流内 error 事件
        logger.exception("LLM 流式调用失败")
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"


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
    system = _build_system(document, page_number)
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    return StreamingResponse(
        _sse(system, provider, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
