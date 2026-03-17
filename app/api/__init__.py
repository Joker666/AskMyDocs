from fastapi import APIRouter

from app.api.routes_documents import router as documents_router
from app.api.routes_health import router as health_router
from app.api.routes_query import router as query_router

api_router = APIRouter()
api_router.include_router(documents_router)
api_router.include_router(health_router)
api_router.include_router(query_router)
