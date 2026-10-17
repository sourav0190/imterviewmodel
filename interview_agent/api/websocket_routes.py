import logging
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from interview_agent.services.interview_session_service import interview_session_service
from interview_agent.security import Principal, secure_compare, verify_jwt_token, ws_ticket_manager
from interview_agent.config import settings

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["Interview WebSocket Stream"])

@ws_router.websocket("/ws/{session_id}")
async def interview_websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    ticket: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
    org_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """
    Real-time WebSocket stream for an active interview session.
    Streams live transcript segments, notes, provisional evaluations, and final reports.
    Enforces cryptographic authentication and session ownership before accepting subscriptions.

    Authentication Options:
    1. Short-Lived Single-Use Ticket (Recommended for browsers): ?ticket=wst_...
       Obtained via authenticated POST /api/v1/interviews/ws-ticket. Prevents long-lived tokens in query URLs.
    2. Header-Based Bearer JWT / API Key (Recommended for automated scripts/agents):
       Authorization: Bearer <jwt> or X-API-Key: <key>.
    3. Query token fallback (Dev/Test only).
    """
    principal: Optional[Principal] = None

    # Option 1: Browser Single-Use Short-Lived Ticket
    if ticket:
        principal = await ws_ticket_manager.consume_ticket(ticket, session_id)
        if not principal:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired WebSocket ticket")
            return

    # Option 2: Headers or Direct Token
    if not principal:
        auth_header = websocket.headers.get("authorization")
        token_val = websocket.headers.get("x-api-key")
        if not token_val and auth_header and auth_header.startswith("Bearer "):
            token_val = auth_header[7:].strip()
        if not token_val:
            token_val = token

        org_val = websocket.headers.get("x-organization-id") or org_id
        user_val = websocket.headers.get("x-user-id") or user_id

        is_jwt = bool(token_val and (token_val.count(".") == 2 or settings.jwt_jwks_url or settings.jwt_public_key or settings.jwt_secret))

        if token_val and is_jwt:
            try:
                principal = verify_jwt_token(token_val)
            except Exception as e:
                logger.warning(f"WebSocket JWT authentication failed: {e}")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid JWT token")
                return
        elif token_val and settings.api_key and secure_compare(token_val, settings.api_key):
            principal = Principal(
                principal_id=user_val or "server-principal",
                organization_id=org_val or "default-org",
                role="user",
                is_authenticated=True,
                token_type="api_key"
            )
        elif settings.allow_anonymous_dev and settings.app_env != "production":
            if token_val and settings.api_key and not secure_compare(token_val, settings.api_key):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid credentials")
                return
            principal = Principal(
                principal_id=user_val or "dev-user",
                organization_id=org_val or "dev-org",
                role="user" if org_val else "admin",
                is_authenticated=True,
                token_type="anonymous_dev"
            )
        else:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication failed")
            return

    # Verify session exists and principal has authorization
    session = interview_session_service.get_session(session_id)
    if not session or not principal.can_access_session(session):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Session not found or unauthorized")
        return

    # Connect and stream
    await interview_session_service.connect_ws(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await interview_session_service.disconnect_ws(session_id, websocket)
        logger.info(f"WebSocket client disconnected from session: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        await interview_session_service.disconnect_ws(session_id, websocket)
