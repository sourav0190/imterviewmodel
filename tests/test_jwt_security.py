import unittest
import time
import jwt
from starlette.testclient import TestClient

from main import app
from interview_agent.models.interview_session import session_repo
from interview_agent.config import settings
from interview_agent.security import ws_ticket_manager, Principal


class TestJwtSecuritySuite(unittest.TestCase):
    """
    Comprehensive cryptographic JWT identity and security test suite validating:
    - Missing, malformed, expired, and invalid-signature JWT verification.
    - Issuer and audience claims validation.
    - Neutralization of caller-supplied spoofed headers (verified JWT claims are authoritative).
    - Cross-tenant isolation across REST and WebSocket endpoints.
    - Privilege escalation defense (admin role requires explicit verified claim).
    - Short-lived, single-use WebSocket tickets for browsers (no long-lived tokens in URLs).
    - HTTP health check and CORS operational endpoints.
    - Preservation of server API key compatibility.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_secret = "test_cryptographic_jwt_secret_9999"
        cls.test_issuer = "https://auth.aiproctor.com/"
        cls.test_audience = "aiproctor-api"

    def setUp(self):
        session_repo.clear()
        # Save original settings
        self._orig_api_key = settings.api_key
        self._orig_anon_dev = settings.allow_anonymous_dev
        self._orig_app_env = settings.app_env
        self._orig_jwt_secret = settings.jwt_secret
        self._orig_jwt_issuer = settings.jwt_issuer
        self._orig_jwt_audience = settings.jwt_audience
        self._orig_cors_origins = settings.cors_allowed_origins

        # Configure JWT for test suite
        settings.jwt_secret = self.test_secret
        settings.jwt_issuer = self.test_issuer
        settings.jwt_audience = self.test_audience
        settings.allow_anonymous_dev = False
        settings.app_env = "staging"

    def tearDown(self):
        settings.api_key = self._orig_api_key
        settings.allow_anonymous_dev = self._orig_anon_dev
        settings.app_env = self._orig_app_env
        settings.jwt_secret = self._orig_jwt_secret
        settings.jwt_issuer = self._orig_jwt_issuer
        settings.jwt_audience = self._orig_jwt_audience
        settings.cors_allowed_origins = self._orig_cors_origins
        session_repo.clear()

    def _create_token(
        self,
        sub: str = "user_123",
        org_id: str = "org_alpha",
        role: str = "user",
        expires_in: int = 3600,
        issuer: str = "https://auth.aiproctor.com/",
        audience: str = "aiproctor-api",
        secret: str = "test_cryptographic_jwt_secret_9999"
    ) -> str:
        now = int(time.time())
        payload = {
            "sub": sub,
            "org_id": org_id,
            "roles": [role],
            "iat": now,
            "nbf": now,
            "exp": now + expires_in,
            "iss": issuer,
            "aud": audience
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    # --- 1. Missing, Malformed, Expired, and Invalid-Signature JWTs ---

    def test_missing_jwt_rejected(self):
        """Verify that requests without credentials return 401 Unauthorized."""
        res = self.client.get("/api/v1/interviews")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Missing authentication credentials", res.json()["detail"])

    def test_malformed_jwt_rejected(self):
        """Verify that a malformed JWT string is rejected with 401."""
        res = self.client.get(
            "/api/v1/interviews",
            headers={"Authorization": "Bearer not.a.valid.jwt.token"}
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid authentication token", res.json()["detail"])

    def test_expired_jwt_rejected(self):
        """Verify that an expired JWT is rejected with 401."""
        expired_token = self._create_token(expires_in=-120)  # expired 2 minutes ago
        res = self.client.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication token has expired", res.json()["detail"])

    def test_invalid_signature_jwt_rejected(self):
        """Verify that a JWT signed with an untrusted secret is rejected with 401."""
        forged_token = self._create_token(secret="attacker_untrusted_secret")
        res = self.client.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {forged_token}"}
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid token signature", res.json()["detail"])

    # --- 2. Incorrect Issuer and Audience Claims ---

    def test_incorrect_issuer_rejected(self):
        """Verify that a token with an unexpected issuer is rejected."""
        bad_issuer_token = self._create_token(issuer="https://rogue-idp.example.com/")
        res = self.client.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {bad_issuer_token}"}
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid token issuer", res.json()["detail"])

    def test_incorrect_audience_rejected(self):
        """Verify that a token scoped for another audience is rejected."""
        bad_aud_token = self._create_token(audience="other-service-api")
        res = self.client.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {bad_aud_token}"}
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid token audience", res.json()["detail"])

    # --- 3. Anti-Spoofing: Verified Claims Override Caller-Supplied Headers ---

    def test_caller_headers_cannot_override_verified_claims(self):
        """
        Verify that caller-supplied headers (X-Organization-Id, X-User-Id, X-Role)
        are completely ignored when a verified JWT is present.
        """
        alice_jwt = self._create_token(sub="alice_legit", org_id="org_alpha", role="user")

        # Caller attempts to spoof identity via headers
        spoofed_headers = {
            "Authorization": f"Bearer {alice_jwt}",
            "X-Organization-Id": "org_beta",       # Spoofed org
            "X-User-Id": "victim_bob",              # Spoofed user
            "X-Role": "admin"                       # Spoofed role
        }

        # Create session
        res = self.client.post("/api/v1/interviews", json={
            "title": "Anti-Spoofing Verification",
            "candidate_id": "cand_99",
            "candidate_name": "Test Candidate",
            "interviewer_id": "int_99"
        }, headers=spoofed_headers)
        self.assertEqual(res.status_code, 201)
        session_data = res.json()

        # Session must be bound strictly to verified JWT claims (org_alpha, alice_legit)
        self.assertEqual(session_data["organization_id"], "org_alpha")
        self.assertEqual(session_data["owner_id"], "alice_legit")
        self.assertNotEqual(session_data["organization_id"], "org_beta")
        self.assertNotEqual(session_data["owner_id"], "victim_bob")

    # --- 4. Cross-Tenant Isolation Across REST & WebSocket ---

    def test_cross_tenant_isolation_with_jwt(self):
        """
        Verify that Tenant Alpha's JWT cannot access or manipulate Tenant Beta's session.
        """
        token_alpha = self._create_token(sub="user_a", org_id="org_alpha")
        token_beta = self._create_token(sub="user_b", org_id="org_beta")

        # Org Alpha creates a session
        create_res = self.client.post("/api/v1/interviews", json={
            "title": "Confidential Alpha Session",
            "candidate_id": "cand_a",
            "candidate_name": "Alice",
            "interviewer_id": "int_a"
        }, headers={"Authorization": f"Bearer {token_alpha}"})
        self.assertEqual(create_res.status_code, 201)
        session_id = create_res.json()["session_id"]

        # Org Beta attempts to access Org Alpha's session -> 404
        get_res = self.client.get(
            f"/api/v1/interviews/{session_id}",
            headers={"Authorization": f"Bearer {token_beta}"}
        )
        self.assertEqual(get_res.status_code, 404)

        # Org Beta lists sessions -> receives 0 (Alpha's session not exposed)
        list_res = self.client.get(
            "/api/v1/interviews",
            headers={"Authorization": f"Bearer {token_beta}"}
        )
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(len(list_res.json()), 0)

        # Org Beta attempts to delete Org Alpha's session -> 404
        del_res = self.client.delete(
            f"/api/v1/interviews/{session_id}",
            headers={"Authorization": f"Bearer {token_beta}"}
        )
        self.assertEqual(del_res.status_code, 404)

    # --- 5. Privilege Escalation & Admin Role Authorization ---

    def test_admin_role_requires_verified_claim(self):
        """
        Verify that a user without 'admin' in their verified token claims cannot
        access cross-tenant sessions, but a verified admin can.
        """
        user_alpha = self._create_token(sub="regular_user", org_id="org_alpha", role="user")
        admin_token = self._create_token(sub="platform_admin", org_id="org_admin", role="admin")

        # Create session under Org Alpha
        create_res = self.client.post("/api/v1/interviews", json={
            "candidate_id": "cand_1", "candidate_name": "Cand", "interviewer_id": "int_1"
        }, headers={"Authorization": f"Bearer {user_alpha}"})
        session_id = create_res.json()["session_id"]

        # Another tenant regular user is rejected
        user_beta = self._create_token(sub="other_user", org_id="org_beta", role="user")
        self.assertEqual(self.client.get(f"/api/v1/interviews/{session_id}", headers={"Authorization": f"Bearer {user_beta}"}).status_code, 404)

        # Verified admin can access
        admin_res = self.client.get(f"/api/v1/interviews/{session_id}", headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(admin_res.status_code, 200)

    # --- 6. Short-Lived Single-Use WebSocket Ticket for Browsers ---

    def test_websocket_ticket_exchange_and_single_use(self):
        """
        Verify browser-safe WebSocket authentication:
        1. Obtain short-lived ticket via authenticated POST /ws-ticket (Bearer JWT).
        2. Connect WebSocket with ?ticket=wst_... -> succeeds.
        3. Attempting to reuse the consumed ticket fails with WS 1008.
        4. Attempting to use a ticket for another session fails with WS 1008.
        """
        token_alpha = self._create_token(sub="alice", org_id="org_alpha")

        # Create session
        res = self.client.post("/api/v1/interviews", json={
            "candidate_id": "c_ws", "candidate_name": "Cand", "interviewer_id": "i_ws"
        }, headers={"Authorization": f"Bearer {token_alpha}"})
        session_id = res.json()["session_id"]

        # 1. Request ticket
        ticket_res = self.client.post(
            "/api/v1/interviews/ws-ticket",
            json={"session_id": session_id},
            headers={"Authorization": f"Bearer {token_alpha}"}
        )
        self.assertEqual(ticket_res.status_code, 200)
        ticket = ticket_res.json()["ticket"]
        self.assertTrue(ticket.startswith("wst_"))
        self.assertEqual(ticket_res.json()["expires_in"], 60)

        # 2. Connect WebSocket with ticket -> Success (receives snapshot)
        with self.client.websocket_connect(f"/api/v1/interviews/ws/{session_id}?ticket={ticket}") as ws:
            msg = ws.receive_json()
            self.assertEqual(msg["type"], "session_snapshot")

        # 3. Reuse same ticket -> Rejected (single-use consumed)
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/api/v1/interviews/ws/{session_id}?ticket={ticket}") as ws:
                ws.receive_json()

        # 4. Another tenant cannot generate a ticket for this session
        token_beta = self._create_token(sub="bob", org_id="org_beta")
        unauth_ticket_res = self.client.post(
            "/api/v1/interviews/ws-ticket",
            json={"session_id": session_id},
            headers={"Authorization": f"Bearer {token_beta}"}
        )
        self.assertEqual(unauth_ticket_res.status_code, 404)

    # --- 7. HTTP Health Check Endpoints ---

    def test_health_check_endpoints_safe(self):
        """Verify /health and /api/v1/health return 200 without exposing credentials or internal paths."""
        for path in ("/health", "/api/v1/health"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("status", data)
            self.assertIn("database", data)
            self.assertIn("environment", data)
            # Ensure no credentials or URLs are leaked
            body_text = res.text.lower()
            self.assertNotIn("password", body_text)
            self.assertNotIn("postgresql://", body_text)
            self.assertNotIn("secret", body_text)

    # --- 8. CORS Configuration Enforcement ---

    def test_cors_explicit_origins_enforced(self):
        """Verify CORS allows configured origins and blocks disallowed origins without using wildcard."""
        # Allowed origin returns 200 and echo origin header
        allowed_res = self.client.options(
            "/api/v1/interviews",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "POST"
            }
        )
        self.assertEqual(allowed_res.status_code, 200)
        self.assertEqual(allowed_res.headers.get("access-control-allow-origin"), "http://localhost:8000")
        self.assertNotEqual(allowed_res.headers.get("access-control-allow-origin"), "*")

        # Disallowed origin is rejected with 400 Bad Request
        disallowed_res = self.client.options(
            "/api/v1/interviews",
            headers={
                "Origin": "https://rogue-origin.evil.com",
                "Access-Control-Request-Method": "POST"
            }
        )
        self.assertEqual(disallowed_res.status_code, 400)

    # --- 9. Server API Key Backward Compatibility ---

    def test_server_api_key_still_functional(self):
        """Verify that server-to-server calls with INTERVIEW_API_KEY remain supported."""
        settings.api_key = "server_gateway_key_777"

        res = self.client.get(
            "/api/v1/interviews",
            headers={"X-API-Key": "server_gateway_key_777"}
        )
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
