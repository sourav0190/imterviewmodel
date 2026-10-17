from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

class ParticipantRole(str, Enum):
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"
    OBSERVER = "observer"
    UNKNOWN = "unknown"

class Participant(BaseModel):
    participant_id: str
    name: str
    role: ParticipantRole = ParticipantRole.UNKNOWN
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RubricDimension(BaseModel):
    name: str
    description: str
    weight: float = 1.0
    min_score: float = 1.0
    max_score: float = 5.0

class QuestionRubric(BaseModel):
    question_id: str = Field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    question_text: str
    expected_concepts: List[str] = Field(default_factory=list)
    dimensions: List[RubricDimension] = Field(default_factory=list)
    difficulty: Optional[str] = "intermediate"

class InterviewRubricConfig(BaseModel):
    title: Optional[str] = "Standard Technical Evaluation"
    global_dimensions: List[RubricDimension] = Field(
        default_factory=lambda: [
            RubricDimension(name="Correctness", description="Accuracy and validity of technical explanation", weight=1.5),
            RubricDimension(name="Technical Depth", description="Understanding of underlying principles and trade-offs", weight=1.2),
            RubricDimension(name="Relevance", description="Directly addressing the interviewer's question", weight=1.0),
            RubricDimension(name="Reasoning & Structure", description="Logical flow, clarity, and articulation of thought process", weight=1.0),
            RubricDimension(name="Evidence & Examples", description="Concrete examples, real-world experience, or case studies cited", weight=0.8),
        ]
    )
    questions: List[QuestionRubric] = Field(default_factory=list)

class SessionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    TERMINATED = "terminated"

class InterviewSessionCreate(BaseModel):
    title: str = "Technical Interview"
    candidate_id: str
    candidate_name: str
    interviewer_id: str
    interviewer_name: Optional[str] = "Interviewer"
    organization_id: Optional[str] = None
    owner_id: Optional[str] = None
    rubric_config: Optional[InterviewRubricConfig] = None
    consent_obtained: bool = Field(
        True,
        description="Explicit candidate and interviewer consent obtained for AI assistance and transcription."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

class InterviewSessionResponse(BaseModel):
    session_id: str
    title: str
    status: SessionStatus
    candidate_id: str
    candidate_name: str
    interviewer_id: str
    interviewer_name: str
    organization_id: Optional[str] = None
    owner_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    consent_obtained: bool
    total_segments: int = 0
    total_questions: int = 0
    total_evaluations: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)

