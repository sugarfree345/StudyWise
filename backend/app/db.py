from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  建表前确保模型已注册
from app.core.config import settings
from app.db_migrations import migrate_schema

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    migrate_schema(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
