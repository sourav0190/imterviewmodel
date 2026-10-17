import unittest
import os
import shutil
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from interview_agent.db.models import (
    Base,
    SessionORM,
    TranscriptSegmentORM,
    InterviewNoteORM,
    AnswerEvaluationORM,
    FinalReportORM,
)
from interview_agent.db.repository import SQLAlchemySessionRepository
from interview_agent.db.connection import get_db_session
from interview_agent.models.interview_session import InterviewSessionModel
from interview_agent.schemas.interview import (
    InterviewSessionCreate,
    SessionStatus,
    ParticipantRole,
    InterviewRubricConfig,
    QuestionRubric,
    RubricDimension,
)
from interview_agent.schemas.transcript import TranscriptSegment
from interview_agent.schemas.evaluation import (
    AnswerEvaluation,
    InterviewNote,
    FinalReport,
    EvaluationStatus,
    DimensionScore,
)
from interview_agent.security import Principal
from interview_agent.config import settings

TEST_DB_FILE = "test_persistence_isolated.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_FILE}"


class TestInterviewPersistenceSuite(unittest.TestCase):
    """
    Automated regression tests verifying SQLAlchemy/PostgreSQL persistence architecture:
    1. Session data survives closing and reopening repository.
    2. Transcripts, notes, evaluations, and reports persist and reload accurately.
    3. Cross-organization and unauthorized access remains blocked at query level.
    4. Session deletion cascades and deletes all dependent database records.
    5. Duplicate transcript retries do not create duplicate records (idempotency).
    6. Finalizing twice returns existing report without creating duplicates.
    7. Database failures raise clear errors rather than silently losing data.
    """

    @classmethod
    def setUpClass(cls):
        # Save original config
        cls._orig_db_url = settings.database_url
        cls._orig_backend = settings.persistence_backend

    @classmethod
    def tearDownClass(cls):
        settings.database_url = cls._orig_db_url
        settings.persistence_backend = cls._orig_backend
        if os.path.exists(TEST_DB_FILE):
            try:
                os.remove(TEST_DB_FILE)
            except Exception:
                pass

    def setUp(self):
        settings.database_url = TEST_DB_URL
        settings.persistence_backend = "postgres"
        
        # Reset engine and recreate schema in isolated test database
        from interview_agent.db import connection
        connection._engine = None
        connection._session_factory = None
        
        self.engine = connection.get_engine(TEST_DB_URL)
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.repo = SQLAlchemySessionRepository()

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        from interview_agent.db import connection
        if connection._engine:
            connection._engine.dispose()
        connection._engine = None
        connection._session_factory = None
        if os.path.exists(TEST_DB_FILE):
            try:
                os.remove(TEST_DB_FILE)
            except Exception:
                pass

    def test_session_survives_closing_and_reopening_repository(self):
        """Verify that session identity, rubrics, and status survive closing and reopening the repository."""
        rubric = InterviewRubricConfig(
            title="Senior Distributed Systems Rubric",
            questions=[
                QuestionRubric(
                    question_id="q1",
                    question_text="Explain Raft consensus.",
                    expected_concepts=["leader election", "log replication"],
                    dimensions=[RubricDimension(name="Depth", description="Deep understanding", weight=1.2)]
                )
            ]
        )
        data = InterviewSessionCreate(
            title="Distributed Systems Lead",
            candidate_id="cand_persistent_1",
            candidate_name="Grace Hopper",
            interviewer_id="int_persistent_1",
            interviewer_name="Alan Turing",
            organization_id="org_cyberdyne",
            owner_id="recruiter_sarah",
            rubric_config=rubric,
            consent_obtained=True,
            metadata={"priority": "high", "department": "Core Infrastructure"}
        )

        session = InterviewSessionModel(data, session_id="int_persistent_001")
        session.status = SessionStatus.ACTIVE
        self.repo.save(session)

        # Reopen a completely separate repository instance
        new_repo = SQLAlchemySessionRepository()
        reloaded = new_repo.get("int_persistent_001")

        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.session_id, "int_persistent_001")
        self.assertEqual(reloaded.candidate_name, "Grace Hopper")
        self.assertEqual(reloaded.interviewer_name, "Alan Turing")
        self.assertEqual(reloaded.organization_id, "org_cyberdyne")
        self.assertEqual(reloaded.owner_id, "recruiter_sarah")
        self.assertEqual(reloaded.status, SessionStatus.ACTIVE)
        self.assertEqual(reloaded.metadata.get("priority"), "high")
        self.assertEqual(reloaded.rubric_config.title, "Senior Distributed Systems Rubric")
        self.assertEqual(len(reloaded.rubric_config.questions), 1)

    def test_transcripts_notes_evaluations_and_reports_persist_correctly(self):
        """Verify that full interview conversation, notes, rubrics, and reports reload completely."""
        data = InterviewSessionCreate(
            title="Backend Architect",
            candidate_id="cand_bob",
            candidate_name="Bob Martin",
            interviewer_id="int_alice",
            organization_id="org_acme"
        )
        session = InterviewSessionModel(data, session_id="int_full_002")
        self.repo.save(session)

        # 1. Add transcript segment
        segment = TranscriptSegment(
            segment_id="seg_001",
            session_id="int_full_002",
            speaker_id="int_alice",
            speaker_name="Alice",
            speaker_role=ParticipantRole.INTERVIEWER,
            start_time=1.0,
            end_time=4.5,
            text="What is your caching strategy?",
            confidence=0.98
        )
        session.transcript_segments.append(segment)
        session.processed_sequence_numbers.add("int_alice_1")

        # 2. Add note
        note = InterviewNote(
            note_id="note_001",
            session_id="int_full_002",
            question_id="q_cache",
            question_text="What is your caching strategy?",
            answer_summary="Candidate recommended multi-layer cache with Redis and local LRU.",
            key_concepts=["redis", "lru", "cache-aside"],
            examples_provided=["Payment gateway balance cache"],
            omissions=["TTL jitter for thundering herd"],
            follow_up_points=["Ask about cache invalidation"],
            start_time=5.0,
            end_time=15.0
        )
        session.notes.append(note)

        # 3. Add evaluation
        dim_scores = [
            DimensionScore(
                dimension_name="Correctness",
                score=4.5,
                feedback="Accurate caching topology",
                evidence_quotes=["multi-layer cache with Redis"]
            )
        ]
        evaluation = AnswerEvaluation(
            evaluation_id="eval_001",
            session_id="int_full_002",
            question_id="q_cache",
            question_text="What is your caching strategy?",
            candidate_answer_text="I recommend a multi-layer cache with Redis.",
            answer_start_time=5.0,
            answer_end_time=15.0,
            status=EvaluationStatus.COMPLETE,
            scores=dim_scores,
            overall_score=4.5,
            max_overall_score=5.0,
            overall_percentage=90.0,
            strengths=["Strong architecture fundamentals"],
            confidence=0.92
        )
        session.evaluations.append(evaluation)

        # 4. Add final report
        report = FinalReport(
            session_id="int_full_002",
            candidate_name="Bob Martin",
            candidate_id="cand_bob",
            interview_title="Backend Architect",
            status="completed",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            executive_summary="Candidate demonstrated exceptional technical depth.",
            aggregate_score=4.5,
            max_possible_score=5.0,
            aggregate_percentage=90.0,
            top_strengths=["Architecture", "System Design"],
            key_areas_for_improvement=["Cache invalidation edge cases"],
            dimension_scores=dim_scores,
            evaluations=[evaluation]
        )
        session.final_report = report
        session.status = SessionStatus.COMPLETED

        # Save all through repository
        self.repo.save(session)

        # Reopen repo and verify full object graph
        reloaded = SQLAlchemySessionRepository().get("int_full_002")
        self.assertIsNotNone(reloaded)
        self.assertEqual(len(reloaded.transcript_segments), 1)
        self.assertEqual(reloaded.transcript_segments[0].text, "What is your caching strategy?")
        self.assertEqual(len(reloaded.notes), 1)
        self.assertEqual(reloaded.notes[0].key_concepts, ["redis", "lru", "cache-aside"])
        self.assertEqual(len(reloaded.evaluations), 1)
        self.assertEqual(reloaded.evaluations[0].overall_score, 4.5)
        self.assertEqual(reloaded.evaluations[0].scores[0].dimension_name, "Correctness")
        self.assertIsNotNone(reloaded.final_report)
        self.assertEqual(reloaded.final_report.aggregate_score, 4.5)
        self.assertEqual(reloaded.final_report.aggregate_percentage, 90.0)
        self.assertEqual(reloaded.final_report.top_strengths, ["Architecture", "System Design"])

    def test_cross_organization_and_unauthorized_access_remains_blocked(self):
        """Verify that organization filtering prevents cross-tenant data leaks."""
        # Session in Org Alpha
        s_alpha = InterviewSessionModel(InterviewSessionCreate(
            title="Alpha Interview", candidate_id="c_a", candidate_name="Alice Alpha",
            interviewer_id="i_a", organization_id="org_alpha"
        ), session_id="int_alpha_1")
        self.repo.save(s_alpha)

        # Session in Org Beta
        s_beta = InterviewSessionModel(InterviewSessionCreate(
            title="Beta Interview", candidate_id="c_b", candidate_name="Bob Beta",
            interviewer_id="i_b", organization_id="org_beta"
        ), session_id="int_beta_1")
        self.repo.save(s_beta)

        principal_alpha = Principal(principal_id="recruiter_a", organization_id="org_alpha", role="user")
        principal_beta = Principal(principal_id="recruiter_b", organization_id="org_beta", role="user")

        # Org Alpha list only returns Alpha
        alpha_sessions = self.repo.list_for_principal(principal_alpha)
        self.assertEqual(len(alpha_sessions), 1)
        self.assertEqual(alpha_sessions[0].session_id, "int_alpha_1")

        # Org Beta list only returns Beta
        beta_sessions = self.repo.list_for_principal(principal_beta)
        self.assertEqual(len(beta_sessions), 1)
        self.assertEqual(beta_sessions[0].session_id, "int_beta_1")

        # Org Alpha principal cannot access Beta session
        beta_session = self.repo.get("int_beta_1")
        self.assertFalse(principal_alpha.can_access_session(beta_session))
        self.assertTrue(principal_beta.can_access_session(beta_session))

    def test_cascade_deletion_removes_dependent_records(self):
        """Verify database foreign-key cascade deletes all segments, notes, evaluations, and reports."""
        session = InterviewSessionModel(InterviewSessionCreate(
            candidate_id="c1", candidate_name="User", interviewer_id="i1"
        ), session_id="int_cascade_del")
        
        session.transcript_segments.append(TranscriptSegment(
            segment_id="seg_casc", session_id="int_cascade_del", speaker_id="i1",
            speaker_name="Interviewer", speaker_role=ParticipantRole.INTERVIEWER,
            start_time=0.0, end_time=2.0, text="Hello"
        ))
        session.notes.append(InterviewNote(
            note_id="note_casc", session_id="int_cascade_del", question_id="q1",
            question_text="Q", answer_summary="A", start_time=0.0, end_time=2.0
        ))
        session.evaluations.append(AnswerEvaluation(
            evaluation_id="eval_casc", session_id="int_cascade_del", question_id="q1",
            question_text="Q", candidate_answer_text="A", answer_start_time=0.0, answer_end_time=2.0
        ))
        session.final_report = FinalReport(
            session_id="int_cascade_del", candidate_name="User", candidate_id="c1",
            interview_title="Title", status="completed", started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(), executive_summary="Summary", aggregate_score=4.0,
            max_possible_score=5.0, aggregate_percentage=80.0
        )
        self.repo.save(session)

        # Delete the session
        deleted = self.repo.delete("int_cascade_del")
        self.assertTrue(deleted)

        # Verify raw tables are empty for this session
        with self.engine.connect() as conn:
            seg_count = conn.execute(text("SELECT COUNT(*) FROM interview_transcript_segments WHERE session_id = 'int_cascade_del'")).scalar()
            note_count = conn.execute(text("SELECT COUNT(*) FROM interview_notes WHERE session_id = 'int_cascade_del'")).scalar()
            eval_count = conn.execute(text("SELECT COUNT(*) FROM interview_evaluations WHERE session_id = 'int_cascade_del'")).scalar()
            rep_count = conn.execute(text("SELECT COUNT(*) FROM interview_final_reports WHERE session_id = 'int_cascade_del'")).scalar()

            self.assertEqual(seg_count, 0)
            self.assertEqual(note_count, 0)
            self.assertEqual(eval_count, 0)
            self.assertEqual(rep_count, 0)

    def test_duplicate_transcript_retry_idempotency(self):
        """Verify that resending the same sequence number does not duplicate records in the database."""
        session = InterviewSessionModel(InterviewSessionCreate(
            candidate_id="c1", candidate_name="User", interviewer_id="i1"
        ), session_id="int_idemp")
        self.repo.save(session)

        # Add segment with sequence key
        seg1 = TranscriptSegment(
            segment_id="seg_seq_1", session_id="int_idemp", speaker_id="cand_1",
            speaker_name="Candidate", speaker_role=ParticipantRole.CANDIDATE,
            start_time=1.0, end_time=3.0, text="Answer text part 1"
        )
        session.transcript_segments.append(seg1)
        session.processed_sequence_numbers.add("cand_1_1")
        self.repo.save(session)

        # Simulate client retry with same segment ID
        self.repo.save(session)

        with self.engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM interview_transcript_segments WHERE session_id = 'int_idemp'")).scalar()
            self.assertEqual(count, 1)

    def test_finalizing_twice_idempotency(self):
        """Verify that finalizing a session twice does not produce duplicate report records."""
        session = InterviewSessionModel(InterviewSessionCreate(
            candidate_id="c1", candidate_name="User", interviewer_id="i1"
        ), session_id="int_rep_idemp")
        report = FinalReport(
            session_id="int_rep_idemp", candidate_name="User", candidate_id="c1",
            interview_title="Title", status="completed", started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(), executive_summary="Summary", aggregate_score=4.0,
            max_possible_score=5.0, aggregate_percentage=80.0
        )
        session.final_report = report
        self.repo.save(session)

        # Save again
        self.repo.save(session)

        with self.engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM interview_final_reports WHERE session_id = 'int_rep_idemp'")).scalar()
            self.assertEqual(count, 1)

    def test_database_failure_produces_clear_error(self):
        """Verify that connection failures produce clear operational errors without silent data loss."""
        from interview_agent.db.connection import get_engine, check_db_health
        bad_url = "sqlite:////nonexistent_dir_9999/unwritable.db"
        
        with self.assertRaises(Exception):
            engine = get_engine(bad_url)
            check_db_health(engine)



if __name__ == "__main__":
    unittest.main()
