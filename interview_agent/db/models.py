from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import (
    Column,
    String,
    Boolean,
    Float,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SessionORM(Base):
    """
    SQLAlchemy ORM model representing an interview session.
    Persists session identity, lifecycle, ownership, metadata, and rubric configuration.
    """
    __tablename__ = "interview_sessions"

    session_id = Column(String(64), primary_key=True)
    title = Column(String(255), nullable=False, default="Technical Interview")
    candidate_id = Column(String(128), nullable=False, index=True)
    candidate_name = Column(String(255), nullable=False)
    interviewer_id = Column(String(128), nullable=False, index=True)
    interviewer_name = Column(String(255), nullable=False, default="Interviewer")
    organization_id = Column(String(128), nullable=True, index=True)
    owner_id = Column(String(128), nullable=True, index=True)
    status = Column(String(32), nullable=False, default="created", index=True)
    consent_obtained = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Serialized structures
    rubric_config = Column(JSON, nullable=True)
    session_metadata = Column(JSON, nullable=True)
    participants = Column(JSON, nullable=True)

    # Relationships with cascade deletion
    transcript_segments = relationship(
        "TranscriptSegmentORM",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="TranscriptSegmentORM.start_time"
    )
    notes = relationship(
        "InterviewNoteORM",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewNoteORM.start_time"
    )
    evaluations = relationship(
        "AnswerEvaluationORM",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AnswerEvaluationORM.answer_start_time"
    )
    final_report = relationship(
        "FinalReportORM",
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False
    )

    __table_args__ = (
        Index("idx_session_org_status", "organization_id", "status"),
        Index("idx_session_owner_created", "owner_id", "created_at"),
    )


class TranscriptSegmentORM(Base):
    """
    SQLAlchemy ORM model for transcribed speech segments.
    Stores speaker role, timestamps, text, confidence, and sequence number for idempotency.
    """
    __tablename__ = "interview_transcript_segments"

    segment_id = Column(String(64), primary_key=True)
    session_id = Column(
        String(64),
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    speaker_id = Column(String(128), nullable=False)
    speaker_name = Column(String(255), nullable=False)
    speaker_role = Column(String(32), nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    is_final = Column(Boolean, nullable=False, default=True)
    confidence = Column(Float, nullable=False, default=1.0)
    language = Column(String(16), nullable=False, default="en")
    sequence_number = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    session = relationship("SessionORM", back_populates="transcript_segments")

    __table_args__ = (
        # Prevent duplicate sequence ingestion per participant within a session
        UniqueConstraint("session_id", "speaker_id", "sequence_number", name="uq_session_speaker_sequence"),
        Index("idx_segment_session_time", "session_id", "start_time"),
    )


class InterviewNoteORM(Base):
    """
    SQLAlchemy ORM model for structured question notes.
    """
    __tablename__ = "interview_notes"

    note_id = Column(String(64), primary_key=True)
    session_id = Column(
        String(64),
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    question_id = Column(String(64), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    answer_summary = Column(Text, nullable=False)
    key_concepts = Column(JSON, nullable=False, default=list)
    examples_provided = Column(JSON, nullable=False, default=list)
    omissions = Column(JSON, nullable=False, default=list)
    follow_up_points = Column(JSON, nullable=False, default=list)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    session = relationship("SessionORM", back_populates="notes")

    __table_args__ = (
        Index("idx_note_session_question", "session_id", "question_id"),
    )


class AnswerEvaluationORM(Base):
    """
    SQLAlchemy ORM model for rubric-based and question-level evaluations.
    """
    __tablename__ = "interview_evaluations"

    evaluation_id = Column(String(64), primary_key=True)
    session_id = Column(
        String(64),
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    question_id = Column(String(64), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    candidate_answer_text = Column(Text, nullable=False)
    answer_start_time = Column(Float, nullable=False)
    answer_end_time = Column(Float, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    overall_score = Column(Float, nullable=False, default=0.0)
    max_overall_score = Column(Float, nullable=False, default=5.0)
    overall_percentage = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.85)
    explanation = Column(Text, nullable=False, default="")
    is_rubric_based = Column(Boolean, nullable=False, default=False)
    uncertain_association = Column(Boolean, nullable=False, default=False)
    
    # Complex evaluation structures serialized as JSON
    scores = Column(JSON, nullable=False, default=list)
    strengths = Column(JSON, nullable=False, default=list)
    missing_concepts = Column(JSON, nullable=False, default=list)
    suggested_follow_ups = Column(JSON, nullable=False, default=list)
    
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("SessionORM", back_populates="evaluations")

    __table_args__ = (
        Index("idx_eval_session_question", "session_id", "question_id"),
    )


class FinalReportORM(Base):
    """
    SQLAlchemy ORM model for executive interview final reports.
    """
    __tablename__ = "interview_final_reports"

    report_id = Column(String(64), primary_key=True)
    session_id = Column(
        String(64),
        ForeignKey("interview_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )
    candidate_name = Column(String(255), nullable=False)
    candidate_id = Column(String(128), nullable=False)
    interview_title = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False)
    executive_summary = Column(Text, nullable=False)
    aggregate_score = Column(Float, nullable=False)
    max_possible_score = Column(Float, nullable=False, default=5.0)
    aggregate_percentage = Column(Float, nullable=False)
    top_strengths = Column(JSON, nullable=False, default=list)
    key_areas_for_improvement = Column(JSON, nullable=False, default=list)
    dimension_scores = Column(JSON, nullable=True, default=list)
    evaluations = Column(JSON, nullable=True, default=list)
    meeting_date = Column(String(64), nullable=True)
    participants = Column(JSON, nullable=True, default=list)
    technical_concepts_discussed = Column(JSON, nullable=True, default=list)
    decisions_and_actions = Column(JSON, nullable=True, default=list)
    unanswered_questions = Column(JSON, nullable=True, default=list)
    proctoring_suspicion_score = Column(Float, nullable=True)
    recommendation = Column(String(64), nullable=True)
    transcript_provenance = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


    session = relationship("SessionORM", back_populates="final_report")
