"""Jitsi Meet integration package for the Interview Intelligence Agent."""
from interview_agent.integrations.jitsi.schemas import (
    JitsiRoomConfig,
    JitsiTranscriptEvent,
    JitsiWebhookPayload,
    JitsiDeploymentType,
)
from interview_agent.integrations.jitsi.room_manager import jitsi_room_manager, JitsiRoomManager
from interview_agent.integrations.jitsi.adapter import jitsi_adapter, JitsiTranscriptionAdapter
from interview_agent.integrations.jitsi.routes import router as jitsi_router

__all__ = [
    "JitsiRoomConfig",
    "JitsiTranscriptEvent",
    "JitsiWebhookPayload",
    "JitsiDeploymentType",
    "jitsi_room_manager",
    "JitsiRoomManager",
    "jitsi_adapter",
    "JitsiTranscriptionAdapter",
    "jitsi_router",
]
