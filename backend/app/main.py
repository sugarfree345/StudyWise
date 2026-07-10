from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.router import api_router
from app.core.config import settings
from app.db import create_db_and_tables
from app.services.llm.profiles import load_profiles, profiles_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    logger.info("StudyWise 后端已启动，数据目录：{}", settings.data_dir)
    if not profiles_path().exists():
        logger.warning(
            "尚未配置大模型。请将 backend/models.example.json 复制到 {} 并填写密钥",
            profiles_path(),
        )
    else:
        logger.info("已加载 {} 个模型档案", len(load_profiles()))
    yield


app = FastAPI(title="StudyWise API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}
