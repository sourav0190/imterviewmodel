import re
import uuid
from typing import Optional, Tuple, List
from interview_agent.schemas.interview import ParticipantRole
from interview_agent.schemas.transcript import TranscriptSegment
from interview_agent.models.interview_session import InterviewSessionModel
from interview_agent.models.answer_evaluation import ActiveQuestionState

# Conversational backchannels that do not indicate turn handoffs or answer completions
BACKCHANNEL_WORDS = {
    "mm-hmm", "mmhmm", "uh-huh", "uhhuh", "mhm", "yeah", "yes", "okay",
    "right", "got it", "i see", "sure", "cool", "alright"
}

# Interrogative keywords for technical interviews
QUESTION_TRIGGERS = [
    r"\bhow\b", r"\bwhat\b", r"\bwhy\b", r"\bwhere\b", r"\bwhen\b", r"\bwhich\b",
    r"\bexplain\b", r"\bdescribe\b", r"\btell me\b", r"\bwalk me through\b",
    r"\bcan you\b", r"\bcould you\b", r"\bwould you\b", r"\bdesign\b"
]

FOLLOW_UP_TRIGGERS = [
    r"\bwhat if\b", r"\bwhat about\b", r"\bhow about\b", r"\band if\b",
    r"\belaborate\b", r"\bexpand on\b", r"\bwhat happens when\b", r"\bwhat would happen\b"
]

class QuestionDetector:
    """
    Stateful conversational processor that detects interviewer questions,
    associates candidate responses, manages follow-ups and interruptions,
    and signals when an answer is complete and ready for evaluation.
    """

    def is_question_turn(self, text: str) -> Tuple[bool, bool]:
        """
        Determines whether text is a question and whether it's a follow-up.
        Returns: (is_question, is_follow_up)
        """
        cleaned = text.strip().lower()
        if not cleaned:
            return False, False

        # Ends with question mark
        has_qmark = cleaned.endswith("?")

        # Matches question keywords
        has_qtrigger = any(re.search(pat, cleaned) for pat in QUESTION_TRIGGERS)
        is_followup = any(re.search(pat, cleaned) for pat in FOLLOW_UP_TRIGGERS)

        is_q = has_qmark or has_qtrigger
        return is_q, is_followup

    def is_backchannel(self, text: str) -> bool:
        """Determines if a short utterance is simply an encouraging backchannel or listening cue."""
        cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
        return cleaned in BACKCHANNEL_WORDS or len(cleaned.split()) <= 2 and cleaned in BACKCHANNEL_WORDS

    def process_segment(
        self,
        session: InterviewSessionModel,
        segment: TranscriptSegment
    ) -> Tuple[Optional[ActiveQuestionState], Optional[ActiveQuestionState]]:
        """
        Processes a single incoming transcript segment.
        Returns:
            (in_progress_question, completed_question_to_evaluate)
        """
        completed_question: Optional[ActiveQuestionState] = None
        in_progress_question: Optional[ActiveQuestionState] = None

        # 1. Handle INTERVIEWER Speech
        if segment.speaker_role == ParticipantRole.INTERVIEWER:
            # If it's just a passive backchannel ("okay", "uh-huh"), don't interrupt candidate's answer
            if self.is_backchannel(segment.text):
                return None, None

            is_q, is_followup = self.is_question_turn(segment.text)

            # If the interviewer asks a question, close any existing candidate answer in progress
            if session.current_question_id and len(session.current_answer_buffer) > 0:
                answer_text = " ".join(s.text for s in session.current_answer_buffer).strip()
                if len(answer_text) > 10:  # Minimum substantive answer threshold
                    completed_question = ActiveQuestionState(
                        question_id=session.current_question_id,
                        question_text=session.current_question_text or "Question",
                        asked_at=session.current_answer_buffer[0].start_time,
                        accumulated_answer=answer_text,
                        answer_start_time=session.current_answer_buffer[0].start_time,
                        last_answer_update=session.current_answer_buffer[-1].end_time,
                        is_completed=True,
                        uncertain_association=False
                    )

            # Start tracking the new question
            if is_q or not session.current_question_id:
                new_qid = f"q_{uuid.uuid4().hex[:8]}"
                session.current_question_id = new_qid
                session.current_question_text = segment.text
                session.current_answer_buffer = []

                in_progress_question = ActiveQuestionState(
                    question_id=new_qid,
                    question_text=segment.text,
                    asked_at=segment.start_time,
                    is_follow_up=is_followup,
                    parent_question_id=completed_question.question_id if (is_followup and completed_question) else None,
                    accumulated_answer="",
                    answer_start_time=None,
                    is_completed=False,
                    uncertain_association=False
                )

        # 2. Handle CANDIDATE Speech
        elif segment.speaker_role == ParticipantRole.CANDIDATE:
            session.current_answer_buffer.append(segment)
            answer_text = " ".join(s.text for s in session.current_answer_buffer).strip()

            uncertain = False
            if not session.current_question_id:
                # Candidate spoke without an interviewer question detected
                session.current_question_id = f"q_unprompted_{uuid.uuid4().hex[:6]}"
                session.current_question_text = "[Initial Opening or Unprompted Statement]"
                uncertain = True

            in_progress_question = ActiveQuestionState(
                question_id=session.current_question_id,
                question_text=session.current_question_text or "General Technical Discussion",
                asked_at=session.current_answer_buffer[0].start_time,
                accumulated_answer=answer_text,
                answer_start_time=session.current_answer_buffer[0].start_time,
                last_answer_update=segment.end_time,
                is_completed=False,
                uncertain_association=uncertain
            )

        # 3. Handle UNKNOWN or Observer Speech
        else:
            if session.current_question_id:
                in_progress_question = ActiveQuestionState(
                    question_id=session.current_question_id,
                    question_text=session.current_question_text or "",
                    asked_at=segment.start_time,
                    accumulated_answer=" ".join(s.text for s in session.current_answer_buffer),
                    uncertain_association=True
                )

        return in_progress_question, completed_question

    def finalize_active_answer(self, session: InterviewSessionModel) -> Optional[ActiveQuestionState]:
        """Finalizes any pending candidate answer when the interview ends or is paused."""
        if session.current_question_id and len(session.current_answer_buffer) > 0:
            answer_text = " ".join(s.text for s in session.current_answer_buffer).strip()
            if answer_text:
                completed = ActiveQuestionState(
                    question_id=session.current_question_id,
                    question_text=session.current_question_text or "Interview Question",
                    asked_at=session.current_answer_buffer[0].start_time,
                    accumulated_answer=answer_text,
                    answer_start_time=session.current_answer_buffer[0].start_time,
                    last_answer_update=session.current_answer_buffer[-1].end_time,
                    is_completed=True,
                    uncertain_association=False
                )
                session.current_answer_buffer = []
                return completed
        return None

question_detector = QuestionDetector()
