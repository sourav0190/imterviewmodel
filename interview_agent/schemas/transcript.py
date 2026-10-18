from typing import List, Optional
from pydantic import BaseModel, Field
import uuid
from interview_agent.schemas.interview import ParticipantRole

class AudioChunkPayload(BaseModel):
    """Payload representing a single audio chunk from the meeting media pipeline."""
    session_id: str
    participant_id: str
    participant_role: Optional[ParticipantRole] = ParticipantRole.UNKNOWN
    sequence_number: int = Field(..., ge=0, description="Sequential chunk index for ordering and deduplication")
    timestamp: float = Field(..., ge=0.0, description="Audio offset in seconds or epoch timestamp")
    duration: float = Field(default=1.0, gt=0.0, description="Duration of this chunk in seconds")
    audio_base64: Optional[str] = Field(default=None, description="Base64 encoded audio bytes (PCM/WAV/WebM/Opus/MP3/OGG)")
    format: str = "pcm"
    sample_rate: int = Field(default=16000, ge=8000, le=96000)
    channels: int = Field(default=1, ge=1, le=2)

class TranscriptSegment(BaseModel):
    """Normalized transcript segment from the speech-to-text service."""
    segment_id: str = Field(default_factory=lambda: f"seg_{uuid.uuid4().hex[:10]}")
    session_id: str
    speaker_id: str
    speaker_name: str
    speaker_role: ParticipantRole
    start_time: float
    end_time: float
    text: str
    is_final: bool = True
    confidence: float = 1.0
    language: str = "en"
    sequence_number: Optional[int] = None
    is_simulated: bool = False
    source: str = Field(default="bridge", description="Source provenance: 'bridge', 'local_microphone', or 'simulation'")

class TranscriptResponse(BaseModel):
    session_id: str
    total_segments: int
    segments: List[TranscriptSegment]
