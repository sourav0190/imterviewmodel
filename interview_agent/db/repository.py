import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import joinedload


from interview_agent.db.connection import get_db_session
from interview_agent.db.models import (
    SessionORM,
    TranscriptSegmentORM,
    InterviewNoteORM,
    AnswerEvaluationORM,
    FinalReportORM,
)
from interview_agent.models.interview_session import InterviewSessionModel
from interview_agent.schemas.interview import (
    InterviewSessionCreate,
    SessionStatus,
    ParticipantRole,
    InterviewRubricConfig,
)
from interview_agent.schemas.transcript import TranscriptSegment
from interview_agent.schemas.evaluation import (
    AnswerEvaluation,
    InterviewNote,
    FinalReport,
    EvaluationStatus,
    DimensionScore,
)

logger = logging.getLogger(__name__)


def orm_to_domain(orm: SessionORM) -> InterviewSessionModel:
    """Map a SQLAlchemy SessionORM record to domain InterviewSessionModel."""
    rubric_cfg = None
    if orm.rubric_config:
        try:
            rubric_cfg = InterviewRubricConfig.model_validate(orm.rubric_config)
        except Exception as e:
            logger.warning(f"Failed to deserialize rubric config: {e}")

    data = InterviewSessionCreate(
        title=orm.title,
        candidate_id=orm.candidate_id,
        candidate_name=orm.candidate_name,
        interviewer_id=orm.interviewer_id,
        interviewer_name=orm.interviewer_name,
        organization_id=orm.organization_id,
        owner_id=orm.owner_id,
        rubric_config=rubric_cfg,
        consent_obtained=orm.consent_obtained,
        metadata=orm.session_metadata or {}
    )

    session = InterviewSessionModel(data, session_id=orm.session_id)
    session.status = SessionStatus(orm.status)
    session.created_at = orm.created_at
    session.updated_at = orm.updated_at

    # Map transcript segments
    session.transcript_segments = []
    for seg in sorted(orm.transcript_segments, key=lambda s: s.start_time):
        t_seg = TranscriptSegment(
            segment_id=seg.segment_id,
            session_id=seg.session_id,
            speaker_id=seg.speaker_id,
            speaker_name=seg.speaker_name,
            speaker_role=ParticipantRole(seg.speaker_role) if seg.speaker_role in ParticipantRole._value2member_map_ else ParticipantRole.UNKNOWN,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=seg.text,
            is_final=seg.is_final,
            confidence=seg.confidence,
            language=seg.language,
            sequence_number=seg.sequence_number,
        )
        session.transcript_segments.append(t_seg)
        if seg.sequence_number is not None:
            session.processed_sequence_numbers.add(f"{seg.speaker_id}_{seg.sequence_number}")
            session.processed_sequence_numbers.add((seg.speaker_id, seg.sequence_number))

    # Map interview notes
    session.notes = []
    for n in sorted(orm.notes, key=lambda n: n.start_time):
        session.notes.append(InterviewNote(
            note_id=n.note_id,
            session_id=n.session_id,
            question_id=n.question_id,
            question_text=n.question_text,
            answer_summary=n.answer_summary,
            key_concepts=n.key_concepts or [],
            examples_provided=n.examples_provided or [],
            omissions=n.omissions or [],
            follow_up_points=n.follow_up_points or [],
            start_time=n.start_time,
            end_time=n.end_time,
            created_at=n.created_at
        ))

    # Map evaluations
    session.evaluations = []
    for ev in sorted(orm.evaluations, key=lambda e: e.answer_start_time):
        dim_scores = []
        for s in (ev.scores or []):
            if isinstance(s, dict):
                dim_scores.append(DimensionScore(**s))
            elif isinstance(s, DimensionScore):
                dim_scores.append(s)

        expl = ev.explanation or ""
        eval_method = "llm" if "[Evaluation Method: OpenAI" in expl else ("deterministic_fallback" if "[Fallback Notice:" in expl else "deterministic")
        is_fb = "[Fallback Notice:" in expl

        session.evaluations.append(AnswerEvaluation(
            evaluation_id=ev.evaluation_id,
            session_id=ev.session_id,
            question_id=ev.question_id,
            question_text=ev.question_text,
            candidate_answer_text=ev.candidate_answer_text,
            answer_start_time=ev.answer_start_time,
            answer_end_time=ev.answer_end_time,
            status=EvaluationStatus(ev.status) if ev.status in EvaluationStatus._value2member_map_ else EvaluationStatus.PENDING,
            scores=dim_scores,
            overall_score=ev.overall_score,
            max_overall_score=ev.max_overall_score,
            overall_percentage=ev.overall_percentage,
            confidence=ev.confidence,
            explanation=expl,
            is_rubric_based=ev.is_rubric_based,
            uncertain_association=ev.uncertain_association,
            evaluation_method=eval_method,
            is_fallback=is_fb,
            strengths=ev.strengths or [],
            missing_concepts=ev.missing_concepts or [],
            suggested_follow_ups=ev.suggested_follow_ups or [],
            created_at=ev.created_at,
            updated_at=ev.updated_at
        ))

    # Map final report
    if orm.final_report:
        fr = orm.final_report
        session.final_report = FinalReport(
            session_id=fr.session_id,
            candidate_name=fr.candidate_name,
            candidate_id=fr.candidate_id,
            interview_title=fr.interview_title,
            status=fr.status,
            started_at=fr.started_at,
            completed_at=fr.completed_at,
            executive_summary=fr.executive_summary,
            aggregate_score=fr.aggregate_score,
            max_possible_score=fr.max_possible_score or 5.0,
            aggregate_percentage=fr.aggregate_percentage,
            top_strengths=fr.top_strengths or [],
            key_areas_for_improvement=fr.key_areas_for_improvement or [],
            question_evaluations=session.evaluations,
            notes=session.notes
        )

    return session



class SQLAlchemySessionRepository:
    """
    Production PostgreSQL-backed session repository using SQLAlchemy 2.0.
    Ensures persistent atomic transactions, cascade deletion, and sequence idempotency.
    """

    def save(self, session: InterviewSessionModel) -> InterviewSessionModel:
        with get_db_session() as db:
            orm = (
                db.query(SessionORM)
                .options(
                    joinedload(SessionORM.transcript_segments),
                    joinedload(SessionORM.notes),
                    joinedload(SessionORM.evaluations),
                    joinedload(SessionORM.final_report),
                )
                .filter(SessionORM.session_id == session.session_id)
                .first()
            )

            session.touch()

            if not orm:
                orm = SessionORM(
                    session_id=session.session_id,
                    title=session.title,
                    candidate_id=session.candidate_id,
                    candidate_name=session.candidate_name,
                    interviewer_id=session.interviewer_id,
                    interviewer_name=session.interviewer_name,
                    organization_id=session.organization_id,
                    owner_id=session.owner_id,
                    status=session.status.value,
                    consent_obtained=session.consent_obtained,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    rubric_config=session.rubric_config.model_dump(mode="json") if session.rubric_config else None,
                    session_metadata=session.metadata,
                    participants={k: v.model_dump(mode="json") for k, v in session.participants.items()}
                )
                db.add(orm)
            else:
                orm.title = session.title
                orm.status = session.status.value
                orm.updated_at = session.updated_at
                orm.organization_id = session.organization_id
                orm.owner_id = session.owner_id
                orm.session_metadata = session.metadata

            # Synchronize transcript segments
            existing_seg_ids = {s.segment_id for s in orm.transcript_segments}
            existing_sequences = {
                (s.speaker_id, s.sequence_number)
                for s in orm.transcript_segments
                if s.sequence_number is not None
            }
            for seg in session.transcript_segments:
                if seg.segment_id not in existing_seg_ids:
                    # Determine sequence number from seg.sequence_number or processed sequences
                    seq_num = getattr(seg, "sequence_number", None)
                    if seq_num is None:
                        for seq_key in session.processed_sequence_numbers:
                            if isinstance(seq_key, tuple) and len(seq_key) == 2 and seq_key[0] == seg.speaker_id:
                                seq_num = seq_key[1]
                                break
                            elif isinstance(seq_key, str) and seq_key.startswith(f"{seg.speaker_id}_"):
                                try:
                                    seq_num = int(seq_key.split("_")[1])
                                    break
                                except (ValueError, IndexError):
                                    pass

                    # If sequence number already exists for this speaker, skip insertion (idempotent duplicate retry)
                    if seq_num is not None and (seg.speaker_id, seq_num) in existing_sequences:
                        continue

                    seg_orm = TranscriptSegmentORM(
                        segment_id=seg.segment_id,
                        session_id=session.session_id,
                        speaker_id=seg.speaker_id,
                        speaker_name=seg.speaker_name,
                        speaker_role=seg.speaker_role.value if hasattr(seg.speaker_role, "value") else str(seg.speaker_role),
                        start_time=seg.start_time,
                        end_time=seg.end_time,
                        text=seg.text,
                        is_final=seg.is_final,
                        confidence=seg.confidence,
                        language=seg.language,
                        sequence_number=seq_num
                    )
                    db.add(seg_orm)
                    existing_seg_ids.add(seg.segment_id)
                    if seq_num is not None:
                        existing_sequences.add((seg.speaker_id, seq_num))

            # Synchronize notes
            existing_note_ids = {n.note_id for n in orm.notes}
            for note in session.notes:
                if note.note_id not in existing_note_ids:
                    note_orm = InterviewNoteORM(
                        note_id=note.note_id,
                        session_id=session.session_id,
                        question_id=note.question_id,
                        question_text=note.question_text,
                        answer_summary=note.answer_summary,
                        key_concepts=note.key_concepts,
                        examples_provided=note.examples_provided,
                        omissions=note.omissions,
                        follow_up_points=note.follow_up_points,
                        start_time=note.start_time,
                        end_time=note.end_time,
                        created_at=note.created_at
                    )
                    db.add(note_orm)
                    existing_note_ids.add(note.note_id)

            # Synchronize evaluations
            existing_eval_ids = {e.evaluation_id for e in orm.evaluations}
            for ev in session.evaluations:
                if ev.evaluation_id not in existing_eval_ids:
                    eval_orm = AnswerEvaluationORM(
                        evaluation_id=ev.evaluation_id,
                        session_id=session.session_id,
                        question_id=ev.question_id,
                        question_text=ev.question_text,
                        candidate_answer_text=ev.candidate_answer_text,
                        answer_start_time=ev.answer_start_time,
                        answer_end_time=ev.answer_end_time,
                        status=ev.status.value if hasattr(ev.status, "value") else str(ev.status),
                        overall_score=ev.overall_score,
                        max_overall_score=ev.max_overall_score,
                        overall_percentage=ev.overall_percentage,
                        confidence=ev.confidence,
                        explanation=ev.explanation,
                        is_rubric_based=ev.is_rubric_based,
                        uncertain_association=ev.uncertain_association,
                        scores=[s.model_dump(mode="json") if hasattr(s, "model_dump") else s for s in ev.scores],
                        strengths=ev.strengths,
                        missing_concepts=ev.missing_concepts,
                        suggested_follow_ups=ev.suggested_follow_ups,
                        created_at=ev.created_at,
                        updated_at=ev.updated_at
                    )
                    db.add(eval_orm)
                    existing_eval_ids.add(ev.evaluation_id)

            # Synchronize final report
            if session.final_report and not orm.final_report:
                fr = session.final_report
                dim_scores = [d.model_dump(mode="json") if hasattr(d, "model_dump") else d for d in getattr(fr, "dimension_scores", [])]
                evals = [e.model_dump(mode="json") if hasattr(e, "model_dump") else e for e in getattr(fr, "question_evaluations", [])]
                fr_orm = FinalReportORM(
                    report_id=f"rep_{session.session_id}",
                    session_id=session.session_id,
                    candidate_name=fr.candidate_name,
                    candidate_id=fr.candidate_id,
                    interview_title=fr.interview_title,
                    status=fr.status,
                    started_at=fr.started_at,
                    completed_at=fr.completed_at,
                    executive_summary=fr.executive_summary,
                    aggregate_score=fr.aggregate_score,
                    max_possible_score=fr.max_possible_score or 5.0,
                    aggregate_percentage=fr.aggregate_percentage,
                    top_strengths=fr.top_strengths,
                    key_areas_for_improvement=fr.key_areas_for_improvement,
                    dimension_scores=dim_scores,
                    evaluations=evals,
                    proctoring_suspicion_score=getattr(fr, "proctoring_suspicion_score", None),
                    recommendation=getattr(fr, "recommendation", "Hire"),
                    created_at=datetime.utcnow()
                )
                db.add(fr_orm)

            db.flush()
            return session

    def get(self, session_id: str) -> Optional[InterviewSessionModel]:
        with get_db_session() as db:
            orm = (
                db.query(SessionORM)
                .options(
                    joinedload(SessionORM.transcript_segments),
                    joinedload(SessionORM.notes),
                    joinedload(SessionORM.evaluations),
                    joinedload(SessionORM.final_report),
                )
                .filter(SessionORM.session_id == session_id)
                .first()
            )
            if not orm:
                return None
            return orm_to_domain(orm)

    def list_all(self, limit: int = 50) -> List[InterviewSessionModel]:
        with get_db_session() as db:
            orms = (
                db.query(SessionORM)
                .options(
                    joinedload(SessionORM.transcript_segments),
                    joinedload(SessionORM.notes),
                    joinedload(SessionORM.evaluations),
                    joinedload(SessionORM.final_report),
                )
                .order_by(SessionORM.created_at.desc())
                .limit(limit)
                .all()
            )
            return [orm_to_domain(o) for o in orms]

    def list_for_principal(self, principal, limit: int = 50) -> List[InterviewSessionModel]:
        with get_db_session() as db:
            query = db.query(SessionORM).options(
                joinedload(SessionORM.transcript_segments),
                joinedload(SessionORM.notes),
                joinedload(SessionORM.evaluations),
                joinedload(SessionORM.final_report),
            )
            
            # Apply database-level filtering where principal has explicit boundaries
            if principal.role not in ("admin", "system"):
                if principal.organization_id:
                    query = query.filter(SessionORM.organization_id == principal.organization_id)
                elif principal.principal_id:
                    query = query.filter(
                        (SessionORM.owner_id == principal.principal_id) |
                        (SessionORM.candidate_id == principal.principal_id) |
                        (SessionORM.interviewer_id == principal.principal_id)
                    )

            orms = query.order_by(SessionORM.created_at.desc()).limit(limit).all()
            # Double check in-memory principal permissions
            return [orm_to_domain(o) for o in orms if principal.can_access_session(o)]

    def delete(self, session_id: str) -> bool:
        with get_db_session() as db:
            orm = (
                db.query(SessionORM)
                .options(
                    joinedload(SessionORM.transcript_segments),
                    joinedload(SessionORM.notes),
                    joinedload(SessionORM.evaluations),
                    joinedload(SessionORM.final_report),
                )
                .filter(SessionORM.session_id == session_id)
                .first()
            )
            if not orm:
                return False
            db.delete(orm)
            return True


    def clear(self):
        """Clears all session tables (used for test teardown)."""
        with get_db_session() as db:
            # Foreign keys cascade deletion from interview_sessions
            db.query(SessionORM).delete()
