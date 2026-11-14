"""API endpoint route definitions."""

from fastapi import APIRouter

from app.api.routes import (
    activities,
    auth,
    enrollments,
    farmers,
    monitoring,
    observations,
    parcels,
    projects,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(farmers.router)
api_router.include_router(parcels.router)
api_router.include_router(projects.router)
api_router.include_router(enrollments.router)
api_router.include_router(activities.router)
api_router.include_router(observations.router)
api_router.include_router(monitoring.router)
