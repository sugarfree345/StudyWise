from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class Document(SQLModel, table=True):
    """用户上传的一份 PDF 资料（课件 / 论文等）。"""

    id: int | None = Field(default=None, primary_key=True)
    filename: str
    stored_path: str
    page_count: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ImageAsset(SQLModel, table=True):
    """页面图片的元数据。

    大模型第一次读到某张图后为它打标：装饰性图片（is_useful=False）
    之后不再提取原图，只用一句 summary 描述代替，以节省 token。
    """

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    page_number: int = Field(index=True)
    image_index: int
    summary: str = ""              # 概括简介（大模型生成）
    is_useful: bool | None = None  # None = 尚未标注
    importance: int = 0            # 重要性评分
    retrieval_count: int = 0       # 被检索次数
