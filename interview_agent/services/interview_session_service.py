import asyncio
import logging
from typing import Optional, List, Dict, Set, Any
from fastapi import WebSocket

from interview_agent.schemas.interview import (
    InterviewSessionCreate,
    InterviewSessionResponse,
    SessionStatus,
    ParticipantRole,
)
from interview_agent.schemas.transcript import AudioChunkPayload, TranscriptSegment
from interview_agent.schemas.evaluation import AnswerEvaluation, InterviewNote, FinalReport
from interview_agent.models.interview_session import InterviewSessionModel, session_repo
from interview_agent.models.answer_evaluation import ActiveQuestionState
from interview_agent.services.audio_adapter import audio_adapter, MockAudioAdapter
from interview_agent.services.question_detector import question_detector
from interview_agent.services.notes_service import notes_service
from interview_agent.services.answer_evaluator import answer_evaluator
from interview_agent.services.report_service import report_service

logger = logging.getLogger(__name__)

class InterviewSessionService:
    """
    Central orchestration service for interview sessions.
    Coordinates audio intake, transcription, question tracking, notes, evaluation,
    and real-time WebSocket broadcasting.
    """

    def __init__(self):
        # Active WebSockets per session_id
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    # --- Session Management ---

    def create_session(self, data: InterviewSessionCreate, principal: Optional[Any] = None) -> InterviewSessionResponse:
        if principal:
            if not data.organization_id and getattr(principal, "organization_id", None):
                data.organization_id = principal.organization_id
            if not data.owner_id and getattr(principal, "principal_id", None):
                data.owner_id = principal.principal_id
        session = InterviewSessionModel(data)
        session_repo.save(session)
        logger.info(f"Created interview session: {session.session_id} (org={session.organization_id}, owner={session.owner_id})")
        return session.to_response()

    def get_session(self, session_id: str) -> Optional[InterviewSessionModel]:
        return session_repo.get(session_id)

    def list_sessions(self, principal: Optional[Any] = None) -> List[InterviewSessionResponse]:
        if principal:
            return [s.to_response() for s in session_repo.list_for_principal(principal)]
        return [s.to_response() for s in session_repo.list_all()]


    def update_status(self, session_id: str, new_status: SessionStatus) -> Optional[InterviewSessionModel]:
        session = session_repo.get(session_id)
        if not session:
            return None
        session.status = new_status
        session_repo.save(session)
        asyncio.create_task(self.broadcast(session_id, {
            "type": "session_status_changed",
            "session_id": session_id,
            "status": new_status.value
        }))
        return session

    # --- Real-Time Audio & Conversational Stream ---

    async def ingest_audio_chunk(
        self,
        session_id: str,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> Optional[TranscriptSegment]:
        session = session_repo.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found for audio ingestion")
            return None

        # 1. Process chunk via audio adapter -> transcribe (handles buffered/reordered chunks)
        segments = await audio_adapter.process_chunks(session_id, chunk, transcription_hint=transcription_hint)
        if not segments:
            return None

        last_seg = None
        for segment in segments:
            res = await self.ingest_transcript_segment(session_id, segment)
            if res:
                last_seg = res

        return last_seg or (segments[-1] if segments else None)

    async def ingest_transcript_segment(
        self,
        session_id: str,
        segment: TranscriptSegment
    ) -> Optional[TranscriptSegment]:
        """
        Directly inngests an authorized transcript segment (from Jitsi bridge transcriber,
        webhook, or STT service) into the interview pipeline.
        Deduplicates, persists to database, broadcasts to WebSockets, and drives QA notes & evaluations.
        """
        session = session_repo.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found for transcript segment ingestion")
            return None

        # Check deduplication against already ingested transcript segments
        for existing in session.transcript_segments:
            if existing.segment_id == segment.segment_id:
                logger.debug(f"Skipping duplicate segment_id {segment.segment_id} for session {session_id}")
                return None
            if (
                segment.sequence_number is not None
                and existing.sequence_number is not None
                and existing.speaker_id == segment.speaker_id
                and existing.sequence_number == segment.sequence_number
            ):
                logger.debug(f"Skipping duplicate sequence {segment.sequence_number} for speaker {segment.speaker_id}")
                return None

        if getattr(segment, "sequence_number", None) is not None:
            seq_key = (segment.speaker_id, segment.sequence_number)
            str_key = f"{segment.speaker_id}_{segment.sequence_number}"
            session.processed_sequence_numbers.add(seq_key)
            session.processed_sequence_numbers.add(str_key)

        # Append segment to transcript
        session.transcript_segments.append(segment)
        session.last_speech_timestamp = max(session.last_speech_timestamp, segment.end_time)
        session.touch()
        session_repo.save(session)

        # Broadcast transcript segment immediately to UI
        await self.broadcast(session_id, {
            "type": "transcript_segment",
            "segment": segment.model_dump()
        })

        # Conversational Processing (Question Detection & Answer Tracking)
        in_progress_q, completed_q = question_detector.process_segment(session, segment)

        # If a question-answer block was completed
        if completed_q:
            await self._handle_completed_question(session, completed_q)

        # Broadcast updated in-progress question/answer state
        if in_progress_q:
            await self.broadcast(session_id, {
                "type": "active_question_state",
                "state": in_progress_q.model_dump()
            })

            # Check if answer buffer qualifies for provisional evaluation
            if in_progress_q.accumulated_answer and len(in_progress_q.accumulated_answer.split()) >= 15:
                # Trigger non-blocking provisional evaluation
                asyncio.create_task(self._trigger_provisional_eval(session, in_progress_q))

        return segment

    async def _handle_completed_question(self, session: InterviewSessionModel, completed_q: ActiveQuestionState):
        logger.info(f"Completed QA turn: {completed_q.question_id} for session {session.session_id}")
        
        # 1. Generate live structured notes
        note = notes_service.generate_note(session, completed_q)
        await self.broadcast(session.session_id, {
            "type": "interview_note",
            "note": note.model_dump(mode="json")
        })

        # 2. Evaluate answer (Finalized evaluation)
        eval_result = await answer_evaluator.evaluate_answer(session, completed_q, is_provisional=False)
        await self.broadcast(session.session_id, {
            "type": "answer_evaluation",
            "evaluation": eval_result.model_dump(mode="json")
        })

    async def _trigger_provisional_eval(self, session: InterviewSessionModel, in_progress_q: ActiveQuestionState):
        try:
            prov_eval = await answer_evaluator.evaluate_answer(session, in_progress_q, is_provisional=True)
            await self.broadcast(session.session_id, {
                "type": "answer_evaluation",
                "evaluation": prov_eval.model_dump(mode="json")
            })
        except Exception as e:
            logger.debug(f"Provisional eval skipped/failed: {e}")

    async def finalize_session(self, session_id: str) -> Optional[FinalReport]:
        session = session_repo.get(session_id)
        if not session:
            return None

        # Flush any pending candidate answer in buffer
        remaining_q = question_detector.finalize_active_answer(session)
        if remaining_q:
            await self._handle_completed_question(session, remaining_q)

        session.status = SessionStatus.COMPLETED
        report = report_service.generate_final_report(session)
        session_repo.save(session)

        await self.broadcast(session_id, {
            "type": "final_report",
            "report": report.model_dump(mode="json")
        })
        return report

    # --- Mock Simulation Workflow for Testing ---

    async def run_mock_simulation(
        self,
        session_id: str,
        auto_finalize: bool = True,
        step_delay: float = 0.0
    ) -> List[TranscriptSegment]:
        """
        Runs an automated simulation of a full technical interview conversation.
        Perfect for verifying end-to-end functionality without physical microphones.
        """
        session = session_repo.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Allow re-activating if session was completed
        if session.status == SessionStatus.COMPLETED:
            session.status = SessionStatus.ACTIVE
            session_repo.save(session)

        produced_segments: List[TranscriptSegment] = []
        clock = session.transcript_segments[-1].end_time + 1.0 if session.transcript_segments else 0.0

        participant_seqs: Dict[str, int] = {}
        for seg in session.transcript_segments:
            participant_seqs[seg.speaker_id] = max(
                participant_seqs.get(seg.speaker_id, -1),
                seg.sequence_number
            )

        for turn in MockAudioAdapter.SAMPLE_INTERVIEW_TURNS:
            if step_delay > 0:
                await asyncio.sleep(step_delay)

            role = turn["role"]
            speaker_id = session.interviewer_id if role == ParticipantRole.INTERVIEWER else session.candidate_id
            duration = turn["duration"]

            cur_seq = participant_seqs.get(speaker_id, -1) + 1
            participant_seqs[speaker_id] = cur_seq

            chunk = AudioChunkPayload(
                session_id=session_id,
                participant_id=speaker_id,
                participant_role=role,
                sequence_number=cur_seq,
                timestamp=clock,
                duration=duration,
                audio_base64="UklGRi4AAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=", # Dummy 1s PCM
                format="pcm"
            )

            seg = await self.ingest_audio_chunk(
                session_id=session_id,
                chunk=chunk,
                transcription_hint=turn["text"]
            )
            if seg:
                produced_segments.append(seg)
            clock += duration

        # Finalize the interview after conversation finishes if auto_finalize is True
        if auto_finalize:
            await self.finalize_session(session_id)
        return produced_segments

    # --- WebSocket Streaming ---

    async def connect_ws(self, session_id: str, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            if session_id not in self._connections:
                self._connections[session_id] = set()
            self._connections[session_id].add(ws)

        # Send initial state snapshot upon connecting
        session = session_repo.get(session_id)
        if session:
            snapshot = {
                "type": "session_snapshot",
                "session": session.to_response().model_dump(mode="json"),
                "transcript": [s.model_dump(mode="json") for s in session.transcript_segments],
                "notes": [n.model_dump(mode="json") for n in session.notes],
                "evaluations": [e.model_dump(mode="json") for e in session.evaluations],
                "final_report": session.final_report.model_dump(mode="json") if session.final_report else None
            }
            await ws.send_json(snapshot)

    async def disconnect_ws(self, session_id: str, ws: WebSocket):
        async with self._lock:
            if session_id in self._connections:
                self._connections[session_id].discard(ws)
                if not self._connections[session_id]:
                    del self._connections[session_id]

    async def broadcast(self, session_id: str, message: dict):
        connections_to_notify = []
        async with self._lock:
            if session_id in self._connections:
                connections_to_notify = list(self._connections[session_id])

        for ws in connections_to_notify:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send WS message to client: {e}")

    async def close_session_ws(self, session_id: str, reason: str = "Session closed"):
        """Gracefully close and terminate all active WebSockets for a session."""
        connections_to_close = []
        async with self._lock:
            if session_id in self._connections:
                connections_to_close = list(self._connections[session_id])
                del self._connections[session_id]
        for ws in connections_to_close:
            try:
                await ws.close(code=1000, reason=reason)
            except Exception:
                pass

    async def delete_session(self, session_id: str, principal: Optional[Any] = None) -> bool:
        """
        Securely deletes an authorized session:
        1. Closes all active WebSockets to prevent event leakage.
        2. Safely deletes retained raw audio directory.
        3. Removes session domain model from the repository.
        """
        session = session_repo.get(session_id)
        if not session:
            return False

        if principal and hasattr(principal, "can_access_session") and not principal.can_access_session(session):
            return False

        # Close all active WebSocket streams for this session
        await self.close_session_ws(session_id, reason="Session deleted")

        # Delete any retained raw audio from disk safely
        from interview_agent.services.audio_adapter import delete_session_audio_storage, audio_adapter
        delete_session_audio_storage(session_id)
        if hasattr(audio_adapter, "jitter_buffer"):
            await audio_adapter.jitter_buffer.reset_stream(session_id)

        # Delete from repository
        return session_repo.delete(session_id)

interview_session_service = InterviewSessionService()

