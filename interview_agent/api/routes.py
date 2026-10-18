from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Header, status
from pydantic import BaseModel

from interview_agent.schemas.interview import (
    InterviewSessionCreate,
    InterviewSessionResponse,
    SessionStatus,
)
from interview_agent.schemas.transcript import (
    AudioChunkPayload,
    TranscriptResponse,
)
from interview_agent.schemas.evaluation import (
    AnswerEvaluation,
    InterviewNote,
    FinalReport,
)
from interview_agent.services.interview_session_service import interview_session_service
from interview_agent.security import Principal, get_current_principal, check_session_access
from interview_agent.config import settings

router = APIRouter(prefix="/interviews", tags=["Interview Intelligence Agent"])

class StatusUpdateRequest(BaseModel):
    status: SessionStatus

class SimulateRequest(BaseModel):
    pass

class WebSocketTicketRequest(BaseModel):
    session_id: str

class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in: int
    session_id: str

# Legacy alias for backward compatibility with existing tests/references
verify_interview_auth = get_current_principal


@router.post("/ws-ticket", response_model=WebSocketTicketResponse)
async def generate_websocket_ticket(
    body: WebSocketTicketRequest,
    principal: Principal = Depends(get_current_principal)
):
    """
    Generate a short-lived, single-use ticket for authenticating browser WebSockets.
    Eliminates exposure of long-lived JWTs or credentials in logged query URLs.
    """
    session = check_session_access(interview_session_service.get_session(body.session_id), principal)
    from interview_agent.security import ws_ticket_manager
    ticket = await ws_ticket_manager.create_ticket(
        principal=principal,
        session_id=session.session_id,
        ttl=settings.ws_ticket_expiry_seconds
    )
    return WebSocketTicketResponse(
        ticket=ticket,
        expires_in=settings.ws_ticket_expiry_seconds,
        session_id=session.session_id
    )


@router.post("", response_model=InterviewSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_interview_session(
    data: InterviewSessionCreate,
    principal: Principal = Depends(get_current_principal)
):
    """Create a new interview session with optional custom rubric configuration and consent flags."""
    return interview_session_service.create_session(data, principal=principal)


@router.get("", response_model=List[InterviewSessionResponse])
async def list_interview_sessions(
    principal: Principal = Depends(get_current_principal)
):
    """List interview sessions accessible to the authenticated principal."""
    return interview_session_service.list_sessions(principal=principal)


@router.get("/{session_id}", response_model=InterviewSessionResponse)
async def get_interview_session(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Retrieve interview session state and metrics."""
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    return session.to_response()


@router.post("/{session_id}/status", response_model=InterviewSessionResponse)
async def update_session_status(
    session_id: str,
    body: StatusUpdateRequest,
    principal: Principal = Depends(get_current_principal)
):
    """Update interview session status (active, paused, completed)."""
    check_session_access(interview_session_service.get_session(session_id), principal)
    session = interview_session_service.update_status(session_id, body.status)
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return session.to_response()


@router.post("/{session_id}/audio")
async def ingest_audio_chunk(
    session_id: str,
    chunk: AudioChunkPayload,
    principal: Principal = Depends(get_current_principal)
):
    """Ingest a streaming audio chunk from authorized meeting media pipeline."""
    check_session_access(interview_session_service.get_session(session_id), principal)
    from interview_agent.services.audio_adapter import AudioAdapterException
    try:
        segment = await interview_session_service.ingest_audio_chunk(session_id, chunk)
    except AudioAdapterException as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not segment:
        return {"status": "accepted_or_duplicate", "session_id": session_id}
    return {"status": "transcribed", "segment": segment}


@router.post("/{session_id}/simulate-mock")
async def simulate_mock_interview(
    session_id: str,
    auto_finalize: bool = True,
    step_delay: float = 0.0,
    principal: Principal = Depends(get_current_principal)
):
    """Simulates an automated full technical interview conversation for testing/dev."""
    if settings.app_env.lower() in ("production", "prod"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development simulation endpoints are strictly prohibited in production mode."
        )

    session = check_session_access(interview_session_service.get_session(session_id), principal)
    from interview_agent.services.audio_adapter import AudioAdapterException
    try:
        segments = await interview_session_service.run_mock_simulation(
            session_id, auto_finalize=auto_finalize, step_delay=step_delay
        )
    except AudioAdapterException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation error: {str(e)}")

    return {
        "status": "simulation_completed",
        "session_id": session_id,
        "segments_generated": len(segments),
        "total_evaluations": len(session.evaluations),
        "report_generated": session.final_report is not None
    }


@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Retrieve all transcribed segments for an interview session."""
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    return TranscriptResponse(
        session_id=session.session_id,
        total_segments=len(session.transcript_segments),
        segments=session.transcript_segments
    )


@router.get("/{session_id}/notes", response_model=List[InterviewNote])
async def get_interview_notes(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Retrieve structured notes generated during the interview."""
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    return session.notes


@router.get("/{session_id}/evaluations", response_model=List[AnswerEvaluation])
async def get_evaluations(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Retrieve question-wise evaluations."""
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    return session.evaluations


@router.post("/{session_id}/finalize", response_model=FinalReport)
async def finalize_interview(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Finalize an interview session and generate the executive summary report."""
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    if session.status == SessionStatus.COMPLETED and session.final_report:
        return session.final_report

    report = await interview_session_service.finalize_session(session_id)
    if not report:
        raise HTTPException(status_code=500, detail="Failed to generate final report")
    return report


@router.get("/{session_id}/report", response_model=FinalReport)
async def get_interview_report(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Retrieve the generated final report for an interview session."""
    session = check_session_access(interview_session_service.get_session(session_id), principal)
    if not session.final_report:
        report = await interview_session_service.finalize_session(session_id)
        return report
    return session.final_report


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview_session(
    session_id: str,
    principal: Principal = Depends(get_current_principal)
):
    """Privacy/GDPR compliance: Delete all interview transcripts, evaluations, notes, and retained raw audio."""
    check_session_access(interview_session_service.get_session(session_id), principal)
    deleted = await interview_session_service.delete_session(session_id, principal)
    if not deleted:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return None

