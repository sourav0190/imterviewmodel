import secrets
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import jwt

from interview_agent.config import settings
from interview_agent.models.interview_session import InterviewSessionModel, session_repo
from interview_agent.integrations.jitsi.schemas import JitsiRoomConfig, JitsiDeploymentType

logger = logging.getLogger(__name__)


class JitsiRoomManager:
    """
    Manages Jitsi room lifecycle, unpredictable room name generation,
    session association, and deployment-appropriate token signing.
    """

    def determine_deployment_type(self) -> JitsiDeploymentType:
        server = settings.jitsi_server_url.lower()
        if "8x8.vc" in server or bool(settings.jitsi_app_id and "meet.jit.si" not in server):
            return JitsiDeploymentType.JAAS
        if "meet.jit.si" in server:
            return JitsiDeploymentType.PUBLIC
        return JitsiDeploymentType.SELF_HOSTED

    def generate_unpredictable_room_name(self, session_id: str) -> str:
        """
        Generates a high-entropy, unpredictable room name for privacy and collision prevention.
        On public meet.jit.si, high-entropy unguessable names are the primary barrier
        against accidental or malicious eavesdropping.
        """
        prefix = settings.jitsi_room_prefix.strip().replace(" ", "-")
        # 16 bytes of cryptographic randomness = 128 bits of entropy
        entropy_token = secrets.token_hex(8)
        clean_session_id = session_id.replace("int_", "")
        return f"{prefix}-{clean_session_id}-{entropy_token}"

    def get_or_create_room(
        self,
        session: InterviewSessionModel,
        base_url: Optional[str] = None
    ) -> JitsiRoomConfig:
        """
        Retrieves the existing room associated with the session or generates a new one.
        Persists room association in the session repository.
        """
        meta = session.metadata
        room_name = meta.get("jitsi_room_name")

        if not room_name:
            room_name = self.generate_unpredictable_room_name(session.session_id)
            meta["jitsi_room_name"] = room_name
            meta["jitsi_room_created_at"] = datetime.utcnow().isoformat()
            meta["jitsi_server_url"] = settings.jitsi_server_url
            meta["jitsi_domain"] = settings.jitsi_domain
            session.touch()
            session_repo.save(session)
            logger.info(f"Associated new Jitsi room '{room_name}' with session '{session.session_id}'")

        deployment = self.determine_deployment_type()
        jwt_token = self._generate_jitsi_jwt(session, room_name, is_moderator=True)

        server_url = settings.jitsi_server_url
        domain = settings.jitsi_domain

        # URLs for direct browser join
        interviewer_url = f"{server_url}/{room_name}#userInfo.displayName=\"{session.interviewer_name}\""
        candidate_url = f"{server_url}/{room_name}#userInfo.displayName=\"{session.candidate_name}\""

        return JitsiRoomConfig(
            session_id=session.session_id,
            room_name=room_name,
            server_url=server_url,
            domain=domain,
            subject=f"Interview: {session.title}",
            interviewer_name=session.interviewer_name,
            candidate_name=session.candidate_name,
            interviewer_join_url=interviewer_url,
            candidate_join_url=candidate_url,
            jwt_token=jwt_token,
            transcription_enabled=settings.jitsi_transcription_enabled,
            consent_required=True,
            deployment_type=deployment,
            created_at=session.created_at
        )

    def _generate_jitsi_jwt(
        self,
        session: InterviewSessionModel,
        room_name: str,
        is_moderator: bool = True
    ) -> Optional[str]:
        """
        Generates a signed JWT token if Jitsi credentials are configured (JaaS or authenticated self-hosted).
        Returns None for public meet.jit.si deployments (which ignore or reject custom JWTs).
        """
        secret = settings.jitsi_secret
        app_id = settings.jitsi_app_id
        if not secret or not app_id:
            return None

        now = datetime.utcnow()
        payload = {
            "aud": "jitsi",
            "iss": app_id,
            "sub": settings.jitsi_domain,
            "room": room_name,
            "exp": int((now + timedelta(hours=3)).timestamp()),
            "nbf": int(now.timestamp()),
            "context": {
                "user": {
                    "id": session.interviewer_id if is_moderator else session.candidate_id,
                    "name": session.interviewer_name if is_moderator else session.candidate_name,
                    "moderator": is_moderator
                },
                "features": {
                    "recording": False,
                    "livestreaming": False,
                    "transcription": True
                }
            }
        }

        try:
            algorithm = "RS256" if "BEGIN RSA PRIVATE KEY" in secret or "BEGIN PRIVATE KEY" in secret else "HS256"
            token = jwt.encode(payload, secret, algorithm=algorithm)
            return token
        except Exception as e:
            logger.warning(f"Failed to generate Jitsi JWT token: {e}")
            return None


jitsi_room_manager = JitsiRoomManager()
