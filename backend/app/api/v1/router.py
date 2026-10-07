from fastapi import APIRouter

from app.api.v1 import analytics, approvals, auth, catalog, crm, knowledge, projects, visualization, workflow

api_router = APIRouter()
for module in (auth, projects, workflow, approvals, knowledge, crm, catalog, visualization, analytics):
    api_router.include_router(module.router)
