"""会话级最近页面 FIFO 队列与临时尾部上下文。"""

from __future__ import annotations

from datetime import datetime, timezone

import tiktoken
from sqlmodel import Session, select

from app.models import ChatConversationPageContext, DocumentPage

MAX_RECENT_PAGES = 8
MAX_CONTEXT_TOKENS = 1_600
_ENCODING = tiktoken.get_encoding("o200k_base")


def record_pages(
    session: Session,
    *,
    conversation_id: int,
    page_numbers: list[int],
    turn: int,
) -> list[int]:
    """把工具实际返回的正文页依次放到队尾，并从队首淘汰到最多 8 页。"""
    returned_pages = list(dict.fromkeys(page_numbers))
    if not returned_pages:
        return _queue_page_numbers(session, conversation_id)

    existing = session.exec(
        select(ChatConversationPageContext)
        .where(ChatConversationPageContext.conversation_id == conversation_id)
        .order_by(
            ChatConversationPageContext.queue_position,
            ChatConversationPageContext.id,
        )
    ).all()
    by_page = {item.page_number: item for item in existing}
    queue = [item.page_number for item in existing]

    # 再次读取的页也算最新使用：先从原位置移除，再按工具返回顺序放到队尾。
    for page_number in returned_pages:
        if page_number in queue:
            queue.remove(page_number)
        queue.append(page_number)
    queue = queue[-MAX_RECENT_PAGES:]

    keep = set(queue)
    for item in existing:
        if item.page_number not in keep:
            session.delete(item)

    now = datetime.now(timezone.utc)
    returned_set = set(returned_pages)
    for position, page_number in enumerate(queue):
        item = by_page.get(page_number)
        if item is None:
            item = ChatConversationPageContext(
                conversation_id=conversation_id,
                page_number=page_number,
                last_turn=turn,
            )
        if page_number in returned_set:
            item.last_turn = turn
            item.updated_at = now
        item.queue_position = position
        session.add(item)

    session.commit()
    return queue


def build_recent_page_context(
    session: Session,
    *,
    conversation_id: int,
    document_id: int,
) -> tuple[str | None, list[int], bool]:
    """读取整个最近页面队列，构造不进入持久历史的请求尾部资料。"""
    page_numbers = _queue_page_numbers(session, conversation_id)
    if not page_numbers:
        return None, [], False

    pages = {
        page.page_number: page
        for page in session.exec(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .where(DocumentPage.page_number.in_(page_numbers))
        ).all()
    }
    chunks = [
        f"## 第 {page_number} 页\n\n{pages[page_number].markdown}".rstrip()
        for page_number in page_numbers
        if page_number in pages
    ]
    if not chunks:
        return None, [], False

    header = (
        "[最近使用页面临时参考]\n"
        "以下内容来自本会话最近通过文字工具读取的页面，只用于回答紧接着的上一条用户问题。"
        "它不是新的用户请求，也不进入长期聊天历史。若资料不足，请继续调用工具读取所需页面。\n\n"
    )
    full_context = header + "\n\n".join(chunks)
    tokens = _ENCODING.encode(full_context)
    if len(tokens) <= MAX_CONTEXT_TOKENS:
        return full_context, page_numbers, False

    marker = "\n\n[最近页面资料已截断至 1600 tokens；如信息不足请调用工具补充。]"
    marker_tokens = _ENCODING.encode(marker)
    kept_tokens = tokens[: MAX_CONTEXT_TOKENS - len(marker_tokens)]
    context = _ENCODING.decode(kept_tokens) + marker
    return context, page_numbers, True


def _queue_page_numbers(session: Session, conversation_id: int) -> list[int]:
    page_numbers = [
        item.page_number
        for item in session.exec(
            select(ChatConversationPageContext)
            .where(ChatConversationPageContext.conversation_id == conversation_id)
            .order_by(
                ChatConversationPageContext.queue_position,
                ChatConversationPageContext.id,
            )
        ).all()
    ]
    # 兼容曾运行过旧 v4 逻辑、表中遗留超过 8 页的本地数据库。
    return page_numbers[-MAX_RECENT_PAGES:]
