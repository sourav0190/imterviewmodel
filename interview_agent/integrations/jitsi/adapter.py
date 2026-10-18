import hmac
import hashlib
import logging
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from interview_agent.config import settings
from interview_agent.schemas.interview import ParticipantRole, SessionStatus
from interview_agent.schemas.transcript import TranscriptSegment
from interview_agent.models.interview_session import InterviewSessionModel, session_repo
from interview_agent.services.speaker_service import speaker_service
from interview_agent.services.interview_session_service import interview_session_service
from interview_agent.integrations.jitsi.schemas import (
    JitsiTranscriptEvent,
    JitsiWebhookPayload,
)

logger = logging.getLogger(__name__)


class JitsiTranscriptionAdapterException(Exception):
    """Domain exception for Jitsi transcription integration errors."""
    pass


class JitsiTranscriptionAdapter:
    """
    Adapter interfacing Jitsi Meet transcription services (Jigasi,
    jitsi/opus-transcriber-proxy, and 8x8 JaaS webhooks) with the
    AiProtctor Interview Intelligence Agent pipeline.
    """

    def __init__(self):
        # Bounded out-of-order buffer: session_id -> list of JitsiTranscriptEvent
        self._reorder_buffer: Dict[str, List[JitsiTranscriptEvent]] = {}
        # Track processed event IDs for idempotency
        self._processed_event_ids: Dict[str, set] = {}
        self._lock = asyncio.Lock()

    def verify_webhook_signature(
        self,
        raw_body: bytes,
        signature_header: Optional[str],
        secret: Optional[str] = None
    ) -> bool:
        """
        Validates HMAC-SHA256 signature from Jitsi bridge or webhook callbacks.
        Protects against spoofed transcript events and unauthorized callback injection.
        """
        configured_secret = secret or settings.jitsi_webhook_secret
        if not configured_secret:
            if settings.app_env.lower() in ("production", "prod"):
                logger.error("Rejecting Jitsi webhook: JITSI_WEBHOOK_SECRET is not configured in production.")
                return False
            # Allow dev mode only if explicitly anonymous dev is enabled
            return settings.allow_anonymous_dev

        if not signature_header:
            logger.warning("Rejecting Jitsi webhook: Missing X-Jitsi-Signature or Authorization signature header.")
            return False

        # Support formats like 'sha256=<hex>' or raw '<hex>'
        expected_sig = signature_header.strip()
        if expected_sig.startswith("sha256="):
            expected_sig = expected_sig[7:]

        mac = hmac.new(
            configured_secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256
        )
        calculated_hex = mac.hexdigest()

        return hmac.compare_digest(calculated_hex, expected_sig)

    def map_event_to_segment(
        self,
        session: InterviewSessionModel,
        event: JitsiTranscriptEvent
    ) -> TranscriptSegment:
        """
        Maps a Jitsi bridge transcription event to an authoritative TranscriptSegment.
        Resolves speaker role and participant identity, marking uncertain attributions clearly.
        """
        speaker_id, speaker_role, speaker_name = speaker_service.resolve_speaker(
            session=session,
            participant_id=event.participant_id,
            hinted_role=event.speaker_role,
            speaker_name=event.speaker_name
        )

        # Mark uncertain attribution if speaker cannot be definitively matched
        text = event.text.strip()
        if speaker_role == ParticipantRole.UNKNOWN:
            logger.info(f"Uncertain speaker attribution for participant '{event.participant_id}' in session '{session.session_id}'")

        segment = TranscriptSegment(
            segment_id=event.event_id,
            session_id=session.session_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            speaker_role=speaker_role,
            start_time=event.start_time,
            end_time=event.end_time if event.end_time > event.start_time else (event.start_time + 1.0),
            text=text,
            is_final=event.is_final,
            confidence=event.confidence,
            language=event.language,
            sequence_number=event.sequence_number,
            is_simulated=event.is_simulated,
            source="simulation" if event.is_simulated else "bridge"
        )
        return segment

    async def process_transcript_event(
        self,
        session_id: str,
        event: JitsiTranscriptEvent
    ) -> Optional[TranscriptSegment]:
        """
        Processes a single transcript event from Jitsi:
        - Validates session state and existence.
        - Enforces idempotency and deduplication.
        - Preserves timestamps and participant metadata.
        - Feeds into the existing interview session intelligence service.
        """
        session = session_repo.get(session_id)
        if not session:
            logger.warning(f"Session '{session_id}' not found for Jitsi transcript event")
            return None

        # Check session status
        if session.status == SessionStatus.COMPLETED:
            logger.info(f"Session '{session_id}' is completed; reactivating for live Jitsi event")
            session.status = SessionStatus.ACTIVE
            session_repo.save(session)

        # Idempotency deduplication check by event_id
        async with self._lock:
            if session_id not in self._processed_event_ids:
                self._processed_event_ids[session_id] = set()
            if event.event_id in self._processed_event_ids[session_id]:
                logger.debug(f"Skipping duplicate Jitsi event_id '{event.event_id}'")
                return None
            self._processed_event_ids[session_id].add(event.event_id)

        # Sequence-based deduplication check
        if event.sequence_number is not None:
            seq_key = (event.participant_id, event.sequence_number)
            str_key = f"{event.participant_id}_{event.sequence_number}"
            if seq_key in session.processed_sequence_numbers or str_key in session.processed_sequence_numbers:
                logger.debug(f"Skipping duplicate Jitsi sequence {seq_key}")
                return None

        # Map to domain segment
        segment = self.map_event_to_segment(session, event)

        # Ingest directly into the central interview intelligence pipeline
        # (persists to DB, notifies WebSocket, updates QA state, generates notes/evaluations)
        return await interview_session_service.ingest_transcript_segment(session_id, segment)

    async def process_ordered_events(
        self,
        session_id: str,
        events: List[JitsiTranscriptEvent]
    ) -> List[TranscriptSegment]:
        """
        Sorts and processes a batch of potentially out-of-order Jitsi transcript events.
        Events are ordered by start_time and sequence_number before ingestion.
        """
        # Sort stably by start_time, then sequence_number
        sorted_events = sorted(
            events,
            key=lambda e: (e.start_time, e.sequence_number if e.sequence_number is not None else 0)
        )

        results: List[TranscriptSegment] = []
        for ev in sorted_events:
            seg = await self.process_transcript_event(session_id, ev)
            if seg:
                results.append(seg)
        return results


jitsi_adapter = JitsiTranscriptionAdapter()
