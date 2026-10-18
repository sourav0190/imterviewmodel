import abc
import asyncio
from typing import Optional
import base64
import logging

from interview_agent.schemas.transcript import AudioChunkPayload, TranscriptSegment
from interview_agent.schemas.interview import ParticipantRole
from interview_agent.models.interview_session import InterviewSessionModel
from interview_agent.services.speaker_service import speaker_service
from interview_agent.config import settings

logger = logging.getLogger(__name__)

class BaseTranscriptionService(abc.ABC):
    """Abstract interface for Speech-to-Text services."""

    @abc.abstractmethod
    async def transcribe_chunk(
        self,
        session: InterviewSessionModel,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> Optional[TranscriptSegment]:
        """Convert an audio chunk payload into a normalized TranscriptSegment."""
        pass


class MockTranscriptionService(BaseTranscriptionService):
    """
    Mock STT engine for automated testing, local development, and demonstration.
    Does not require external API keys or heavy local neural network weights.
    """

    async def transcribe_chunk(
        self,
        session: InterviewSessionModel,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> Optional[TranscriptSegment]:
        speaker_id, role, name = speaker_service.resolve_speaker(
            session=session,
            participant_id=chunk.participant_id,
            hinted_role=chunk.participant_role
        )
        
        # If pre-transcribed text or hint is provided (e.g., from mock meeting simulator)
        if transcription_hint:
            text = transcription_hint.strip()
        elif chunk.audio_base64:
            # Simulated decode of audio content
            text = f"[Speech from {name} at {chunk.timestamp:.1f}s]"
        else:
            text = ""

        if not text:
            return None

        segment = TranscriptSegment(
            session_id=session.session_id,
            speaker_id=speaker_id,
            speaker_name=name,
            speaker_role=role,
            start_time=chunk.timestamp,
            end_time=chunk.timestamp + chunk.duration,
            text=text,
            is_final=True,
            confidence=0.98,
            sequence_number=chunk.sequence_number,
            is_simulated=True,
            source="simulation"
        )
        return segment


class WhisperTranscriptionService(BaseTranscriptionService):
    """
    Production-ready STT service supporting OpenAI Whisper API or OpenAI-compatible endpoints.
    Falls back gracefully if credentials or networks are unavailable.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "whisper-1"):
        self.api_key = api_key or settings.stt_api_key
        self.model = model or settings.stt_model

    async def transcribe_chunk(
        self,
        session: InterviewSessionModel,
        chunk: AudioChunkPayload,
        transcription_hint: Optional[str] = None
    ) -> Optional[TranscriptSegment]:
        # If simulation hint is given, prioritize it
        if transcription_hint:
            speaker_id, role, name = speaker_service.resolve_speaker(
                session=session,
                participant_id=chunk.participant_id,
                hinted_role=chunk.participant_role
            )
            return TranscriptSegment(
                session_id=session.session_id,
                speaker_id=speaker_id,
                speaker_name=name,
                speaker_role=role,
                start_time=chunk.timestamp,
                end_time=chunk.timestamp + chunk.duration,
                text=transcription_hint.strip(),
                is_final=True,
                confidence=0.99,
                sequence_number=chunk.sequence_number,
                is_simulated=True,
                source="simulation"
            )

        # Reject if API key is not configured when using Whisper
        if not self.api_key:
            logger.error(
                "Whisper transcription requested but INTERVIEW_STT_API_KEY is not configured. "
                "Real transcription is unavailable."
            )
            return None

        try:
            import httpx
            from interview_agent.services.audio_adapter import normalize_audio_for_transcription

            speaker_id, role, name = speaker_service.resolve_speaker(
                session=session,
                participant_id=chunk.participant_id,
                hinted_role=chunk.participant_role
            )
            raw_bytes = base64.b64decode(chunk.audio_base64 or "")
            
            # Normalize container format (PCM/WAV/WebM/MP3) for Whisper endpoint
            norm_bytes, filename, mime_type = normalize_audio_for_transcription(
                raw_bytes,
                chunk.format,
                sample_rate=chunk.sample_rate,
                channels=chunk.channels
            )

            files = {"file": (filename, norm_bytes, mime_type)}
            data = {"model": self.model, "language": settings.stt_language}
            headers = {"Authorization": f"Bearer {self.api_key}"}

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post("https://api.openai.com/v1/audio/transcriptions", files=files, data=data, headers=headers)
                if res.status_code == 200:
                    result_json = res.json()
                    transcribed_text = result_json.get("text", "").strip()
                    if transcribed_text:
                        return TranscriptSegment(
                            session_id=session.session_id,
                            speaker_id=speaker_id,
                            speaker_name=name,
                            speaker_role=role,
                            start_time=chunk.timestamp,
                            end_time=chunk.timestamp + chunk.duration,
                            text=transcribed_text,
                            is_final=True,
                            confidence=0.95,
                            sequence_number=chunk.sequence_number,
                            is_simulated=False,
                            source="local_microphone"
                        )
                elif res.status_code == 401:
                    logger.error("Whisper API authentication failed: Invalid or expired API key (HTTP 401).")
                    return None
                elif res.status_code == 429:
                    logger.error("Whisper API rate limit exceeded (HTTP 429).")
                    return None
                else:
                    err_snippet = res.text[:200] if res.text else ""
                    logger.error(f"Whisper API failed with HTTP {res.status_code}: {err_snippet}")
                    return None
        except httpx.TimeoutException:
            logger.error("Whisper transcription request timed out.")
            return None
        except httpx.RequestError as e:
            logger.error(f"Whisper transcription network connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"Whisper transcription unexpected error: {e}")
            return None

        return None


def get_transcription_service() -> BaseTranscriptionService:
    provider = settings.stt_provider.lower().strip()
    if provider == "whisper":
        return WhisperTranscriptionService()
    elif provider in ("mock", "simulated"):
        return MockTranscriptionService()
    else:
        raise ValueError(f"Unknown or unsupported STT provider '{provider}'. Supported: 'mock', 'whisper'.")
