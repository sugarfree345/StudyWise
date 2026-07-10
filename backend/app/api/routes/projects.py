from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlmodel import Session, select

from app.api.routes.documents import _read_document, save_uploaded_document
from app.db import get_session
from app.models import Document, Project
from app.schemas.document import DocumentRead
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


def _read_project(project: Project, session: Session) -> ProjectRead:
    if project.id is None:
        raise RuntimeError("项目尚未持久化")
    document_ids = list(
        session.exec(
            select(Document.id)
            .where(Document.project_id == project.id)
            .order_by(Document.id)
        ).all()
    )
    return ProjectRead.from_model(project, document_ids)


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    body: ProjectCreate, session: Session = Depends(get_session)
) -> ProjectRead:
    project = Project(name=body.name, summary=body.summary)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read_project(project, session)


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectRead]:
    projects = session.exec(select(Project).order_by(Project.id)).all()
    return [_read_project(project, session) for project in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int, session: Session = Depends(get_session)
) -> ProjectRead:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return _read_project(project, session)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    session: Session = Depends(get_session),
) -> ProjectRead:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _read_project(project, session)


@router.get("/{project_id}/documents", response_model=list[DocumentRead])
def list_project_documents(
    project_id: int, session: Session = Depends(get_session)
) -> list[DocumentRead]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    documents = session.exec(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.id.desc())
    ).all()
    return [_read_document(document, session) for document in documents]


@router.post("/{project_id}/documents", response_model=DocumentRead, status_code=201)
async def upload_project_document(
    project_id: int,
    file: UploadFile,
    session: Session = Depends(get_session),
) -> DocumentRead:
    return await save_uploaded_document(file, project_id, session)
