from fastapi import APIRouter
from interview_agent.api.routes import router as rest_router
from interview_agent.api.websocket_routes import ws_router
from interview_agent.integrations.jitsi.routes import router as jitsi_router

interview_router = APIRouter()
interview_router.include_router(rest_router)
interview_router.include_router(jitsi_router)
interview_router.include_router(ws_router, prefix="/interviews")

__all__ = ["interview_router"]
