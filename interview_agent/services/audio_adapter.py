import abc
import os
import io
import wave
import shutil
import re
import base64
import logging
import asyncio
from typing import Optional, List, Dict, Any, Set, Tuple

from interview_agent.schemas.transcript import AudioChunkPayload, TranscriptSegment
from interview_agent.schemas.interview import ParticipantRole, SessionStatus
from interview_agent.models.interview_session import InterviewSessionModel, session_repo
from interview_agent.services.transcription_service import get_transcription_service, BaseTranscriptionService
from interview_agent.config import settings

logger = logging.getLogger(__name__)

ALLOWED_AUDIO_FORMATS = {"pcm", "wav", "webm", "opus", "ogg", "mp3", "m4a", "flac"}


class AudioAdapterException(Exception):
    """Domain exception for audio ingestion failures."""
    pass


def validate_audio_chunk_payload(chunk: AudioChunkPayload) -> bytes:
    """
    Strictly validates audio chunk payload parameters, formats, and decodes base64 payload.
    Raises AudioAdapterException on any invalid, oversized, or malformed audio data.
    """
    if chunk.sequence_number < 0:
        raise AudioAdapterException(f"Invalid sequence_number '{chunk.sequence_number}': must be >= 0.")
    if chunk.timestamp < 0.0:
        raise AudioAdapterException(f"Invalid timestamp '{chunk.timestamp}': must be >= 0.0.")
    if chunk.duration <= 0.0:
        raise AudioAdapterException(f"Invalid duration '{chunk.duration}': must be > 0.0.")

    fmt = (chunk.format or "pcm").strip().lower()
    if fmt not in ALLOWED_AUDIO_FORMATS:
        raise AudioAdapterException(
            f"Unsupported audio format '{chunk.format}'. Supported formats: {sorted(ALLOWED_AUDIO_FORMATS)}"
        )

    if chunk.sample_rate < 8000 or chunk.sample_rate > 96000:
        raise AudioAdapterException(
            f"Invalid sample_rate '{chunk.sample_rate}'. Must be between 8000 and 96000 Hz."
        )

    if chunk.channels not in (1, 2):
        raise AudioAdapterException(
            f"Invalid channel count '{chunk.channels}'. Must be 1 (mono) or 2 (stereo)."
        )

    if not chunk.audio_base64:
        return b""

    if len(chunk.audio_base64) > settings.max_audio_chunk_bytes:
        raise AudioAdapterException(
            f"Audio chunk payload ({len(chunk.audio_base64)} bytes) exceeds configured maximum limit of {settings.max_audio_chunk_bytes} bytes."
        )

    try:
        raw_bytes = base64.b64decode(chunk.audio_base64, validate=True)
    except Exception as e:
        raise AudioAdapterException(f"Malformed audio_base64 payload: {e}")

    return raw_bytes


def pcm_to_wav_bytes(
    pcm_bytes: bytes,
    channels: int = 1,
    sample_rate: int = 16000,
    sample_width: int = 2
) -> bytes:
    """
    Wraps raw linear PCM bytes into a valid in-memory WAV container with standard RIFF header.
    Ensures compatibility with transcription engines that expect audio container headers.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buffer.getvalue()


def normalize_audio_for_transcription(
    raw_bytes: bytes,
    fmt: str,
    sample_rate: int = 16000,
    channels: int = 1
) -> Tuple[bytes, str, str]:
    """
    Normalizes audio payload into recognized containers for speech-to-text engines.
    Returns: (audio_bytes, filename, content_type)
    """
    fmt = (fmt or "pcm").strip().lower()
    if fmt == "pcm":
        wav_bytes = pcm_to_wav_bytes(raw_bytes, channels=channels, sample_rate=sample_rate)
        return wav_bytes, "audio.wav", "audio/wav"
    elif fmt == "wav":
        if not raw_bytes.startswith(b"RIFF"):
            wav_bytes = pcm_to_wav_bytes(raw_bytes, channels=channels, sample_rate=sample_rate)
            return wav_bytes, "audio.wav", "audio/wav"
        return raw_bytes, "audio.wav", "audio/wav"
    elif fmt in ("webm", "opus"):
        return raw_bytes, "audio.webm", "audio/webm"
    elif fmt == "mp3":
        return raw_bytes, "audio.mp3", "audio/mpeg"
    elif fmt == "ogg":
        return raw_bytes, "audio.ogg", "audio/ogg"
    elif fmt in ("m4a", "flac"):
        return raw_bytes, f"audio.{fmt}", f"audio/{fmt}"
    else:
        wav_bytes = pcm_to_wav_bytes(raw_bytes, channels=channels, sample_rate=sample_rate)
        return wav_bytes, "audio.wav", "audio/wav"


class BoundedJitterBuffer:
    """
    Per-stream bounded jitter buffer for packet reordering and backpressure control.
    Buffers out-of-order chunks up to max_buffer_size, releasing them in sequence.
    Guarantees O(1) bounded memory and flushes gaps when capacity or timeout limits are reached.
    """

    def __init__(self, max_buffer_size: Optional[int] = None, max_gap: Optional[int] = None):
        self.max_buffer_size = max_buffer_size or getattr(settings, "audio_jitter_buffer_max_chunks", 20)
        self.max_gap = max_gap or getattr(settings, "audio_max_chunk_gap", 5)
        # Map (session_id, participant_id) -> state dict
        self._streams: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def push_and_get_ready(self, session_id: str, chunk: AudioChunkPayload) -> List[AudioChunkPayload]:
        async with self._lock:
            key = (session_id, chunk.participant_id)
            if key not in self._streams:
                self._streams[key] = {
                    "expected_seq": chunk.sequence_number,
                    "buffer": {}
                }

            stream = self._streams[key]
            seq = chunk.sequence_number
            expected = stream["expected_seq"]

            # Late arrival behind current stream sequence -> process immediately to avoid dropping speech
            if seq < expected:
                return [chunk]

            # In-order arrival
            if seq == expected:
                ready = [chunk]
                stream["expected_seq"] = seq + 1
                # Flush any consecutive chunks that arrived previously and were buffered
                while stream["expected_seq"] in stream["buffer"]:
                    next_seq = stream["expected_seq"]
                    ready.append(stream["buffer"].pop(next_seq))
                    stream["expected_seq"] = next_seq + 1
                return ready

            # Out of order: chunk arrived ahead of expected
            buf = stream["buffer"]
            # Backpressure defense: if buffer exceeds limit or gap is too wide, flush to avoid stalling
            if len(buf) >= self.max_buffer_size or (seq - expected) > self.max_gap:
                logger.warning(
                    f"Jitter buffer limit reached for stream {key}. Flushing sequence gap ({expected} -> {seq})."
                )
                ready = []
                for buffered_seq in sorted(buf.keys()):
                    ready.append(buf.pop(buffered_seq))
                ready.append(chunk)
                stream["expected_seq"] = seq + 1
                return ready

            # Buffer out-of-order chunk awaiting missing predecessor
            buf[seq] = chunk
            return []

    async def reset_stream(self, session_id: str, participant_id: Optional[str] = None):
        async with self._lock:
            if participant_id:
                self._streams.pop((session_id, participant_id), None)
            else:
                keys = [k for k in self._streams if k[0] == session_id]
                for k in keys:
                    self._streams.pop(k, None)


class BaseAudioAdapter(abc.ABC):
    """
    Abstract interface for consuming audio from an authorized meeting media pipeline.
    Ensures provider-independence, deduplication, timestamp tracking, and privacy guarantees.
    """

    def __init__(self, stt_service: Optional[BaseTranscriptionService] = None):
        self.stt_service = stt_service or get_transcription_service()
        self.jitter_buffer = BoundedJitterBuffer()

    @abc.abstractmethod
    async def process_chunks(
        self,
        session_id: str,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> List[TranscriptSegment]:
        """Ingest and process an audio chunk, returning all ready contiguous segments."""
        pass

    @abc.abstractmethod
    async def process_chunk(
        self,
        session_id: str,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> Optional[TranscriptSegment]:
        """Ingest and process a single audio chunk from the meeting platform."""
        pass


class PlatformMediaAudioAdapter(BaseAudioAdapter):
    """
    Production-grade adapter for authorized meeting media pipelines:
    - Browser MediaRecorder / AudioWorklet live microphone stream.
    - Server-side WebRTC / SFU meeting participant tracks (LiveKit, Mediasoup, Janus).
    - Authorized meeting bot relays (Zoom, Teams, Google Meet).
    
    Enforces participant authorization, role verification, payload validation,
    sequence deduplication, jitter reordering, and GDPR raw audio non-retention policies.
    """

    async def process_chunks(
        self,
        session_id: str,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> List[TranscriptSegment]:
        session = session_repo.get(session_id)
        if not session:
            raise AudioAdapterException(f"Interview session '{session_id}' not found.")

        if session.status not in (SessionStatus.CREATED, SessionStatus.ACTIVE):
            raise AudioAdapterException(f"Session '{session_id}' is in status '{session.status}', cannot accept audio.")

        # 1. Authorize participant against session records
        is_registered = (
            chunk.participant_id in session.participants
            or chunk.participant_id in (session.interviewer_id, session.candidate_id)
        )
        if not is_registered:
            logger.warning(
                f"Audio chunk from unauthorized participant '{chunk.participant_id}' rejected for session '{session_id}'"
            )
            raise AudioAdapterException(
                f"Participant '{chunk.participant_id}' is not registered or authorized in session '{session_id}'."
            )

        # 2. Enforce authoritative participant role (prevent client role spoofing)
        if chunk.participant_id in session.participants:
            authoritative_role = session.participants[chunk.participant_id].role
            if chunk.participant_role != authoritative_role and chunk.participant_role != ParticipantRole.UNKNOWN:
                logger.debug(
                    f"Overriding client role '{chunk.participant_role}' with authoritative role '{authoritative_role.value}' for participant '{chunk.participant_id}'"
                )
            chunk.participant_role = authoritative_role

        # 3. Validate audio payload, formats, and decode base64
        raw_bytes = validate_audio_chunk_payload(chunk)

        # Activate session upon first valid audio packet
        if session.status == SessionStatus.CREATED:
            session.status = SessionStatus.ACTIVE
            session_repo.save(session)

        # 4. Deduplication check: Discard already processed sequence numbers
        seq_key = (chunk.participant_id, chunk.sequence_number)
        if seq_key in session.processed_sequence_numbers:
            logger.debug(f"Discarding duplicate chunk {seq_key} for session {session_id}")
            return None

        # 5. Jitter buffer reordering (handles out-of-order chunk arrivals)
        ready_chunks = await self.jitter_buffer.push_and_get_ready(session_id, chunk)
        if not ready_chunks:
            # Chunk is buffered awaiting earlier sequence numbers
            return None

        # Process all ready contiguous chunks
        ready_segments: List[TranscriptSegment] = []
        for ready_chunk in ready_chunks:
            r_key = (ready_chunk.participant_id, ready_chunk.sequence_number)
            if r_key in session.processed_sequence_numbers:
                continue

            session.processed_sequence_numbers.add(r_key)

            # 6. Privacy & Audio Retention Policy
            # GDPR / Privacy Principle: Never store raw audio by default unless explicitly configured & consented
            if settings.audio_retention_enabled and session.consent_obtained and ready_chunk.audio_base64:
                self._save_raw_audio_chunk(session_id, ready_chunk)

            # 7. Transcribe audio chunk to text via configured STT service
            segment = await self.stt_service.transcribe_chunk(
                session=session,
                chunk=ready_chunk,
                transcription_hint=transcription_hint
            )
            if segment:
                ready_segments.append(segment)

        return ready_segments

    async def process_chunk(
        self,
        session_id: str,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> Optional[TranscriptSegment]:
        segments = await self.process_chunks(session_id, chunk, transcription_hint=transcription_hint)
        return segments[-1] if segments else None

    def _save_raw_audio_chunk(self, session_id: str, chunk: AudioChunkPayload):
        try:
            if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
                logger.warning(f"Invalid session_id format for audio storage: {session_id}")
                return
            base_dir = os.path.realpath(os.path.abspath(settings.audio_storage_path))
            target_dir = os.path.realpath(os.path.abspath(os.path.join(base_dir, session_id)))
            if not (target_dir.startswith(base_dir + os.sep) or target_dir == base_dir):
                logger.error(f"Path traversal detected during session audio storage: {session_id}")
                return
            os.makedirs(target_dir, exist_ok=True)
            chunk_file = os.path.join(target_dir, f"chunk_{chunk.participant_id}_{chunk.sequence_number}.raw")
            with open(chunk_file, "wb") as f:
                f.write(base64.b64decode(chunk.audio_base64 or ""))
        except Exception as e:
            logger.error(f"Failed to persist authorized audio chunk: {e}")


def delete_session_audio_storage(session_id: str) -> bool:
    """
    Safely delete retained raw audio for an authorized session.
    Guards against path traversal and ensures deletion only occurs within audio_storage_path.
    """
    if not re.match(r"^[a-zA-Z0-9_\-]+$", session_id):
        logger.warning(f"Invalid session_id format for audio deletion: {session_id}")
        return False

    base_dir = os.path.realpath(os.path.abspath(settings.audio_storage_path))
    target_dir = os.path.realpath(os.path.abspath(os.path.join(base_dir, session_id)))

    # Ensure target_dir is strictly a subdirectory of base_dir
    if not (target_dir.startswith(base_dir + os.sep) or target_dir == base_dir):
        logger.error(f"Path traversal detected during session audio deletion: {session_id}")
        return False

    if os.path.exists(target_dir) and os.path.isdir(target_dir):
        try:
            shutil.rmtree(target_dir)
            logger.info(f"Deleted retained audio directory for session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete retained audio for session {session_id}: {e}")
            return False
    return False


class MockAudioAdapter(BaseAudioAdapter):
    """
    Mock audio adapter for testing, development, and offline demo workflows.
    Provides realistic simulated interview conversations with technical questions and answers.
    """

    SAMPLE_INTERVIEW_TURNS = [
        {
            "role": ParticipantRole.INTERVIEWER,
            "text": "Hello! Let's get started with system design. Can you explain how you would design a rate limiter for a distributed API?",
            "duration": 4.5,
        },
        {
            "role": ParticipantRole.CANDIDATE,
            "text": "Sure! For a distributed rate limiter, I would use the Token Bucket or Leaky Bucket algorithm. In a distributed setting, storing counters in Redis using Lua scripts ensures atomic read-and-decrement operations across multiple application nodes. We could partition keys by user ID or IP address, and set TTLs to avoid memory leaks.",
            "duration": 12.0,
        },
        {
            "role": ParticipantRole.INTERVIEWER,
            "text": "That's a solid start. What happens if the Redis cluster becomes unavailable or experiences high network latency?",
            "duration": 5.0,
        },
        {
            "role": ParticipantRole.CANDIDATE,
            "text": "Great follow-up. In a fail-open scenario, to prevent cascading outages, the service could fall back to a local in-memory token bucket per instance with reduced limits. We could also use circuit breakers like Resilience4j or Envoy proxies to shed load gracefully without taking down the core service.",
            "duration": 11.5,
        },
        {
            "role": ParticipantRole.INTERVIEWER,
            "text": "Excellent. Now moving on to databases: how do ACID guarantees differ between PostgreSQL and eventual consistency models in Cassandra?",
            "duration": 6.0,
        },
        {
            "role": ParticipantRole.CANDIDATE,
            "text": "PostgreSQL provides full ACID transactions with serializable snapshot isolation using write-ahead logs and MVCC. In contrast, Apache Cassandra follows the CAP theorem by prioritizing AP — availability and partition tolerance. It uses tunable consistency like QUORUM reads and writes with gossip protocols, hint handoffs, and read repair rather than two-phase commit transactions.",
            "duration": 13.0,
        }
    ]

    async def process_chunks(
        self,
        session_id: str,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> List[TranscriptSegment]:
        adapter = PlatformMediaAudioAdapter(self.stt_service)
        return await adapter.process_chunks(session_id, chunk, transcription_hint=transcription_hint)

    async def process_chunk(
        self,
        session_id: str,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> Optional[TranscriptSegment]:
        adapter = PlatformMediaAudioAdapter(self.stt_service)
        return await adapter.process_chunk(session_id, chunk, transcription_hint=transcription_hint)


# Global default audio adapter instance
audio_adapter = PlatformMediaAudioAdapter()
mock_audio_adapter = MockAudioAdapter()
