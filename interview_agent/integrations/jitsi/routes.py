import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Header, Request, status
from pydantic import BaseModel

from interview_agent.security import Principal, get_current_principal, check_session_access
from interview_agent.models.interview_session import session_repo
from interview_agent.services.interview_session_service import interview_session_service
from interview_agent.schemas.interview import ParticipantRole
from interview_agent.integrations.jitsi.schemas import (
    JitsiRoomConfig,
    JitsiTranscriptEvent,
    JitsiWebhookPayload,
)
from interview_agent.integrations.jitsi.room_manager import jitsi_room_manager
from interview_agent.integrations.jitsi.adapter import jitsi_adapter
from interview_agent.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews", tags=["Jitsi Meet Integration"])


@router.get("/{session_id}/jitsi/config", response_model=JitsiRoomConfig)
async def get_jitsi_room_config(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """
    Retrieve or initialize the Jitsi Meet room configuration for an authorized interview session.
    Generates an unpredictable room name and returns server domain, URLs, and optional signed meeting JWT.
    """
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    return jitsi_room_manager.get_or_create_room(session)


@router.post("/{session_id}/jitsi/room", response_model=JitsiRoomConfig)
async def create_or_refresh_jitsi_room(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """
    Explicitly creates or retrieves the unique Jitsi room associated with the session.
    Enforces authorization and session ownership.
    """
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    return jitsi_room_manager.get_or_create_room(session)


@router.post("/{session_id}/jitsi/transcript-event")
async def ingest_jitsi_transcript_event(
    session_id: str,
    event: JitsiTranscriptEvent,
    request: Request,
    x_jitsi_signature: Optional[str] = Header(None, alias="X-Jitsi-Signature"),
    principal: Optional[Principal] = Depends(get_current_principal)
):
    """
    Ingest a real-time transcript segment from a Jitsi bridge transcriber proxy (e.g., opus-transcriber-proxy).
    Requires either:
    1. Authenticated session principal (Bearer JWT or API Key).
    2. Valid HMAC-SHA256 signature in X-Jitsi-Signature header.
    """
    session = interview_session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    # Verify authorization: either principal or webhook HMAC
    if not principal:
        raw_body = await request.body()
        is_valid_sig = jitsi_adapter.verify_webhook_signature(raw_body, x_jitsi_signature)
        if not is_valid_sig:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Valid authentication credentials or Jitsi webhook signature required."
            )
    else:
        check_session_access(session, principal)

    segment = await jitsi_adapter.process_transcript_event(session_id, event)
    if not segment:
        return {"status": "skipped_duplicate_or_empty", "session_id": session_id}

    return {"status": "ingested", "segment": segment}


@router.post("/jitsi/webhook")
@router.post("/{session_id}/jitsi/webhook")
async def handle_jitsi_webhook(
    request: Request,
    payload: JitsiWebhookPayload,
    session_id: Optional[str] = None,
    x_jitsi_signature: Optional[str] = Header(None, alias="X-Jitsi-Signature")
):
    """
    Generic webhook receiver for Jitsi / 8x8 JaaS / Jigasi transcription events.
    Verifies HMAC signature, extracts transcription payloads, verifies room-session binding,
    and routes authoritative segments to the intelligence pipeline.
    """
    # Check headers for signature (support X-Jitsi-Signature, X-8x8-Signature, or Authorization)
    sig_header = (
        x_jitsi_signature
        or request.headers.get("x-8x8-signature")
        or request.headers.get("authorization")
    )

    raw_body = await request.body()
    is_valid_sig = jitsi_adapter.verify_webhook_signature(raw_body, sig_header)
    if not is_valid_sig:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Jitsi webhook signature"
        )

    # Resolve target session_id from URL or payload
    target_session_id = session_id or payload.session_id or payload.sessionId
    declared_room = payload.room or payload.fqn or payload.data.get("room_name")

    if not target_session_id and declared_room:
        # Extract session_id from room name pattern: AiProtctor-Interview-<session_id>-<entropy>
        room_base = declared_room.split("/")[-1]
        parts = room_base.split("-")
        if len(parts) >= 3 and parts[0] == "AiProtctor" and parts[1] == "Interview":
            target_session_id = parts[2]

    if not target_session_id:
        raise HTTPException(status_code=400, detail="Missing session_id in webhook URL or payload")

    session = interview_session_service.get_session(target_session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Interview session '{target_session_id}' not found")

    # Verify room name binding to prevent cross-session event injection
    if declared_room:
        room_base = declared_room.split("/")[-1]
        expected_room = session.metadata.get("jitsi_room_name", "")
        if expected_room and room_base != expected_room:
            logger.warning(
                f"Rejecting Jitsi webhook: Mismatched room '{room_base}' for session '{target_session_id}' "
                f"(expected '{expected_room}')"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Room name '{room_base}' does not match interview session association."
            )

    event_type = (payload.eventType or payload.event or "").upper()
    logger.info(f"Received Jitsi webhook '{event_type}' for session '{target_session_id}'")

    if event_type in ("TRANSCRIPTION_EVENT", "TRANSCRIPT_SEGMENT", "TRANSCRIPTION_CHUNK", "TRANSCRIPTION_COMPLETED"):
        data = payload.data
        participant_data = data.get("participant", {})
        if not isinstance(participant_data, dict):
            participant_data = {}

        p_id = data.get("participant_id") or participant_data.get("id") or "unknown"
        p_name = data.get("speaker_name") or participant_data.get("name")
        p_role = data.get("speaker_role") or participant_data.get("role")
        text = data.get("text") or data.get("transcript") or ""
        start_time = float(data.get("start_time") or data.get("time") or 0.0)
        duration = float(data.get("duration") or 1.0)
        end_time = float(data.get("end_time") or (start_time + duration))
        seq_num = data.get("sequence_number")
        is_final = bool(data.get("is_final", data.get("isFinal", True)))
        confidence = float(data.get("confidence") or 1.0)

        if not text.strip():
            return {"status": "skipped_empty_text", "session_id": target_session_id}

        t_event = JitsiTranscriptEvent(
            session_id=target_session_id,
            room_name=declared_room or session.metadata.get("jitsi_room_name", ""),
            participant_id=p_id,
            speaker_name=p_name,
            speaker_role=p_role,
            text=text.strip(),
            start_time=start_time,
            end_time=end_time,
            sequence_number=seq_num,
            is_final=is_final,
            confidence=confidence,
            is_simulated=False
        )
        seg = await jitsi_adapter.process_transcript_event(target_session_id, t_event)
        return {"status": "processed", "segment": seg}

    return {"status": "ignored_event_type", "event": event_type}


@router.post("/{session_id}/jitsi/simulate-dev")
async def simulate_jitsi_bridge_interview(
    session_id: str,
    auto_finalize: bool = True,
    principal: Principal = Depends(get_current_principal)
):
    """
    Explicitly labeled development/test harness:
    Simulates genuine multi-participant Jitsi bridge transcription events (Interviewer asking, Candidate answering)
    routed through the JitsiTranscriptionAdapter into PostgreSQL and the intelligence engine.
    All simulated segments are marked with is_simulated=True.
    """
    if settings.app_env.lower() in ("production", "prod"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development simulation endpoints are strictly prohibited in production mode."
        )

    session = check_session_access(interview_session_service.get_session(session_id), principal)

    sample_dialogue = [
        {
            "role": ParticipantRole.INTERVIEWER,
            "speaker_id": session.interviewer_id,
            "speaker_name": session.interviewer_name,
            "text": "Hello, thank you for joining this Jitsi interview. Can you explain how database sharding works and how you would design a sharding key?",
            "duration": 5.0
        },
        {
            "role": ParticipantRole.CANDIDATE,
            "speaker_id": session.candidate_id,
            "speaker_name": session.candidate_name,
            "text": "In database sharding, we horizontally partition data across multiple database instances using a consistent hash of the sharding key. For example, in an e-commerce platform we might shard by user_id or account_id to maintain locality and prevent hot partition imbalances.",
            "duration": 10.0
        },
        {
            "role": ParticipantRole.INTERVIEWER,
            "speaker_id": session.interviewer_id,
            "speaker_name": session.interviewer_name,
            "text": "What happens when a distributed transaction needs to write across two different shards?",
            "duration": 4.0
        },
        {
            "role": ParticipantRole.CANDIDATE,
            "speaker_id": session.candidate_id,
            "speaker_name": session.candidate_name,
            "text": "Cross-shard transactions typically require a two-phase commit protocol or an asynchronous saga pattern with compensating transactions. Two-phase commit guarantees ACID semantics but introduces latency, whereas the saga pattern provides eventual consistency.",
            "duration": 9.0
        }
    ]

    clock = session.last_speech_timestamp or 0.0
    produced_segments = []

    for idx, turn in enumerate(sample_dialogue):
        clock += 1.0
        start = clock
        end = clock + turn["duration"]
        clock = end

        jev = JitsiTranscriptEvent(
            session_id=session_id,
            room_name=session.metadata.get("jitsi_room_name", "AiProtctor-Interview-Sim"),
            participant_id=turn["speaker_id"],
            speaker_name=turn["speaker_name"],
            speaker_role=turn["role"],
            text=turn["text"],
            start_time=start,
            end_time=end,
            sequence_number=idx + 1,
            confidence=0.98,
            is_simulated=True
        )

        seg = await jitsi_adapter.process_transcript_event(session_id, jev)
        if seg:
            produced_segments.append(seg)

    if auto_finalize:
        await interview_session_service.finalize_session(session_id)

    return {
        "status": "jitsi_simulation_completed",
        "session_id": session_id,
        "segments_ingested": len(produced_segments),
        "total_notes": len(session.notes),
        "total_evaluations": len(session.evaluations),
        "final_report_generated": session.final_report is not None
    }
