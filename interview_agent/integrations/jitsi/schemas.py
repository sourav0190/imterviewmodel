from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
from pydantic import BaseModel, Field

from interview_agent.schemas.interview import ParticipantRole


class JitsiDeploymentType(str, Enum):
    PUBLIC = "public_meet_jitsi"
    SELF_HOSTED = "self_hosted"
    JAAS = "jaas_8x8"


class JitsiRoomConfig(BaseModel):
    """Configuration payload returned to authorized dashboard clients for embedding Jitsi."""
    session_id: str
    room_name: str
    server_url: str
    domain: str
    subject: str
    interviewer_name: str
    candidate_name: str
    interviewer_join_url: str
    candidate_join_url: str
    jwt_token: Optional[str] = None
    transcription_enabled: bool = True
    consent_required: bool = True
    consent_notice: str = (
        "Audio and meeting dialogue in this room are transcribed in real time for automated "
        "interview notes, key concept extraction, and technical evaluation. Raw audio is processed "
        "in memory and is never retained on disk by default. Participant consent is mandatory."
    )
    deployment_type: JitsiDeploymentType = JitsiDeploymentType.PUBLIC
    created_at: datetime = Field(default_factory=datetime.utcnow)


class JitsiParticipantInfo(BaseModel):
    """Metadata for a Jitsi meeting participant."""
    participant_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[ParticipantRole] = ParticipantRole.UNKNOWN
    joined_at: Optional[datetime] = None


class JitsiTranscriptEvent(BaseModel):
    """
    Normalized transcript event from Jitsi bridge transcription daemon
    (Jigasi, jitsi/opus-transcriber-proxy, or JaaS webhook).
    """
    event_id: str = Field(default_factory=lambda: f"jev_{uuid.uuid4().hex[:10]}")
    session_id: str
    room_name: str
    participant_id: str
    speaker_name: Optional[str] = None
    speaker_role: Optional[ParticipantRole] = None
    text: str
    start_time: float
    end_time: float
    timestamp: float = 0.0
    is_final: bool = True
    confidence: float = 1.0
    sequence_number: Optional[int] = None
    language: str = "en"
    is_simulated: bool = False


class JitsiWebhookPayload(BaseModel):
    """Generic incoming webhook structure from Jitsi, Jigasi, or 8x8 JaaS events."""
    event: Optional[str] = None
    eventType: Optional[str] = None
    room: Optional[str] = None
    fqn: Optional[str] = None
    session_id: Optional[str] = None
    sessionId: Optional[str] = None
    timestamp: Optional[float] = None
    data: Dict[str, Any] = Field(default_factory=dict)
