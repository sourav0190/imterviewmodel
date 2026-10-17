import re
import logging
from typing import List
from datetime import datetime
from interview_agent.models.interview_session import InterviewSessionModel
from interview_agent.models.answer_evaluation import ActiveQuestionState
from interview_agent.schemas.evaluation import InterviewNote

logger = logging.getLogger(__name__)

# Common architectural and engineering concepts dictionary for grounded concept extraction
TECH_KEYWORDS = [
    "redis", "postgresql", "mysql", "cassandra", "kafka", "rabbitmq", "grpc", "rest", "graphql",
    "docker", "kubernetes", "token bucket", "leaky bucket", "acid", "cap theorem", "quarum", "quorum",
    "mvcc", "write-ahead log", "wal", "replication", "sharding", "partitioning", "circuit breaker",
    "load balancer", "cache", "lru", "cdn", "eventual consistency", "two-phase commit", "2pc",
    "raft", "paxos", "jwt", "oauth", "tls", "encryption", "hashing", "btree", "lsm tree"
]

class NotesService:
    """
    Progressively synthesizes structured, factual interview notes.
    Strictly grounded in candidate statements without hallucinating achievements.
    """

    def generate_note(
        self,
        session: InterviewSessionModel,
        qa_state: ActiveQuestionState
    ) -> InterviewNote:
        """
        Synthesizes an InterviewNote for a completed question-answer block.
        """
        answer = qa_state.accumulated_answer
        question = qa_state.question_text

        # Extract technical concepts grounded in the candidate's speech
        concepts = self._extract_concepts(answer)

        # Extract examples or case studies mentioned
        examples = self._extract_examples(answer)

        # Generate a concise summary
        summary = self._summarize_answer(answer)

        # Identify potential omissions based on question rubric
        omissions = self._identify_omissions(session, qa_state, concepts)

        note = InterviewNote(
            session_id=session.session_id,
            question_id=qa_state.question_id,
            question_text=question,
            answer_summary=summary,
            key_concepts=concepts,
            examples_provided=examples,
            omissions=omissions,
            follow_up_points=[
                f"Clarify operational failure modes for {concepts[0]}" if concepts else "Ask for concrete system scaling metrics"
            ],
            start_time=qa_state.answer_start_time or qa_state.asked_at,
            end_time=qa_state.last_answer_update or (qa_state.asked_at + 10.0),
            created_at=datetime.utcnow()
        )

        session.notes.append(note)
        session.touch()
        return note

    def _extract_concepts(self, text: str) -> List[str]:
        lower = text.lower()
        found = []
        for kw in TECH_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", lower):
                found.append(kw.title() if len(kw) > 4 else kw.upper())
        return list(dict.fromkeys(found))[:6]

    def _extract_examples(self, text: str) -> List[str]:
        examples = []
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_lower = s.lower()
            if any(cue in s_lower for cue in ["for example", "in my experience", "we used", "i implemented", "such as", "using"]):
                examples.append(s.strip())
        return examples[:3]

    def _summarize_answer(self, text: str) -> str:
        words = text.split()
        if len(words) <= 30:
            return text.strip()
        # Create concise summary
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return " ".join(sentences[:2]).strip()

    def _identify_omissions(
        self,
        session: InterviewSessionModel,
        qa_state: ActiveQuestionState,
        identified_concepts: List[str]
    ) -> List[str]:
        omissions = []
        # Check against question rubric if configured
        for q_rubric in session.rubric_config.questions:
            if q_rubric.question_text.lower() in qa_state.question_text.lower() or qa_state.question_id == q_rubric.question_id:
                for expected in q_rubric.expected_concepts:
                    if expected.lower() not in [c.lower() for c in identified_concepts] and expected.lower() not in qa_state.accumulated_answer.lower():
                        omissions.append(expected)
        return omissions[:4]

notes_service = NotesService()
