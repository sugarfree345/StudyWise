from datetime import datetime

from pydantic import BaseModel, Field

from app.models import Project


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    summary: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = None


class ProjectRead(BaseModel):
    id: int
    name: str
    summary: str
    document_ids: list[int]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(
        cls, project: Project, document_ids: list[int]
    ) -> "ProjectRead":
        if project.id is None:
            raise ValueError("项目尚未持久化")
        return cls(
            id=project.id,
            name=project.name,
            summary=project.summary,
            document_ids=document_ids,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
