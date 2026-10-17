from typing import List, Optional
from pydantic import BaseModel, Field
from interview_agent.schemas.interview import ParticipantRole

class TurnModel(BaseModel):
    """Aggregated conversational turn representing one speaker's continuous speech block."""
    turn_id: str
    session_id: str
    speaker_id: str
    speaker_name: str
    speaker_role: ParticipantRole
    start_time: float
    end_time: float
    text: str
    segment_ids: List[str] = Field(default_factory=list)
    is_question: bool = False
