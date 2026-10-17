from typing import Optional, Dict
import logging
from interview_agent.schemas.interview import ParticipantRole, Participant
from interview_agent.models.interview_session import InterviewSessionModel

logger = logging.getLogger(__name__)


class SpeakerService:
    """
    Resolves and validates speaker identity and conversational roles.
    
    Speaker Attribution Strategy:
    ----------------------------
    1. Primary Architecture (Track-Level Attribution):
       In production WebRTC / SFU meeting environments (LiveKit, Mediasoup, Janus, or browser WebRTC tracks),
       each participant streams on a dedicated, authenticated audio track tagged with their `participant_id`.
       Because tracks are discrete at the media layer, speaker identity is 100% deterministic and does NOT
       depend on acoustic diarization or arrival-order guessing.
       
    2. Fallback Architecture (Single Mixed Stream / Turn-Taking Heuristics):
       When meeting infrastructure provides only a single combined audio channel and the transcription
       provider does not perform server-side acoustic diarization, speaker attribution falls back to
       turn-taking role assignment (Interviewer asks -> Candidate responds). This limitation is explicitly
       flagged in logs and domain models to avoid claiming false acoustic certainty.
    """

    def __init__(self):
        # Cache for diarization speaker label mappings per session (session_id -> {label: role})
        self._diarization_map: Dict[str, Dict[str, str]] = {}

    def resolve_speaker(
        self,
        session: InterviewSessionModel,
        participant_id: str,
        hinted_role: Optional[ParticipantRole] = None,
        speaker_name: Optional[str] = None
    ) -> tuple[str, ParticipantRole, str]:
        """
        Resolves (speaker_id, speaker_role, speaker_name) for a given session.
        Prioritizes authoritative session registration over client-supplied hints.
        """
        # 1. Authoritative registered session participant lookup
        if participant_id in session.participants:
            p = session.participants[participant_id]
            return p.participant_id, p.role, p.name

        # 2. Match against authoritative interviewer / candidate IDs
        if participant_id == session.interviewer_id:
            return participant_id, ParticipantRole.INTERVIEWER, session.interviewer_name
        if participant_id == session.candidate_id:
            return participant_id, ParticipantRole.CANDIDATE, session.candidate_name

        # 3. Check if hinted role was passed from an authenticated track
        if hinted_role and hinted_role != ParticipantRole.UNKNOWN:
            name = speaker_name or (session.interviewer_name if hinted_role == ParticipantRole.INTERVIEWER else session.candidate_name)
            return participant_id, hinted_role, name

        # 4. Fallback: Diarization speaker mapping (e.g. "SPEAKER_00", "SPEAKER_01")
        if session.session_id not in self._diarization_map:
            self._diarization_map[session.session_id] = {}

        session_map = self._diarization_map[session.session_id]
        if participant_id in session_map:
            assigned_role = session_map[participant_id]
            role = ParticipantRole(assigned_role)
            name = session.interviewer_name if role == ParticipantRole.INTERVIEWER else session.candidate_name
            return participant_id, role, name

        # Assign first speaker to interviewer if not set, second to candidate
        if len(session_map) == 0:
            session_map[participant_id] = ParticipantRole.INTERVIEWER.value
            logger.info(f"Speaker fallback: Assigned '{participant_id}' as Interviewer (turn-taking heuristic)")
            return participant_id, ParticipantRole.INTERVIEWER, session.interviewer_name
        elif len(session_map) == 1:
            session_map[participant_id] = ParticipantRole.CANDIDATE.value
            logger.info(f"Speaker fallback: Assigned '{participant_id}' as Candidate (turn-taking heuristic)")
            return participant_id, ParticipantRole.CANDIDATE, session.candidate_name

        # Default fallback
        return participant_id, ParticipantRole.UNKNOWN, speaker_name or "Unknown Participant"


speaker_service = SpeakerService()
