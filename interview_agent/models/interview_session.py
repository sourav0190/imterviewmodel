import threading
import abc
from typing import Dict, List, Optional
from datetime import datetime

import uuid

from interview_agent.schemas.interview import (
    Participant,
    ParticipantRole,
    InterviewRubricConfig,
    SessionStatus,
    InterviewSessionCreate,
    InterviewSessionResponse,
)
from interview_agent.schemas.transcript import TranscriptSegment
from interview_agent.schemas.evaluation import AnswerEvaluation, InterviewNote, FinalReport

class InterviewSessionModel:
    """Stateful domain entity for an interview session."""

    def __init__(self, data: InterviewSessionCreate, session_id: Optional[str] = None):
        self.session_id: str = session_id or f"int_{uuid.uuid4().hex[:12]}"
        self.title: str = data.title
        self.candidate_id: str = data.candidate_id
        self.candidate_name: str = data.candidate_name
        self.interviewer_id: str = data.interviewer_id
        self.interviewer_name: str = data.interviewer_name or "Interviewer"
        self.status: SessionStatus = SessionStatus.CREATED
        self.created_at: datetime = datetime.utcnow()
        self.updated_at: datetime = datetime.utcnow()
        self.consent_obtained: bool = data.consent_obtained
        self.rubric_config: InterviewRubricConfig = data.rubric_config or InterviewRubricConfig()
        self.organization_id: Optional[str] = getattr(data, "organization_id", None) or data.metadata.get("organization_id")
        self.owner_id: Optional[str] = getattr(data, "owner_id", None) or data.metadata.get("owner_id")
        self.metadata: Dict = dict(data.metadata)
        
        # Participants registered
        self.participants: Dict[str, Participant] = {
            self.interviewer_id: Participant(
                participant_id=self.interviewer_id,
                name=self.interviewer_name,
                role=ParticipantRole.INTERVIEWER
            ),
            self.candidate_id: Participant(
                participant_id=self.candidate_id,
                name=self.candidate_name,
                role=ParticipantRole.CANDIDATE
            )
        }
        
        # Conversational state
        self.transcript_segments: List[TranscriptSegment] = []
        self.notes: List[InterviewNote] = []
        self.evaluations: List[AnswerEvaluation] = []
        self.final_report: Optional[FinalReport] = None
        
        # Audio sequence tracking to avoid duplicates
        self.processed_sequence_numbers: set = set()
        
        # Active question-answer tracking state
        self.current_question_id: Optional[str] = None
        self.current_question_text: Optional[str] = None
        self.current_answer_buffer: List[TranscriptSegment] = []
        self.current_turn_role: ParticipantRole = ParticipantRole.UNKNOWN
        self.last_speech_timestamp: float = 0.0

    def touch(self):
        self.updated_at = datetime.utcnow()

    def to_response(self) -> InterviewSessionResponse:
        return InterviewSessionResponse(
            session_id=self.session_id,
            title=self.title,
            status=self.status,
            candidate_id=self.candidate_id,
            candidate_name=self.candidate_name,
            interviewer_id=self.interviewer_id,
            interviewer_name=self.interviewer_name,
            organization_id=self.organization_id,
            owner_id=self.owner_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            consent_obtained=self.consent_obtained,
            total_segments=len(self.transcript_segments),
            total_questions=len(self.notes),
            total_evaluations=len(self.evaluations),
            metadata=self.metadata
        )


class BaseSessionRepository(abc.ABC):
    """Abstract interface defining interview session persistence operations."""

    @abc.abstractmethod
    def save(self, session: InterviewSessionModel) -> InterviewSessionModel:
        pass

    @abc.abstractmethod
    def get(self, session_id: str) -> Optional[InterviewSessionModel]:
        pass

    @abc.abstractmethod
    def list_all(self, limit: int = 50) -> List[InterviewSessionModel]:
        pass

    @abc.abstractmethod
    def list_for_principal(self, principal, limit: int = 50) -> List[InterviewSessionModel]:
        pass

    @abc.abstractmethod
    def delete(self, session_id: str) -> bool:
        pass

    @abc.abstractmethod
    def clear(self):
        pass


class InMemorySessionRepository(BaseSessionRepository):
    """Thread-safe in-memory repository for unit tests and local isolated development."""

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: Dict[str, InterviewSessionModel] = {}

    def save(self, session: InterviewSessionModel) -> InterviewSessionModel:
        with self._lock:
            session.touch()
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> Optional[InterviewSessionModel]:
        with self._lock:
            return self._sessions.get(session_id)

    def list_all(self, limit: int = 50) -> List[InterviewSessionModel]:
        with self._lock:
            return list(self._sessions.values())[:limit]

    def list_for_principal(self, principal, limit: int = 50) -> List[InterviewSessionModel]:
        with self._lock:
            return [s for s in self._sessions.values() if principal.can_access_session(s)][:limit]

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def clear(self):
        with self._lock:
            self._sessions.clear()


class SessionRepositoryProxy(BaseSessionRepository):
    """
    Configurable repository proxy delegating to either SQLAlchemy (PostgreSQL / SQLite)
    or InMemory repository based on application settings.
    """

    def __init__(self):
        self._in_memory = InMemorySessionRepository()
        self._sqlalchemy = None

    def _get_active_repo(self) -> BaseSessionRepository:
        from interview_agent.config import settings
        # Use SQLAlchemy repository if postgres backend or DATABASE_URL is configured
        if settings.persistence_backend == "postgres" or settings.database_url:
            if self._sqlalchemy is None:
                from interview_agent.db.repository import SQLAlchemySessionRepository
                self._sqlalchemy = SQLAlchemySessionRepository()
            return self._sqlalchemy
        if settings.app_env.lower() in ("production", "prod"):
            raise RuntimeError(
                "CRITICAL DATABASE CONFIGURATION ERROR: Silent fallback to in-memory persistence is prohibited in production. "
                "Ensure INTERVIEW_PERSISTENCE_BACKEND='postgres' and DATABASE_URL is configured."
            )
        return self._in_memory

    def save(self, session: InterviewSessionModel) -> InterviewSessionModel:
        return self._get_active_repo().save(session)

    def get(self, session_id: str) -> Optional[InterviewSessionModel]:
        return self._get_active_repo().get(session_id)

    def list_all(self, limit: int = 50) -> List[InterviewSessionModel]:
        return self._get_active_repo().list_all(limit=limit)

    def list_for_principal(self, principal, limit: int = 50) -> List[InterviewSessionModel]:
        return self._get_active_repo().list_for_principal(principal, limit=limit)

    def delete(self, session_id: str) -> bool:
        return self._get_active_repo().delete(session_id)

    def clear(self):
        self._get_active_repo().clear()
        self._in_memory.clear()


# Default singleton instance used throughout application
session_repo = SessionRepositoryProxy()
SessionRepository = InMemorySessionRepository  # Backward-compatible alias for unit test instantiations

