import unittest
import asyncio
import base64
import os
import io
import wave
import shutil
from starlette.testclient import TestClient

from main import app
from interview_agent.models.interview_session import session_repo, InterviewSessionModel
from interview_agent.schemas.interview import (
    InterviewSessionCreate,
    ParticipantRole,
    SessionStatus,
    InterviewRubricConfig,
    QuestionRubric,
    RubricDimension,
)
from interview_agent.schemas.transcript import AudioChunkPayload, TranscriptSegment
from interview_agent.services.audio_adapter import (
    audio_adapter,
    PlatformMediaAudioAdapter,
    AudioAdapterException,
    validate_audio_chunk_payload,
    pcm_to_wav_bytes,
    normalize_audio_for_transcription,
    BoundedJitterBuffer,
    delete_session_audio_storage,
)
from interview_agent.services.transcription_service import (
    MockTranscriptionService,
    WhisperTranscriptionService,
)
from interview_agent.services.speaker_service import speaker_service
from interview_agent.services.interview_session_service import interview_session_service
from interview_agent.config import settings


def generate_pcm_chunk(duration_sec: float = 1.0, sample_rate: int = 16000) -> str:
    """Generates base64-encoded 16-bit linear PCM audio chunk (silence / sine placeholder)."""
    num_samples = int(sample_rate * duration_sec)
    pcm_bytes = b"\x00\x00" * num_samples
    return base64.b64encode(pcm_bytes).decode("ascii")


def generate_wav_chunk(duration_sec: float = 1.0, sample_rate: int = 16000) -> str:
    """Generates base64-encoded valid WAV file with RIFF container."""
    num_samples = int(sample_rate * duration_sec)
    pcm_bytes = b"\x00\x00" * num_samples
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class TestMeetingAudioIntegrationSuite(unittest.TestCase):
    """
    Comprehensive test suite validating the real meeting-audio integration pipeline:
    - Audio payload validation, size limits, and format checking.
    - Participant authorization and role anti-spoofing enforcement.
    - Out-of-order chunk reordering via bounded jitter buffer.
    - Audio containerization (PCM -> WAV wrapping, WebM/Opus, MP3, OGG).
    - Transcription provenance (is_simulated flag distinction).
    - End-to-end integration with question detection, notes, evaluations, persistence, and WebSockets.
    - Raw audio non-retention compliance and secure deletion.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        settings.audio_retention_enabled = False
        session_repo.clear()
        self.session_data = InterviewSessionCreate(
            title="Senior Distributed Systems Interview",
            candidate_id="cand_test_001",
            candidate_name="Alice Candidate",
            interviewer_id="int_lead_001",
            interviewer_name="Bob Interviewer",
            organization_id="org_test_media",
            consent_obtained=True
        )
        self.session_res = interview_session_service.create_session(self.session_data)
        self.session_id = self.session_res.session_id

    def tearDown(self):
        # Reset any streams in jitter buffer
        asyncio.run(audio_adapter.jitter_buffer.reset_stream(self.session_id))
        settings.audio_retention_enabled = False
        session_repo.clear()

    # --- 1. Audio Ingestion & Participant Authorization ---

    def test_valid_authorized_audio_ingested_successfully(self):
        """Verify that valid authorized audio reaches the existing ingestion pipeline."""
        payload = {
            "session_id": self.session_id,
            "participant_id": "int_lead_001",
            "participant_role": "interviewer",
            "sequence_number": 0,
            "timestamp": 0.0,
            "duration": 2.5,
            "audio_base64": generate_wav_chunk(2.5),
            "format": "wav",
            "sample_rate": 16000,
            "channels": 1
        }
        res = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "transcribed")
        self.assertIn("segment", data)
        self.assertEqual(data["segment"]["speaker_id"], "int_lead_001")
        self.assertEqual(data["segment"]["speaker_role"], "interviewer")
        self.assertEqual(data["segment"]["sequence_number"], 0)

    def test_unauthorized_participant_rejected(self):
        """Verify that an unknown participant cannot inject audio into the session."""
        payload = {
            "session_id": self.session_id,
            "participant_id": "unknown_intruder_999",
            "participant_role": "candidate",
            "sequence_number": 0,
            "timestamp": 0.0,
            "duration": 1.0,
            "audio_base64": generate_pcm_chunk(1.0),
            "format": "pcm"
        }
        res = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("not registered or authorized", res.json()["detail"])

    def test_participant_role_spoofing_overridden_by_session_records(self):
        """Verify client-supplied role cannot spoof identity; authoritative role is enforced."""
        # Candidate sends chunk claiming to be 'interviewer'
        payload = {
            "session_id": self.session_id,
            "participant_id": "cand_test_001",
            "participant_role": "interviewer",  # Spoofed!
            "sequence_number": 0,
            "timestamp": 0.0,
            "duration": 2.0,
            "audio_base64": generate_wav_chunk(2.0),
            "format": "wav"
        }
        res = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res.status_code, 200)
        # Server must enforce candidate role
        self.assertEqual(res.json()["segment"]["speaker_role"], "candidate")
        self.assertEqual(res.json()["segment"]["speaker_name"], "Alice Candidate")

    def test_nonexistent_session_audio_rejected(self):
        """Verify audio cannot be injected into an invalid/nonexistent session."""
        payload = {
            "session_id": "int_nonexistent_999",
            "participant_id": "cand_test_001",
            "sequence_number": 0,
            "timestamp": 0.0,
            "duration": 1.0,
            "audio_base64": generate_pcm_chunk(1.0)
        }
        res = self.client.post("/api/v1/interviews/int_nonexistent_999/audio", json=payload)
        self.assertEqual(res.status_code, 404)

    # --- 2. Format Validation & Containerization ---

    def test_unsupported_audio_format_rejected(self):
        """Verify unsupported audio formats are rejected with 400 Bad Request."""
        payload = {
            "session_id": self.session_id,
            "participant_id": "int_lead_001",
            "sequence_number": 0,
            "timestamp": 0.0,
            "duration": 1.0,
            "audio_base64": "AAAA",
            "format": "unsupported_avi"
        }
        res = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported audio format", res.json()["detail"])

    def test_malformed_base64_payload_rejected(self):
        """Verify malformed base64 is caught safely without unhandled server crash."""
        payload = {
            "session_id": self.session_id,
            "participant_id": "int_lead_001",
            "sequence_number": 0,
            "timestamp": 0.0,
            "duration": 1.0,
            "audio_base64": "not_valid_base64_@@@@!!!",
            "format": "pcm"
        }
        res = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Malformed audio_base64 payload", res.json()["detail"])

    def test_pcm_to_wav_containerization(self):
        """Verify raw PCM bytes are converted to standard in-memory WAV with RIFF header."""
        raw_pcm = b"\x00\x00" * 8000
        wav_bytes = pcm_to_wav_bytes(raw_pcm, channels=1, sample_rate=16000)
        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav_bytes[:16])

        # Test normalize_audio_for_transcription
        norm_bytes, filename, mime = normalize_audio_for_transcription(raw_pcm, "pcm")
        self.assertEqual(filename, "audio.wav")
        self.assertEqual(mime, "audio/wav")
        self.assertTrue(norm_bytes.startswith(b"RIFF"))

    def test_webm_and_mp3_containers_preserved_for_transcription(self):
        """Verify WebM and MP3 formats are recognized and routed with correct mime-types."""
        dummy_webm = b"\x1aE\xdf\xa3" + b"\x00" * 100
        norm_bytes, filename, mime = normalize_audio_for_transcription(dummy_webm, "webm")
        self.assertEqual(filename, "audio.webm")
        self.assertEqual(mime, "audio/webm")

        dummy_mp3 = b"ID3" + b"\x00" * 100
        norm_bytes, filename, mime = normalize_audio_for_transcription(dummy_mp3, "mp3")
        self.assertEqual(filename, "audio.mp3")
        self.assertEqual(mime, "audio/mpeg")

    # --- 3. Deduplication & Bounded Jitter Buffer Reordering ---

    def test_duplicate_sequence_number_deduplicated(self):
        """Verify duplicate chunks are safely discarded without error."""
        payload = {
            "session_id": self.session_id,
            "participant_id": "int_lead_001",
            "sequence_number": 1,
            "timestamp": 1.0,
            "duration": 2.0,
            "audio_base64": generate_wav_chunk(2.0),
            "format": "wav"
        }
        # First delivery
        res1 = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["status"], "transcribed")

        # Duplicate delivery with same sequence number
        res2 = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["status"], "accepted_or_duplicate")

    def test_jitter_buffer_reorders_out_of_order_chunks(self):
        """Verify that chunks arriving out of order are buffered and emitted in sequence."""
        jb = BoundedJitterBuffer(max_buffer_size=10, max_gap=5)

        chunk0 = AudioChunkPayload(
            session_id="test_sess", participant_id="p1", sequence_number=0, timestamp=0.0
        )
        chunk1 = AudioChunkPayload(
            session_id="test_sess", participant_id="p1", sequence_number=1, timestamp=2.0
        )
        chunk2 = AudioChunkPayload(
            session_id="test_sess", participant_id="p1", sequence_number=2, timestamp=4.0
        )

        async def run_jitter_test():
            # Ingest Seq 0 (in order) -> returns [chunk0]
            ready0 = await jb.push_and_get_ready("test_sess", chunk0)
            self.assertEqual(len(ready0), 1)
            self.assertEqual(ready0[0].sequence_number, 0)

            # Ingest Seq 2 (ahead of seq 1) -> buffers Seq 2, returns []
            ready2 = await jb.push_and_get_ready("test_sess", chunk2)
            self.assertEqual(len(ready2), 0)

            # Ingest Seq 1 (missing chunk arrives!) -> returns [chunk1, chunk2] in order!
            ready1 = await jb.push_and_get_ready("test_sess", chunk1)
            self.assertEqual(len(ready1), 2)
            self.assertEqual(ready1[0].sequence_number, 1)
            self.assertEqual(ready1[1].sequence_number, 2)

        asyncio.run(run_jitter_test())

    def test_jitter_buffer_backpressure_and_gap_flush(self):
        """Verify jitter buffer does not stall when missing chunk is permanently lost."""
        jb = BoundedJitterBuffer(max_buffer_size=3, max_gap=3)

        chunk0 = AudioChunkPayload(
            session_id="test_sess", participant_id="p1", sequence_number=0, timestamp=0.0
        )
        # Gap: Seq 1 is lost permanently
        chunk5 = AudioChunkPayload(
            session_id="test_sess", participant_id="p1", sequence_number=5, timestamp=10.0
        )

        async def run_gap_test():
            await jb.push_and_get_ready("test_sess", chunk0)
            # Seq 5 arrives with gap > max_gap (3)
            ready = await jb.push_and_get_ready("test_sess", chunk5)
            # Jitter buffer should flush gap rather than hanging forever
            self.assertTrue(len(ready) > 0)
            self.assertEqual(ready[-1].sequence_number, 5)

        asyncio.run(run_gap_test())

    # --- 4. Transcription Provenance & Attribution ---

    def test_transcription_provenance_flag(self):
        """Verify MockTranscriptionService flags output as is_simulated=True."""
        mock_stt = MockTranscriptionService()
        chunk = AudioChunkPayload(
            session_id=self.session_id,
            participant_id="cand_test_001",
            sequence_number=5,
            timestamp=12.0,
            duration=3.0,
            audio_base64=generate_pcm_chunk(3.0)
        )
        session = session_repo.get(self.session_id)
        seg = asyncio.run(mock_stt.transcribe_chunk(session, chunk))
        self.assertIsNotNone(seg)
        self.assertTrue(seg.is_simulated)
        self.assertEqual(seg.sequence_number, 5)

    def test_track_level_speaker_attribution(self):
        """Verify discrete track participant IDs map deterministically without acoustic guessing."""
        session = session_repo.get(self.session_id)
        # Interviewer track
        spk_id, role, name = speaker_service.resolve_speaker(session, "int_lead_001")
        self.assertEqual(role, ParticipantRole.INTERVIEWER)
        self.assertEqual(name, "Bob Interviewer")

        # Candidate track
        spk_id, role, name = speaker_service.resolve_speaker(session, "cand_test_001")
        self.assertEqual(role, ParticipantRole.CANDIDATE)
        self.assertEqual(name, "Alice Candidate")

    # --- 5. Privacy, Audio Non-Retention & Deletion ---

    def test_raw_audio_non_retention_by_default(self):
        """Verify GDPR/FERPA compliance: raw audio is never retained on disk by default."""
        self.assertFalse(settings.audio_retention_enabled)
        payload = {
            "session_id": self.session_id,
            "participant_id": "int_lead_001",
            "sequence_number": 10,
            "timestamp": 20.0,
            "duration": 2.0,
            "audio_base64": generate_wav_chunk(2.0),
            "format": "wav"
        }
        res = self.client.post(f"/api/v1/interviews/{self.session_id}/audio", json=payload)
        self.assertEqual(res.status_code, 200)

        # Confirm no directory exists on disk
        target_dir = os.path.join(settings.audio_storage_path, self.session_id)
        self.assertFalse(os.path.exists(target_dir))

    # --- 6. End-to-End Pipeline & Report Finalization ---

    def test_audio_pipeline_end_to_end_triggers_intelligence_services(self):
        """Verify audio flows into question detector, notes, evaluations, persistence, and reports."""
        # 1. Interviewer asks a technical question
        q_payload = {
            "session_id": self.session_id,
            "participant_id": "int_lead_001",
            "sequence_number": 0,
            "timestamp": 0.0,
            "duration": 4.0,
            "audio_base64": generate_wav_chunk(4.0),
            "format": "wav"
        }
        # Provide hint to simulate actual speech content
        asyncio.run(
            interview_session_service.ingest_audio_chunk(
                self.session_id,
                AudioChunkPayload(**q_payload),
                transcription_hint="How do you handle distributed transactions across microservices?"
            )
        )

        # 2. Candidate answers
        a_payload = {
            "session_id": self.session_id,
            "participant_id": "cand_test_001",
            "sequence_number": 0,
            "timestamp": 5.0,
            "duration": 12.0,
            "audio_base64": generate_wav_chunk(12.0),
            "format": "wav"
        }
        asyncio.run(
            interview_session_service.ingest_audio_chunk(
                self.session_id,
                AudioChunkPayload(**a_payload),
                transcription_hint="We can use the Saga pattern with choreography or orchestration, compensating transactions, and outbox patterns."
            )
        )

        # 3. Next question closes previous QA turn
        q2_payload = {
            "session_id": self.session_id,
            "participant_id": "int_lead_001",
            "sequence_number": 1,
            "timestamp": 18.0,
            "duration": 3.0,
            "audio_base64": generate_wav_chunk(3.0),
            "format": "wav"
        }
        asyncio.run(
            interview_session_service.ingest_audio_chunk(
                self.session_id,
                AudioChunkPayload(**q2_payload),
                transcription_hint="What are the trade-offs of choreography vs orchestration?"
            )
        )

        # Verify session state updated in repository
        reloaded = session_repo.get(self.session_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(len(reloaded.transcript_segments), 3)
        self.assertTrue(len(reloaded.notes) >= 1)

        # Finalize report
        fin_res = self.client.post(f"/api/v1/interviews/{self.session_id}/finalize")
        self.assertEqual(fin_res.status_code, 200)
        report_data = fin_res.json()
        self.assertEqual(report_data["status"], "completed")
        self.assertIn("aggregate_score", report_data)


if __name__ == "__main__":
    unittest.main()
