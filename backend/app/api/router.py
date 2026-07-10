from fastapi import APIRouter

from app.api.routes import chat, documents, images, pages, projects

api_router = APIRouter()
api_router.include_router(projects.router)
api_router.include_router(documents.router)
api_router.include_router(pages.router)
api_router.include_router(images.router)
api_router.include_router(chat.router)
