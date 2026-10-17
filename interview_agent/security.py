import hmac
import time
import secrets
import asyncio
import logging
from typing import Optional, Dict, Any, List
import jwt
from jwt import PyJWKClient, PyJWTError, ExpiredSignatureError, InvalidIssuerError, InvalidAudienceError, InvalidSignatureError, DecodeError
from pydantic import BaseModel
from fastapi import Header, HTTPException, status
from interview_agent.config import settings

logger = logging.getLogger(__name__)


class Principal(BaseModel):
    """
    Represents an authenticated caller (user, service, or organization).
    Enforces tenant and session ownership boundaries.
    """
    principal_id: str
    organization_id: Optional[str] = None
    role: str = "user"  # "admin", "system", "interviewer", "candidate", "user"
    is_authenticated: bool = True
    token_type: str = "jwt"  # "jwt", "ticket", "api_key", "anonymous_dev"
    claims: Optional[Dict[str, Any]] = None

    def can_access_session(self, session: Any) -> bool:
        """
        Determine if the principal is authorized to read, modify, or stream the session.
        """
        # System/Admin principals have universal access
        if self.role in ("admin", "system"):
            return True

        # Multi-tenant isolation: check organization boundary
        if getattr(session, "organization_id", None):
            if self.organization_id and self.organization_id == session.organization_id:
                return True
            return False

        # Session ownership boundary: check owner or participant IDs
        owner_id = getattr(session, "owner_id", None)
        if owner_id:
            if self.principal_id == owner_id:
                return True
            if self.principal_id in (getattr(session, "candidate_id", None), getattr(session, "interviewer_id", None)):
                return True
            return False

        # If neither organization_id nor owner_id was explicitly tagged on the session,
        # allow if principal is in the same default org or in development mode
        if settings.allow_anonymous_dev and settings.app_env != "production":
            return True

        # In secured environments, untagged sessions are only accessible by admins
        return self.role in ("admin", "system")


def secure_compare(val1: Optional[str], val2: Optional[str]) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if val1 is None or val2 is None:
        return False
    return hmac.compare_digest(val1.encode("utf-8"), val2.encode("utf-8"))


# --- JWKS Cache & Client ---
_jwk_client: Optional[PyJWKClient] = None
_jwk_client_url: Optional[str] = None


def get_jwk_client(jwks_url: str) -> PyJWKClient:
    global _jwk_client, _jwk_client_url
    if _jwk_client is None or _jwk_client_url != jwks_url:
        _jwk_client = PyJWKClient(jwks_url)
        _jwk_client_url = jwks_url
    return _jwk_client


def verify_jwt_token(token: str) -> Principal:
    """
    Cryptographically verifies a JWT token using trusted public keys (JWKS / PEM) or shared secret.
    Validates signature, expiration, issuer, and audience.
    Derives principal_id, organization_id, and role strictly from verified claims.
    Caller-supplied identity headers are ignored and never override verified claims.
    """
    # 1. Resolve signing key based on configuration
    key: Any = None
    algorithms = settings.jwt_algorithms

    # Check unverified header to ensure algorithm matches allowed set
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: Malformed JWT header ({e})"
        )

    alg = unverified_header.get("alg")
    if not alg or alg not in algorithms:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported JWT algorithm '{alg}'. Allowed algorithms: {algorithms}"
        )

    if settings.jwt_jwks_url:
        try:
            jwk_client = get_jwk_client(settings.jwt_jwks_url)
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            key = signing_key.key
        except Exception as e:
            logger.error(f"Failed to fetch JWKS signing key: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to verify token signature: JWKS signing key lookup failed."
            )
    elif settings.jwt_public_key:
        key = settings.jwt_public_key.strip()
    elif settings.jwt_secret:
        key = settings.jwt_secret
    else:
        # No JWT verification keys configured on server
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT verification failed: No trusted keys, JWKS URL, or secret configured on server."
        )

    # 2. Decode and cryptographically verify claims
    decode_options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_nbf": True,
        "verify_iat": True,
    }

    decode_kwargs: Dict[str, Any] = {
        "algorithms": algorithms,
        "options": decode_options
    }

    if settings.jwt_issuer:
        decode_kwargs["issuer"] = settings.jwt_issuer
        decode_options["verify_iss"] = True
    else:
        decode_options["verify_iss"] = False

    if settings.jwt_audience:
        decode_kwargs["audience"] = settings.jwt_audience
        decode_options["verify_aud"] = True
    else:
        decode_options["verify_aud"] = False

    try:
        payload = jwt.decode(token, key, **decode_kwargs)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired."
        )
    except InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer."
        )
    except InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience."
        )
    except InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature."
        )
    except (DecodeError, PyJWTError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {e}"
        )

    # 3. Extract and validate authoritative claims
    principal_id = payload.get("sub") or payload.get("user_id") or payload.get("uid")
    if not principal_id or not str(principal_id).strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required subject claim ('sub')."
        )
    principal_id = str(principal_id).strip()

    # Extract organization/tenant claim
    org_id = (
        payload.get("org_id")
        or payload.get("organization_id")
        or payload.get("tenant_id")
        or payload.get("https://aiproctor.com/org_id")
    )
    if not org_id and isinstance(payload.get("app_metadata"), dict):
        org_id = payload["app_metadata"].get("org_id") or payload["app_metadata"].get("tenant_id")

    org_id = str(org_id).strip() if org_id else None

    # Derive role strictly from verified claims
    raw_roles = (
        payload.get("roles")
        or payload.get("role")
        or payload.get("https://aiproctor.com/roles")
    )
    if not raw_roles and isinstance(payload.get("app_metadata"), dict):
        raw_roles = payload["app_metadata"].get("roles") or payload["app_metadata"].get("role")

    if isinstance(raw_roles, str):
        roles_list = [raw_roles.lower().strip()]
    elif isinstance(raw_roles, list):
        roles_list = [str(r).lower().strip() for r in raw_roles]
    else:
        roles_list = []

    if any(r in ("admin", "system", "superadmin") for r in roles_list):
        role = "admin"
    elif any(r in ("interviewer", "recruiter", "lead") for r in roles_list):
        role = "interviewer"
    elif any(r in ("candidate",) for r in roles_list):
        role = "candidate"
    else:
        role = "user"

    return Principal(
        principal_id=principal_id,
        organization_id=org_id,
        role=role,
        is_authenticated=True,
        token_type="jwt",
        claims=payload
    )


# --- Browser WebSocket Short-Lived Ticket Manager ---

class WebSocketTicketManager:
    """
    Manages short-lived, single-use tickets for authenticating browser WebSocket connections.
    Avoids putting long-lived JWTs or API keys in query parameters where URLs can be logged.
    """
    def __init__(self, default_ttl: int = 60):
        self.default_ttl = default_ttl
        self._tickets: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def create_ticket(self, principal: Principal, session_id: str, ttl: Optional[int] = None) -> str:
        async with self._lock:
            now = time.time()
            # Clean expired tickets
            expired = [k for k, v in self._tickets.items() if v["expires_at"] <= now]
            for k in expired:
                del self._tickets[k]

            ticket = f"wst_{secrets.token_urlsafe(32)}"
            self._tickets[ticket] = {
                "principal": principal,
                "session_id": session_id,
                "expires_at": now + (ttl or self.default_ttl)
            }
            return ticket

    async def consume_ticket(self, ticket: str, session_id: str) -> Optional[Principal]:
        async with self._lock:
            now = time.time()
            data = self._tickets.pop(ticket, None)  # Atomic single-use pop
            if not data:
                return None
            if data["expires_at"] < now:
                return None
            if data["session_id"] != session_id:
                return None
            return data["principal"]


ws_ticket_manager = WebSocketTicketManager(default_ttl=settings.ws_ticket_expiry_seconds)


# --- Dependency Authentication Resolver ---

async def get_current_principal(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
) -> Principal:
    """
    FastAPI dependency for authenticating callers and resolving their Principal identity.
    Priority 1: Bearer JWT token (verified cryptographically).
    Priority 2: Pre-shared Server API Key (server-to-server gateway).
    Priority 3: Anonymous Development Mode (only if APP_ENV != production).
    """
    # 1. Extract Bearer Token from Authorization Header
    bearer_token = None
    if authorization and authorization.startswith("Bearer "):
        bearer_token = authorization[7:].strip()

    # Determine if bearer token looks like a JWT (header.payload.signature)
    is_jwt_candidate = bool(bearer_token and bearer_token.count(".") == 2)

    # Has JWT verification been configured on the server?
    jwt_configured = bool(settings.jwt_jwks_url or settings.jwt_public_key or settings.jwt_secret)

    if bearer_token and (is_jwt_candidate or jwt_configured):
        # Authenticate via verified JWT
        principal = verify_jwt_token(bearer_token)
        # Note: Caller-supplied headers (X-Organization-Id, X-User-Id, X-Role) are ignored
        return principal

    # 2. Check Server API Key (X-API-Key or Bearer token matching settings.api_key)
    api_token = x_api_key or bearer_token
    if api_token and settings.api_key and secure_compare(api_token, settings.api_key):
        # Authorized Server-to-Server caller
        org_id = x_organization_id or "default-org"
        user_id = x_user_id or "server-principal"
        # Enforce least privilege for server key callers: role defaults to user
        role = "user"
        return Principal(
            principal_id=user_id,
            organization_id=org_id,
            role=role,
            is_authenticated=True,
            token_type="api_key"
        )

    # 3. Anonymous Development Mode (only permitted when APP_ENV != production)
    if settings.allow_anonymous_dev and settings.app_env != "production":
        # If caller passed an invalid API key, reject
        if api_token and settings.api_key and not secure_compare(api_token, settings.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials."
            )

        return Principal(
            principal_id=x_user_id or "dev-user",
            organization_id=x_organization_id or "dev-org",
            role=x_role or ("user" if x_organization_id else "admin"),
            is_authenticated=True,
            token_type="anonymous_dev"
        )

    # 4. Production / Secured Mode Rejection
    if not api_token and not bearer_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials for interview service."
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials."
    )


def check_session_access(session: Optional[Any], principal: Principal) -> Any:
    """
    Verify that the session exists and the principal has authorization to access it.
    Returns HTTP 404 on both missing and unauthorized sessions to prevent resource enumeration.
    """
    if not session or not principal.can_access_session(session):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview session not found"
        )
    return session
