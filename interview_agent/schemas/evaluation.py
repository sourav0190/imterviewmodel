from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

class EvaluationStatus(str, Enum):
    PENDING = "pending"
    PROVISIONAL = "provisional"
    COMPLETE = "complete"
    FAILED = "failed"

class DimensionScore(BaseModel):
    dimension_name: str
    score: float
    max_score: float = 5.0
    weight: float = 1.0
    feedback: str
    evidence_quotes: List[str] = Field(default_factory=list)
    evidence_timestamps: List[float] = Field(default_factory=list)

class AnswerEvaluation(BaseModel):
    evaluation_id: str = Field(default_factory=lambda: f"eval_{uuid.uuid4().hex[:10]}")
    session_id: str
    question_id: str
    question_text: str
    candidate_answer_text: str
    answer_start_time: float
    answer_end_time: float
    status: EvaluationStatus = EvaluationStatus.PENDING
    scores: List[DimensionScore] = Field(default_factory=list)
    overall_score: float = 0.0
    max_overall_score: float = 5.0
    overall_percentage: float = 0.0
    strengths: List[str] = Field(default_factory=list)
    missing_concepts: List[str] = Field(default_factory=list)
    suggested_follow_ups: List[str] = Field(default_factory=list)
    confidence: float = 0.85
    explanation: str = ""
    is_rubric_based: bool = False
    uncertain_association: bool = False
    evaluation_method: str = Field(default="deterministic", description="Method used: 'llm', 'deterministic', or 'mock'")
    is_fallback: bool = Field(default=False, description="True if evaluation fell back to local engine due to provider error/timeout")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class InterviewNote(BaseModel):
    note_id: str = Field(default_factory=lambda: f"note_{uuid.uuid4().hex[:10]}")
    session_id: str
    question_id: str
    question_text: str
    answer_summary: str
    key_concepts: List[str] = Field(default_factory=list)
    examples_provided: List[str] = Field(default_factory=list)
    omissions: List[str] = Field(default_factory=list)
    follow_up_points: List[str] = Field(default_factory=list)
    start_time: float
    end_time: float
    created_at: datetime = Field(default_factory=datetime.utcnow)

class FinalReport(BaseModel):
    session_id: str
    candidate_name: str
    candidate_id: str
    interview_title: str
    status: str
    started_at: datetime
    completed_at: datetime
    meeting_date: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    executive_summary: str
    aggregate_score: float
    max_possible_score: float
    aggregate_percentage: float
    top_strengths: List[str] = Field(default_factory=list)
    key_areas_for_improvement: List[str] = Field(default_factory=list)
    technical_concepts_discussed: List[str] = Field(default_factory=list)
    decisions_and_actions: List[str] = Field(default_factory=list)
    unanswered_questions: List[str] = Field(default_factory=list)
    question_evaluations: List[AnswerEvaluation] = Field(default_factory=list)
    notes: List[InterviewNote] = Field(default_factory=list)
    transcript_provenance: Dict[str, int] = Field(
        default_factory=dict,
        description="Breakdown of transcript segment count by source: 'bridge', 'local_microphone', 'simulation'"
    )
    proctoring_score_isolation_notice: str = (
        "Notice: Technical interview evaluations are strictly decoupled from proctoring suspicion scores. "
        "Candidate competence is assessed purely on technical accuracy, problem-solving, and communication."
    )
