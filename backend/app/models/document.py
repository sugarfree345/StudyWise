from datetime import datetime, timezone

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    """一组相关学习资料。"""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Document(SQLModel, table=True):
    """Project 下的一份 PDF 资料。"""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(default=1, foreign_key="project.id")
    filename: str
    stored_path: str
    page_count: int = 0
    summary: str = ""
    table_of_contents: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentProcessing(SQLModel, table=True):
    """文档 OCR 任务状态，与 Document 分表以兼容已有数据库。"""

    document_id: int = Field(foreign_key="document.id", primary_key=True)
    status: str = Field(default="pending", index=True)
    processed_pages: int = 0
    paddle_job_id: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class ChatConversation(SQLModel, table=True):
    """一份文档下可恢复的一段学习对话。"""

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    title: str = "新对话"
    profile: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatConversationMessage(SQLModel, table=True):
    """持久化的对话消息。

    ``content`` 是界面展示的文字；``request_content`` 保留带页码的模型输入，
    以便恢复后仍维持提示缓存友好的精确历史。
    """

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "position", name="uq_chat_message_conversation_position"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="chatconversation.id", index=True)
    position: int
    role: str
    content: str
    request_content: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    context_tokens: int | None = None
    context_window: int | None = None
    activity_trace: list[dict] | None = Field(default=None, sa_column=Column(JSON))
    duration_ms: int | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ChatConversationPageContext(SQLModel, table=True):
    """会话最近通过文字工具读取的页面 FIFO 队列；正文不在此复制。"""

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "page_number", name="uq_chat_page_context"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="chatconversation.id", index=True)
    page_number: int = Field(index=True)
    last_turn: int
    queue_position: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


class DocumentPage(SQLModel, table=True):
    """PaddleOCR 返回的一页结构化内容。"""

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_page_document_number"),
    )

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    page_number: int = Field(index=True)
    summary: str = ""
    text: str = ""
    markdown: str = ""
    raw_json: str = ""
    render_path: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ImageAsset(SQLModel, table=True):
    """页面图片的元数据。

    大模型第一次读到某张图后为它打标：装饰性图片（is_useful=False）
    之后不再提取原图，只用一句 summary 描述代替，以节省 token。
    """

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    page_id: int | None = Field(default=None, foreign_key="documentpage.id")
    page_number: int = Field(index=True)
    image_index: int
    source_name: str = ""
    filename: str = ""
    stored_path: str = ""
    mime_type: str = "image/png"
    summary: str = ""              # 概括简介（大模型生成）OCR 识别后先是为空, 后续第一次被大模型读到后生成, 后续不再更新
    is_useful: bool | None = None  # None = 尚未标注, 第一次被大模型读到后标注, 后续不再更新, 如果是false ,则说明这个图片就是装饰性图片, 不需要提取原图
    importance: int = 0            # 重要性评分
    retrieval_count: int = 0       # 被检索次数
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
