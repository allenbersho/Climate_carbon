"""API endpoint route definitions."""

from fastapi import APIRouter

from app.api.routes import auth, farmers

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(farmers.router)
