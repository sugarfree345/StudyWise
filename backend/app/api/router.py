from fastapi import APIRouter

from app.api.routes import chat, documents, pages

api_router = APIRouter()
api_router.include_router(documents.router)
api_router.include_router(pages.router)
api_router.include_router(chat.router)
