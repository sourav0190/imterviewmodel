import unittest
import hmac
import hashlib
import json
import base64
from starlette.testclient import TestClient

from main import app
from interview_agent.config import settings
from interview_agent.models.interview_session import session_repo, InterviewSessionModel
from interview_agent.schemas.interview import (
    InterviewSessionCreate,
    ParticipantRole,
    SessionStatus,
)
from interview_agent.schemas.transcript import TranscriptSegment
from interview_agent.services.interview_session_service import interview_session_service
from interview_agent.integrations.jitsi.room_manager import jitsi_room_manager
from interview_agent.integrations.jitsi.adapter import jitsi_adapter
from interview_agent.integrations.jitsi.schemas import JitsiTranscriptEvent, JitsiWebhookPayload


class TestJitsiIntegrationSuite(unittest.TestCase):
    """
    Comprehensive test suite validating Jitsi Meet integration:
    - High-entropy unpredictable room creation and session association.
    - Authorized configuration access and multi-tenant isolation.
    - Webhook HMAC signature validation.
    - Duplicate event deduplication and out-of-order timestamp handling.
    - Speaker resolution, metadata, and timestamp preservation.
    - PostgreSQL/database persistence of Jitsi transcript segments and notes.
    - Automated final report synthesis with verified participants, technical concepts, and follow-ups.
    - Existing proctoring route regression prevention.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        session_repo.clear()
        settings.jitsi_webhook_secret = "test-secret-key-12345"
        settings.app_env = "development"
        settings.allow_anonymous_dev = True

        self.session_data = InterviewSessionCreate(
            title="Senior Distributed Systems Architect",
            candidate_id="cand_alex_001",
            candidate_name="Alex Mercer",
            interviewer_id="int_lead_99",
            interviewer_name="Sarah Chen",
            organization_id="org_engineering",
            owner_id="user_interviewer_1",
            consent_obtained=True
        )
        self.session_res = interview_session_service.create_session(self.session_data)
        self.session_id = self.session_res.session_id

    def test_unpredictable_room_creation_and_association(self):
        """Verify unique, high-entropy room name generation and association with session."""
        session = interview_session_service.get_session(self.session_id)
        self.assertIsNotNone(session)
        self.assertNotIn("jitsi_room_name", session.metadata)

        room_cfg = jitsi_room_manager.get_or_create_room(session)
        self.assertIsNotNone(room_cfg.room_name)
        self.assertTrue(room_cfg.room_name.startswith(settings.jitsi_room_prefix))
        self.assertIn(self.session_id.replace("int_", ""), room_cfg.room_name)
        # Ensure high-entropy suffix
        self.assertGreater(len(room_cfg.room_name), 25)

        # Ensure room name was persisted to session metadata
        updated_session = session_repo.get(self.session_id)
        self.assertEqual(updated_session.metadata["jitsi_room_name"], room_cfg.room_name)

        # Idempotency: Calling again returns the exact same room name
        room_cfg_2 = jitsi_room_manager.get_or_create_room(updated_session)
        self.assertEqual(room_cfg_2.room_name, room_cfg.room_name)

    def test_jitsi_config_endpoint_with_session_association(self):
        """Verify GET /api/v1/interviews/{session_id}/jitsi/config returns complete room config."""
        resp = self.client.get(
            f"/api/v1/interviews/{self.session_id}/jitsi/config",
            headers={"X-Organization-Id": "org_engineering", "X-User-Id": "user_interviewer_1"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_id"], self.session_id)
        self.assertEqual(data["domain"], settings.jitsi_domain)
        self.assertIn("Alex Mercer", data["candidate_name"])
        self.assertIn("Sarah Chen", data["interviewer_name"])
        self.assertTrue(data["consent_required"])
        self.assertIn("transcribed in real time", data["consent_notice"])

    def test_unauthorized_session_access_rejected(self):
        """
        Verify that a user from a different organization cannot access or alter room config.
        Returns 404 to avoid leaking session existence to unauthorized tenants (anti-enumeration).
        """
        resp = self.client.get(
            f"/api/v1/interviews/{self.session_id}/jitsi/config",
            headers={"X-Organization-Id": "org_adversary_tenant", "X-User-Id": "user_hacker"}
        )
        self.assertEqual(resp.status_code, 404)

    def test_webhook_hmac_signature_validation(self):
        """Verify HMAC-SHA256 signature verification for Jitsi bridge webhooks."""
        payload = {
            "event": "TRANSCRIPTION_EVENT",
            "room": "AiProtctor-Interview-room-123",
            "session_id": self.session_id,
            "data": {
                "participant_id": "cand_alex_001",
                "text": "We partition using consistent hashing to distribute keys evenly.",
                "start_time": 12.0,
                "end_time": 16.5,
                "sequence_number": 1,
                "confidence": 0.96
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        # 1. Valid HMAC signature
        mac = hmac.new(
            settings.jitsi_webhook_secret.encode("utf-8"),
            msg=body_bytes,
            digestmod=hashlib.sha256
        )
        valid_sig = f"sha256={mac.hexdigest()}"

        resp = self.client.post(
            f"/api/v1/interviews/{self.session_id}/jitsi/webhook",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Jitsi-Signature": valid_sig}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "processed")

        # 2. Invalid HMAC signature -> 401 Unauthorized
        resp_invalid = self.client.post(
            f"/api/v1/interviews/{self.session_id}/jitsi/webhook",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Jitsi-Signature": "sha256=bad_hex_signature"}
        )
        self.assertEqual(resp_invalid.status_code, 401)

        # 3. Missing HMAC signature in production or when secret set -> 401 Unauthorized
        resp_missing = self.client.post(
            f"/api/v1/interviews/{self.session_id}/jitsi/webhook",
            content=body_bytes,
            headers={"Content-Type": "application/json"}
        )
        self.assertEqual(resp_missing.status_code, 401)

    def test_jitsi_transcript_event_deduplication(self):
        """Verify that duplicate transcript events with same event_id or sequence are dropped idempotently."""
        event = JitsiTranscriptEvent(
            event_id="jev_unique_001",
            session_id=self.session_id,
            room_name="room_abc",
            participant_id="int_lead_99",
            speaker_role=ParticipantRole.INTERVIEWER,
            text="Can you explain how Redis persistence works with RDB and AOF?",
            start_time=1.0,
            end_time=5.0,
            sequence_number=1,
            confidence=0.99
        )

        # First ingestion -> accepted
        resp1 = self.client.post(
            f"/api/v1/interviews/{self.session_id}/jitsi/transcript-event",
            json=event.model_dump(mode="json"),
            headers={"X-Organization-Id": "org_engineering", "X-User-Id": "user_interviewer_1"}
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["status"], "ingested")

        # Second ingestion with identical event_id -> skipped duplicate
        resp2 = self.client.post(
            f"/api/v1/interviews/{self.session_id}/jitsi/transcript-event",
            json=event.model_dump(mode="json"),
            headers={"X-Organization-Id": "org_engineering", "X-User-Id": "user_interviewer_1"}
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "skipped_duplicate_or_empty")

        # Verify only 1 segment persisted in session
        session = session_repo.get(self.session_id)
        self.assertEqual(len(session.transcript_segments), 1)

    def test_out_of_order_events_ordered_processing(self):
        """Verify that out-of-order Jitsi transcript events are ordered chronologically."""
        events = [
            JitsiTranscriptEvent(
                event_id="jev_seq_2",
                session_id=self.session_id,
                room_name="room_abc",
                participant_id="cand_alex_001",
                text="AOF logs every write command, while RDB creates periodic point-in-time snapshots.",
                start_time=6.0,
                end_time=12.0,
                sequence_number=2
            ),
            JitsiTranscriptEvent(
                event_id="jev_seq_1",
                session_id=self.session_id,
                room_name="room_abc",
                participant_id="int_lead_99",
                text="How does Redis ensure durability across restarts?",
                start_time=1.0,
                end_time=5.0,
                sequence_number=1
            )
        ]

        import asyncio
        results = asyncio.run(jitsi_adapter.process_ordered_events(self.session_id, events))
        self.assertEqual(len(results), 2)
        # Verify chronological order: start_time 1.0 processed before 6.0
        self.assertEqual(results[0].start_time, 1.0)
        self.assertEqual(results[1].start_time, 6.0)

    def test_end_to_end_jitsi_bridge_to_notes_and_final_report(self):
        """
        Verify end-to-end integration:
        1. Jitsi transcript events ingested.
        2. Segments saved in repository.
        3. Factual structured notes generated.
        4. Final report synthesized containing verified participants, technical concepts, and follow-ups.
        """
        resp = self.client.post(
            f"/api/v1/interviews/{self.session_id}/jitsi/simulate-dev?auto_finalize=true",
            headers={"X-Organization-Id": "org_engineering", "X-User-Id": "user_interviewer_1"}
        )
        self.assertEqual(resp.status_code, 200)
        sim_data = resp.json()
        self.assertEqual(sim_data["status"], "jitsi_simulation_completed")
        self.assertEqual(sim_data["segments_ingested"], 4)
        self.assertGreaterEqual(sim_data["total_notes"], 1)
        self.assertTrue(sim_data["final_report_generated"])

        # Fetch finalized report via REST API
        report_resp = self.client.get(
            f"/api/v1/interviews/{self.session_id}/report",
            headers={"X-Organization-Id": "org_engineering", "X-User-Id": "user_interviewer_1"}
        )
        self.assertEqual(report_resp.status_code, 200)
        report = report_resp.json()

        # Check required report fields
        self.assertEqual(report["interview_title"], "Senior Distributed Systems Architect")
        self.assertIsNotNone(report["meeting_date"])
        self.assertTrue(len(report["participants"]) >= 2)
        # Check that participants contain reliably established names
        participant_names = " ".join(report["participants"])
        self.assertIn("Alex Mercer", participant_names)
        self.assertIn("Sarah Chen", participant_names)

        # Check technical concepts discussed
        self.assertTrue(len(report["technical_concepts_discussed"]) > 0)
        concept_str = " ".join(report["technical_concepts_discussed"]).lower()
        # Sharding or Acid or Two-Phase Commit should be captured from genuine text
        self.assertTrue(any(k in concept_str for k in ["sharding", "acid", "2pc", "two-phase commit", "saga"]))

        # Check decisions and follow-up actions
        self.assertTrue(len(report["decisions_and_actions"]) > 0)

        # Check proctoring isolation notice
        self.assertIn("strictly decoupled from proctoring suspicion scores", report["proctoring_score_isolation_notice"])

    def test_existing_proctoring_and_analysis_routes_preserved(self):
        """Verify that existing proctoring endpoints (/test, /api/v1/analyze, etc.) remain intact without regression."""
        # /test frontend route
        resp_test = self.client.get("/test")
        self.assertEqual(resp_test.status_code, 200)

        # /interview-dashboard route
        resp_dash = self.client.get("/interview-dashboard")
        self.assertEqual(resp_dash.status_code, 200)

        # /api/v1/analyze route exists (test with dummy frame data or missing frame)
        resp_analyze = self.client.post("/api/v1/analyze", json={})
        # Expect either 400 (missing frame) or 422, verifying router is mounted and active
        self.assertIn(resp_analyze.status_code, (400, 422))

    def test_simulation_endpoints_strictly_prohibited_in_production(self):
        """Security requirement: verify simulate-dev and simulate-mock are blocked in production."""
        from interview_agent.config import settings
        orig_env = settings.app_env
        orig_key = settings.api_key
        try:
            settings.app_env = "production"
            settings.api_key = "prod_secret_key"
            prod_headers = {
                "X-API-Key": "prod_secret_key",
                "X-Organization-Id": "org_engineering",
                "X-User-Id": "user_interviewer_1"
            }
            resp_dev = self.client.post(
                f"/api/v1/interviews/{self.session_id}/jitsi/simulate-dev",
                headers=prod_headers
            )
            self.assertEqual(resp_dev.status_code, 403)
            self.assertIn("Development simulation endpoints are strictly prohibited in production mode", resp_dev.text)

            resp_mock = self.client.post(
                f"/api/v1/interviews/{self.session_id}/simulate-mock",
                headers=prod_headers
            )
            self.assertEqual(resp_mock.status_code, 403)
            self.assertIn("Development simulation endpoints are strictly prohibited in production mode", resp_mock.text)
        finally:
            settings.app_env = orig_env
            settings.api_key = orig_key

    def test_jaas_webhook_transcription_chunk_normalization(self):
        """Verify 8x8 JaaS TRANSCRIPTION_CHUNK webhook format, signature check, and normalization."""
        session = interview_session_service.get_session(self.session_id)
        room_cfg = jitsi_room_manager.get_or_create_room(session)

        jaas_payload = {
            "eventType": "TRANSCRIPTION_CHUNK",
            "fqn": f"vpaas-magic-cookie-xxx/{room_cfg.room_name}",
            "sessionId": self.session_id,
            "data": {
                "participant": {
                    "id": "cand_alex_001",
                    "name": "Alex Mercer"
                },
                "text": "PostgreSQL MVCC uses vacuuming to clean up dead tuples from table pages.",
                "timestamp": 25.0,
                "confidence": 0.98
            }
        }
        body_bytes = json.dumps(jaas_payload).encode("utf-8")
        mac = hmac.new(
            settings.jitsi_webhook_secret.encode("utf-8"),
            msg=body_bytes,
            digestmod=hashlib.sha256
        )
        sig = mac.hexdigest()

        # Post to universal webhook endpoint with X-8x8-Signature
        resp = self.client.post(
            "/api/v1/interviews/jitsi/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-8x8-Signature": sig
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "processed")

        # Verify segment was ingested with source="bridge"
        updated_session = session_repo.get(self.session_id)
        self.assertEqual(len(updated_session.transcript_segments), 1)
        seg = updated_session.transcript_segments[0]
        self.assertEqual(seg.source, "bridge")
        self.assertIn("vacuuming", seg.text)
        self.assertEqual(seg.speaker_role, ParticipantRole.CANDIDATE)

    def test_webhook_room_mismatch_rejected(self):
        """Verify that webhooks presenting a room name that does not match the session room are rejected with 400."""
        session = interview_session_service.get_session(self.session_id)
        jitsi_room_manager.get_or_create_room(session)

        mismatched_payload = {
            "eventType": "TRANSCRIPTION_CHUNK",
            "fqn": "vpaas-magic-cookie-xxx/AiProtctor-Interview-COMPLETELY_WRONG_ROOM",
            "sessionId": self.session_id,
            "data": {
                "text": "Intruder attempt on wrong room.",
                "participant": {"id": "p1", "name": "Hacker"},
                "timestamp": 10.0
            }
        }
        body_bytes = json.dumps(mismatched_payload).encode("utf-8")
        mac = hmac.new(
            settings.jitsi_webhook_secret.encode("utf-8"),
            msg=body_bytes,
            digestmod=hashlib.sha256
        )
        sig = mac.hexdigest()

        resp = self.client.post(
            f"/api/v1/interviews/{self.session_id}/jitsi/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-8x8-Signature": sig
            }
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("does not match", resp.text)

    def test_universal_webhook_nonexistent_room_returns_400(self):
        """Verify that universal webhook without valid session or room returns 400 Bad Request."""
        unknown_payload = {
            "event": "TRANSCRIPTION_EVENT",
            "room": "NonexistentRoom",
            "data": {"text": "hello", "timestamp": 1.0}
        }
        body_bytes = json.dumps(unknown_payload).encode("utf-8")
        mac = hmac.new(
            settings.jitsi_webhook_secret.encode("utf-8"),
            msg=body_bytes,
            digestmod=hashlib.sha256
        )
        sig = mac.hexdigest()

        resp = self.client.post(
            "/api/v1/interviews/jitsi/webhook",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Jitsi-Signature": sig}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Missing session_id in webhook URL or payload", resp.text)

        # Also test with nonexistent session_id -> returns 404
        payload_with_bad_id = dict(unknown_payload, session_id="int_nonexistent_9999")
        bad_id_bytes = json.dumps(payload_with_bad_id).encode("utf-8")
        bad_sig = hmac.new(settings.jitsi_webhook_secret.encode("utf-8"), bad_id_bytes, hashlib.sha256).hexdigest()
        resp_404 = self.client.post(
            "/api/v1/interviews/jitsi/webhook",
            content=bad_id_bytes,
            headers={"Content-Type": "application/json", "X-Jitsi-Signature": bad_sig}
        )
        self.assertEqual(resp_404.status_code, 404)

    def test_startup_validation_actionable_errors(self):
        """Verify startup validation detects invalid or missing bridge configuration in production."""
        from interview_agent.config import InterviewConfig

        base_kwargs = {
            "app_env": "production",
            "allow_anonymous_dev": False,
            "api_key": "valid_key",
            "persistence_backend": "postgres",
            "database_url": "postgresql+psycopg://postgres:secret@localhost:5432/db",
        }

        # 1. JaaS missing app_id
        s1 = InterviewConfig(
            **base_kwargs,
            jitsi_bridge_provider="jaas",
            jitsi_app_id="",
            jitsi_webhook_secret="sec"
        )
        with self.assertRaises(ValueError) as cm1:
            s1.validate_production_security()
        self.assertIn("JITSI_APP_ID is missing", str(cm1.exception))

        # 2. JaaS missing webhook secret
        s2 = InterviewConfig(
            **base_kwargs,
            jitsi_bridge_provider="jaas",
            jitsi_app_id="vpaas-magic-cookie-xxx",
            jitsi_secret="key",
            jitsi_webhook_secret=""
        )
        with self.assertRaises(ValueError) as cm2:
            s2.validate_production_security()
        self.assertIn("JITSI_WEBHOOK_SECRET is missing", str(cm2.exception))

        # 3. Jigasi pointing to public meet.jit.si
        s3 = InterviewConfig(
            **base_kwargs,
            jitsi_bridge_provider="jigasi",
            jitsi_server_url="https://meet.jit.si",
            jitsi_webhook_secret="sec"
        )
        with self.assertRaises(ValueError) as cm3:
            s3.validate_production_security()
        self.assertIn("public 'https://meet.jit.si'", str(cm3.exception))

        # 4. Bridge provider 'none' with transcription enabled in production
        s4 = InterviewConfig(
            **base_kwargs,
            jitsi_bridge_provider="none",
            jitsi_transcription_enabled=True
        )
        with self.assertRaises(ValueError) as cm4:
            s4.validate_production_security()
        self.assertIn("Public meet.jit.si does not expose remote participant audio", str(cm4.exception))

    def test_transcript_provenance_tracking_in_final_report(self):
        """Verify that final report correctly tallies segment provenance (bridge vs local_mic vs simulation)."""
        session = session_repo.get(self.session_id)
        # Add 1 bridge segment, 1 local_microphone segment, 1 simulation segment
        session.transcript_segments.append(TranscriptSegment(
            segment_id="seg_b_1",
            session_id=self.session_id,
            speaker_id="cand_alex_001",
            speaker_name="Alex Mercer",
            speaker_role=ParticipantRole.CANDIDATE,
            text="We scale writes using CockroachDB Multi-Raft consensus.",
            start_time=1.0,
            end_time=5.0,
            source="bridge"
        ))
        session.transcript_segments.append(TranscriptSegment(
            segment_id="seg_m_1",
            session_id=self.session_id,
            speaker_id="int_lead_99",
            speaker_name="Sarah Chen",
            speaker_role=ParticipantRole.INTERVIEWER,
            text="What consensus algorithm does CockroachDB use for range leases?",
            start_time=6.0,
            end_time=10.0,
            source="local_microphone"
        ))
        session.transcript_segments.append(TranscriptSegment(
            segment_id="seg_s_1",
            session_id=self.session_id,
            speaker_id="cand_alex_001",
            speaker_name="Alex Mercer",
            speaker_role=ParticipantRole.CANDIDATE,
            text="Simulated placeholder response for testing.",
            start_time=11.0,
            end_time=15.0,
            source="simulation"
        ))
        session_repo.save(session)

        resp = self.client.post(
            f"/api/v1/interviews/{self.session_id}/finalize",
            headers={"X-Organization-Id": "org_engineering", "X-User-Id": "user_interviewer_1"}
        )
        self.assertEqual(resp.status_code, 200)
        report = resp.json()
        self.assertIn("transcript_provenance", report)
        prov = report["transcript_provenance"]
        self.assertEqual(prov.get("bridge"), 1)
        self.assertEqual(prov.get("local_microphone"), 1)
        self.assertEqual(prov.get("simulation"), 1)


if __name__ == "__main__":
    unittest.main()

