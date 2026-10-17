from typing import Optional, List
from pydantic import BaseModel, Field
from interview_agent.schemas.evaluation import EvaluationStatus, DimensionScore

class ActiveQuestionState(BaseModel):
    """Tracks active question and candidate answer progress in real-time."""
    question_id: str
    question_text: str
    asked_at: float
    is_follow_up: bool = False
    parent_question_id: Optional[str] = None
    accumulated_answer: str = ""
    answer_start_time: Optional[float] = None
    last_answer_update: Optional[float] = None
    is_evaluating: bool = False
    is_completed: bool = False
    uncertain_association: bool = False
