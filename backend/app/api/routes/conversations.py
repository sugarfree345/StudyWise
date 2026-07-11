from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import ChatConversation, ChatConversationMessage, Document
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationMessageIn,
    ConversationSummary,
    ConversationUpdate,
)

router = APIRouter(prefix="/documents/{document_id}/conversations", tags=["conversations"])


def _conversation_or_404(document_id: int, conversation_id: int, session: Session) -> ChatConversation:
    conversation = session.get(ChatConversation, conversation_id)
    if conversation is None or conversation.document_id != document_id:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conversation


def _messages(conversation_id: int, session: Session) -> list[ChatConversationMessage]:
    return session.exec(
        select(ChatConversationMessage)
        .where(ChatConversationMessage.conversation_id == conversation_id)
        .order_by(ChatConversationMessage.position)
    ).all()


def _summary(conversation: ChatConversation, session: Session) -> ConversationSummary:
    if conversation.id is None:
        raise RuntimeError("对话尚未持久化")
    return ConversationSummary(
        id=conversation.id,
        document_id=conversation.document_id,
        title=conversation.title,
        profile=conversation.profile,
        message_count=len(_messages(conversation.id, session)),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get("", response_model=list[ConversationSummary])
def list_conversations(document_id: int, session: Session = Depends(get_session)) -> list[ConversationSummary]:
    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    conversations = session.exec(
        select(ChatConversation)
        .where(ChatConversation.document_id == document_id)
        .order_by(ChatConversation.updated_at.desc())
    ).all()
    return [_summary(conversation, session) for conversation in conversations]


@router.post("", response_model=ConversationSummary, status_code=201)
def create_conversation(
    document_id: int, body: ConversationCreate, session: Session = Depends(get_session)
) -> ConversationSummary:
    if session.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    conversation = ChatConversation(document_id=document_id, profile=body.profile, title=body.title)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return _summary(conversation, session)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    document_id: int, conversation_id: int, session: Session = Depends(get_session)
) -> ConversationDetail:
    conversation = _conversation_or_404(document_id, conversation_id, session)
    summary = _summary(conversation, session)
    return ConversationDetail(
        **summary.model_dump(),
        messages=[ConversationMessageIn.model_validate(message, from_attributes=True) for message in _messages(conversation_id, session)],
    )


@router.put("/{conversation_id}", response_model=ConversationSummary)
def replace_conversation(
    document_id: int,
    conversation_id: int,
    body: ConversationUpdate,
    session: Session = Depends(get_session),
) -> ConversationSummary:
    conversation = _conversation_or_404(document_id, conversation_id, session)
    for message in _messages(conversation_id, session):
        session.delete(message)
    # SQLite 在同一事务内不保证 DELETE 会先于同位置的新 INSERT 执行；
    # 先同步删除，避免触发 (conversation_id, position) 的唯一约束。
    session.flush()
    conversation.profile = body.profile
    if body.title is not None:
        conversation.title = body.title
    conversation.updated_at = datetime.now(timezone.utc)
    for position, message in enumerate(body.messages):
        session.add(ChatConversationMessage(conversation_id=conversation_id, position=position, **message.model_dump()))
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return _summary(conversation, session)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    document_id: int, conversation_id: int, session: Session = Depends(get_session)
) -> None:
    _conversation_or_404(document_id, conversation_id, session)
    for message in _messages(conversation_id, session):
        session.delete(message)
    session.delete(session.get(ChatConversation, conversation_id))
    session.commit()
