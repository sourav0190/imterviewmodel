import unittest
import os
import shutil
import base64
from starlette.testclient import TestClient

from main import app
from interview_agent.models.interview_session import session_repo
from interview_agent.config import settings
from interview_agent.schemas.interview import ParticipantRole
from interview_agent.schemas.transcript import AudioChunkPayload

class TestInterviewSecuritySuite(unittest.TestCase):
    """
    Comprehensive security test suite validating:
    - Credential verification (missing, invalid, valid).
    - Production anonymous-mode protection and startup validation.
    - Tenant and session authorization (reads, updates, audio ingestion, report export, deletion).
    - Cross-organization and cross-session isolation.
    - Safe deletion of retained raw audio files on disk (with path traversal guards).
    - Secure WebSocket authentication and authorization.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        session_repo.clear()
        # Save original settings to restore in tearDown
        self._orig_api_key = settings.api_key
        self._orig_anon_dev = settings.allow_anonymous_dev
        self._orig_app_env = settings.app_env
        self._orig_storage_path = settings.audio_storage_path
        self._orig_audio_retention_enabled = settings.audio_retention_enabled

    def tearDown(self):
        settings.api_key = self._orig_api_key
        settings.allow_anonymous_dev = self._orig_anon_dev
        settings.app_env = self._orig_app_env
        settings.audio_storage_path = self._orig_storage_path
        settings.audio_retention_enabled = self._orig_audio_retention_enabled
        session_repo.clear()

    # --- 1. Credential Verification (Production & Secured Mode) ---

    def test_missing_credentials_rejected_when_auth_required(self):
        """Verify that missing credentials return 401 Unauthorized when anonymous access is disabled."""
        settings.api_key = "secure_test_token_123"
        settings.allow_anonymous_dev = False

        res = self.client.get("/api/v1/interviews")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Missing authentication credentials", res.json()["detail"])

    def test_invalid_credentials_rejected(self):
        """Verify that invalid API keys or Bearer tokens return 401 Unauthorized."""
        settings.api_key = "secure_test_token_123"
        settings.allow_anonymous_dev = False

        # Invalid X-API-Key
        res1 = self.client.get("/api/v1/interviews", headers={"X-API-Key": "wrong_key"})
        self.assertEqual(res1.status_code, 401)
        self.assertIn("Invalid authentication credentials", res1.json()["detail"])

        # Invalid Bearer token
        res2 = self.client.get("/api/v1/interviews", headers={"Authorization": "Bearer wrong_token"})
        self.assertEqual(res2.status_code, 401)

    def test_valid_credentials_accepted(self):
        """Verify that valid API keys or Bearer tokens succeed."""
        settings.api_key = "secure_test_token_123"
        settings.allow_anonymous_dev = False

        # Header: X-API-Key
        res1 = self.client.get("/api/v1/interviews", headers={"X-API-Key": "secure_test_token_123"})
        self.assertEqual(res1.status_code, 200)

        # Header: Authorization Bearer
        res2 = self.client.get("/api/v1/interviews", headers={"Authorization": "Bearer secure_test_token_123"})
        self.assertEqual(res2.status_code, 200)

    def test_production_startup_validation(self):
        """Verify that production mode fails safely when INTERVIEW_API_KEY is missing."""
        settings.app_env = "production"
        settings.api_key = None

        with self.assertRaises(ValueError) as ctx:
            settings.validate_production_security()
        self.assertIn("INTERVIEW_API_KEY must be configured in production", str(ctx.exception))

    # --- 2. Session Ownership & Cross-Organization Isolation ---

    def test_cross_organization_isolation(self):
        """
        Verify that Organization A cannot read, modify, or export reports for Organization B's session.
        Returns 404 to avoid leaking session existence.
        """
        settings.api_key = "shared_api_gateway_key"
        settings.allow_anonymous_dev = False

        auth_headers_org_a = {
            "X-API-Key": "shared_api_gateway_key",
            "X-Organization-Id": "org_alpha",
            "X-User-Id": "recruiter_alpha"
        }
        auth_headers_org_b = {
            "X-API-Key": "shared_api_gateway_key",
            "X-Organization-Id": "org_beta",
            "X-User-Id": "recruiter_beta"
        }

        # Org Alpha creates a session
        create_res = self.client.post("/api/v1/interviews", json={
            "title": "Alpha Confidential Interview",
            "candidate_id": "cand_alpha",
            "candidate_name": "Alice Candidate",
            "interviewer_id": "int_alpha"
        }, headers=auth_headers_org_a)
        self.assertEqual(create_res.status_code, 201)
        session_id = create_res.json()["session_id"]
        self.assertEqual(create_res.json()["organization_id"], "org_alpha")

        # Org Alpha can read it
        read_a = self.client.get(f"/api/v1/interviews/{session_id}", headers=auth_headers_org_a)
        self.assertEqual(read_a.status_code, 200)

        # Org Beta attempts to read Org Alpha's session -> 404 (does not leak existence)
        read_b = self.client.get(f"/api/v1/interviews/{session_id}", headers=auth_headers_org_b)
        self.assertEqual(read_b.status_code, 404)

        # Org Beta attempts to list sessions -> receives only Org Beta sessions (0 results)
        list_b = self.client.get("/api/v1/interviews", headers=auth_headers_org_b)
        self.assertEqual(list_b.status_code, 200)
        self.assertEqual(len(list_b.json()), 0)

        # Org Beta attempts to update status -> 404
        update_b = self.client.post(
            f"/api/v1/interviews/{session_id}/status",
            json={"status": "paused"},
            headers=auth_headers_org_b
        )
        self.assertEqual(update_b.status_code, 404)

        # Org Beta attempts to ingest audio -> 404
        audio_chunk = {
            "session_id": session_id,
            "participant_id": "int_alpha",
            "participant_role": "interviewer",
            "sequence_number": 1,
            "timestamp": 0.0,
            "duration": 1.0,
            "audio_base64": "AAAA"
        }
        audio_b = self.client.post(
            f"/api/v1/interviews/{session_id}/audio",
            json=audio_chunk,
            headers=auth_headers_org_b
        )
        self.assertEqual(audio_b.status_code, 404)

        # Org Beta attempts to read transcript -> 404
        trans_b = self.client.get(f"/api/v1/interviews/{session_id}/transcript", headers=auth_headers_org_b)
        self.assertEqual(trans_b.status_code, 404)

        # Org Beta attempts to finalize & export report -> 404
        finalize_b = self.client.post(f"/api/v1/interviews/{session_id}/finalize", headers=auth_headers_org_b)
        self.assertEqual(finalize_b.status_code, 404)

        # Org Beta attempts to delete session -> 404
        del_b = self.client.delete(f"/api/v1/interviews/{session_id}", headers=auth_headers_org_b)
        self.assertEqual(del_b.status_code, 404)

        # Confirm Org Alpha's session is still intact
        check_a = self.client.get(f"/api/v1/interviews/{session_id}", headers=auth_headers_org_a)
        self.assertEqual(check_a.status_code, 200)

    # --- 3. Secure Session Deletion & Retained Audio Cleanup ---

    def test_authorized_deletion_cleans_retained_audio(self):
        """
        Verify that authorized deletion:
        1. Removes session from repository.
        2. Safely deletes retained raw audio files on disk.
        3. Prevents path traversal outside storage directory.
        """
        temp_audio_dir = os.path.abspath("test_scratch_audio_storage")
        settings.audio_storage_path = temp_audio_dir
        settings.audio_retention_enabled = True
        os.makedirs(temp_audio_dir, exist_ok=True)

        try:
            # Create a session with consent obtained
            create_res = self.client.post("/api/v1/interviews", json={
                "candidate_id": "cand_gdpr",
                "candidate_name": "GDPR User",
                "interviewer_id": "int_lead",
                "consent_obtained": True
            })
            self.assertEqual(create_res.status_code, 201)
            session_id = create_res.json()["session_id"]

            # Ingest an audio chunk that triggers retention
            sample_bytes = b"SIMULATED_PCM_AUDIO_DATA_FOR_GDPR_TEST"
            b64_audio = base64.b64encode(sample_bytes).decode("utf-8")
            chunk_payload = {
                "session_id": session_id,
                "participant_id": "int_lead",
                "participant_role": "interviewer",
                "sequence_number": 1,
                "timestamp": 0.0,
                "duration": 1.5,
                "audio_base64": b64_audio
            }
            audio_res = self.client.post(f"/api/v1/interviews/{session_id}/audio", json=chunk_payload)
            self.assertEqual(audio_res.status_code, 200)

            # Confirm audio file was created on disk
            session_audio_dir = os.path.join(temp_audio_dir, session_id)
            self.assertTrue(os.path.exists(session_audio_dir), "Audio storage dir should exist before deletion")

            # Authorized session deletion
            del_res = self.client.delete(f"/api/v1/interviews/{session_id}")
            self.assertEqual(del_res.status_code, 204)

            # Confirm session is deleted from repo
            get_res = self.client.get(f"/api/v1/interviews/{session_id}")
            self.assertEqual(get_res.status_code, 404)

            # Confirm audio directory on disk is completely removed
            self.assertFalse(os.path.exists(session_audio_dir), "Audio storage dir must be removed upon session deletion")
        finally:
            settings.audio_retention_enabled = False
            if os.path.exists(temp_audio_dir):
                shutil.rmtree(temp_audio_dir)

    def test_path_traversal_audio_deletion_defense(self):
        """Verify that malicious session IDs with path traversal characters cannot delete outside storage dir."""
        from interview_agent.services.audio_adapter import delete_session_audio_storage

        # Attempt to pass traversal paths
        self.assertFalse(delete_session_audio_storage("../../etc"))
        self.assertFalse(delete_session_audio_storage("../root"))
        self.assertFalse(delete_session_audio_storage("..\\system32"))
        self.assertFalse(delete_session_audio_storage("valid/subdir"))

    # --- 4. WebSocket Authentication & Authorization ---

    def test_websocket_authentication_and_tenant_rejection(self):
        """
        Verify WebSocket stream:
        1. Closes with 1008 if unauthenticated when auth is required.
        2. Closes with 1008 if principal belongs to another tenant/organization.
        3. Accepts and streams if authenticated and authorized.
        """
        settings.api_key = "ws_secret_key_888"
        settings.allow_anonymous_dev = False

        auth_headers_org_a = {
            "X-API-Key": "ws_secret_key_888",
            "X-Organization-Id": "org_secure_a"
        }

        # Create session in Org A
        res = self.client.post("/api/v1/interviews", json={
            "candidate_id": "c_ws_sec",
            "candidate_name": "WS Candidate",
            "interviewer_id": "i_ws_sec"
        }, headers=auth_headers_org_a)
        session_id = res.json()["session_id"]

        # 1. Connection without token -> Policy violation 1008
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/api/v1/interviews/ws/{session_id}") as ws:
                ws.receive_json()

        # 2. Connection with wrong token -> Policy violation 1008
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/api/v1/interviews/ws/{session_id}?token=bad_key") as ws:
                ws.receive_json()

        # 3. Connection with valid token but wrong organization -> Policy violation 1008
        with self.assertRaises(Exception):
            with self.client.websocket_connect(
                f"/api/v1/interviews/ws/{session_id}?token=ws_secret_key_888&org_id=org_intruder"
            ) as ws:
                ws.receive_json()

        # 4. Connection with valid token and matching organization -> Succeeds and receives snapshot
        with self.client.websocket_connect(
            f"/api/v1/interviews/ws/{session_id}?token=ws_secret_key_888&org_id=org_secure_a"
        ) as ws:
            snap = ws.receive_json()
            self.assertEqual(snap["type"], "session_snapshot")
            self.assertEqual(snap["session"]["session_id"], session_id)


    def test_omitted_organization_header_does_not_grant_admin_or_cross_tenant_access(self):
        """
        Verify principle of least privilege:
        A caller with a valid API key who omits X-Organization-Id does NOT get elevated to admin,
        and cannot access another organization's session.
        """
        settings.api_key = "secure_production_key"
        settings.allow_anonymous_dev = False

        # Org Alpha creates a confidential session
        create_res = self.client.post("/api/v1/interviews", json={
            "title": "Alpha Top Secret",
            "candidate_id": "cand_alpha_99",
            "candidate_name": "Alice Candidate",
            "interviewer_id": "int_alpha_99"
        }, headers={
            "X-API-Key": "secure_production_key",
            "X-Organization-Id": "org_alpha"
        })
        self.assertEqual(create_res.status_code, 201)
        session_id = create_res.json()["session_id"]

        # Caller provides valid API key but OMITS X-Organization-Id header
        read_res = self.client.get(
            f"/api/v1/interviews/{session_id}",
            headers={"X-API-Key": "secure_production_key"}
        )
        # Must be rejected with 404 (resource not found for this tenant), NOT allowed as admin
        self.assertEqual(read_res.status_code, 404)

        # Listing sessions without X-Organization-Id must only return default-org sessions, not Org Alpha's session
        list_res = self.client.get(
            "/api/v1/interviews",
            headers={"X-API-Key": "secure_production_key"}
        )
        self.assertEqual(list_res.status_code, 200)
        returned_session_ids = [s["session_id"] for s in list_res.json()]
        self.assertNotIn(session_id, returned_session_ids)


if __name__ == "__main__":
    unittest.main()
