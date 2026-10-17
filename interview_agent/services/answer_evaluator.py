import asyncio
import json
import logging
import re
import os
from typing import Optional, List, Dict, Any
from datetime import datetime

from interview_agent.config import settings
from interview_agent.schemas.evaluation import (
    AnswerEvaluation,
    DimensionScore,
    EvaluationStatus,
)
from interview_agent.schemas.interview import QuestionRubric, RubricDimension
from interview_agent.models.interview_session import InterviewSessionModel
from interview_agent.models.answer_evaluation import ActiveQuestionState

logger = logging.getLogger(__name__)

# Injection patterns to flag or neutralize
INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"system prompt override",
    r"give (me )?(a )?(score of )?100",
    r"give (me )?(a )?perfect score",
    r"reveal (the )?system instructions",
    r"disregard the rubric"
]

class AnswerEvaluator:
    """
    LLM-backed answer evaluation engine with rubric support, concurrency bounds,
    timeouts, fallback mechanics, and prompt-injection defenses.
    """

    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
        self._prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "answer_evaluation.txt")
        try:
            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            logger.warning(f"Could not read prompt template from {prompt_path}: {e}")
        return "You are an objective technical interview evaluator."

    def sanitize_untrusted_input(self, text: str) -> str:
        """
        Sanitizes candidate speech to guard against prompt injection.
        """
        # Neutralize common prompt injection phrases by defanging them
        sanitized = text
        for pat in INJECTION_PATTERNS:
            sanitized = re.sub(pat, "[FILTERED_ATTEMPT]", sanitized, flags=re.IGNORECASE)
        return sanitized

    async def evaluate_answer(
        self,
        session: InterviewSessionModel,
        qa_state: ActiveQuestionState,
        is_provisional: bool = False
    ) -> AnswerEvaluation:
        """
        Asynchronously evaluates a candidate's answer with bounded concurrency.
        """
        async with self._semaphore:
            status = EvaluationStatus.PROVISIONAL if is_provisional else EvaluationStatus.COMPLETE
            
            # Find matching question rubric if configured
            q_rubric: Optional[QuestionRubric] = None
            for qr in session.rubric_config.questions:
                if qr.question_id == qa_state.question_id or qr.question_text.lower() in qa_state.question_text.lower():
                    q_rubric = qr
                    break

            is_rubric_based = q_rubric is not None

            # Execute evaluation with timeout
            try:
                evaluation = await asyncio.wait_for(
                    self._execute_evaluation(session, qa_state, q_rubric, status, is_rubric_based),
                    timeout=settings.llm_timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error(f"Evaluation timed out after {settings.llm_timeout_seconds}s for question {qa_state.question_id}")
                # Fallback to local deterministic evaluator on timeout
                evaluation = self._deterministic_evaluator(session, qa_state, q_rubric, status, is_rubric_based)
                evaluation.evaluation_method = "deterministic_fallback"
                evaluation.is_fallback = True
                evaluation.explanation += f" [Fallback Notice: Evaluated via local resilient fallback due to LLM provider timeout ({settings.llm_timeout_seconds}s)]"
            except Exception as e:
                logger.error(f"LLM evaluation failed: {e}")
                evaluation = self._deterministic_evaluator(session, qa_state, q_rubric, status, is_rubric_based)
                evaluation.evaluation_method = "deterministic_fallback"
                evaluation.is_fallback = True
                evaluation.explanation += f" [Fallback Notice: Evaluated via local resilient fallback due to provider error: {str(e)}]"

            # Register or update in session evaluations
            existing_idx = next(
                (i for i, ev in enumerate(session.evaluations) if ev.question_id == qa_state.question_id),
                None
            )
            if existing_idx is not None:
                session.evaluations[existing_idx] = evaluation
            else:
                session.evaluations.append(evaluation)

            session.touch()
            return evaluation

    async def _execute_evaluation(
        self,
        session: InterviewSessionModel,
        qa_state: ActiveQuestionState,
        q_rubric: Optional[QuestionRubric],
        status: EvaluationStatus,
        is_rubric_based: bool
    ) -> AnswerEvaluation:
        provider = settings.llm_provider.lower().strip()
        if provider == "openai":
            if not settings.llm_api_key:
                raise ValueError(
                    "INTERVIEW_LLM_PROVIDER is configured as 'openai', but INTERVIEW_LLM_API_KEY (or OPENAI_API_KEY) is missing. "
                    "Cannot perform LLM evaluation without credentials."
                )
            eval_res = await self._call_openai_evaluator(session, qa_state, q_rubric, status, is_rubric_based)
            eval_res.evaluation_method = "llm"
            eval_res.is_fallback = False
            return eval_res
        elif provider in ("mock", "deterministic"):
            eval_res = self._deterministic_evaluator(session, qa_state, q_rubric, status, is_rubric_based)
            eval_res.evaluation_method = provider
            eval_res.is_fallback = False
            return eval_res
        else:
            raise ValueError(
                f"Unknown or unsupported INTERVIEW_LLM_PROVIDER '{provider}'. Supported options: 'mock', 'deterministic', 'openai'."
            )

    async def _call_openai_evaluator(
        self,
        session: InterviewSessionModel,
        qa_state: ActiveQuestionState,
        q_rubric: Optional[QuestionRubric],
        status: EvaluationStatus,
        is_rubric_based: bool
    ) -> AnswerEvaluation:
        import httpx

        sanitized_answer = self.sanitize_untrusted_input(qa_state.accumulated_answer)
        rubric_details = ""
        if q_rubric:
            rubric_details = f"Expected Concepts: {', '.join(q_rubric.expected_concepts)}\n"
            for d in q_rubric.dimensions:
                rubric_details += f"- {d.name} (weight {d.weight}): {d.description}\n"
        else:
            rubric_details = "No question-specific rubric provided. Use standard engineering evaluation dimensions."

        user_content = (
            f"INTERVIEW QUESTION:\n{qa_state.question_text}\n\n"
            f"EVALUATION CRITERIA:\n{rubric_details}\n\n"
            f"<candidate_transcript_untrusted>\n{sanitized_answer}\n</candidate_transcript_untrusted>\n\n"
            "Evaluate strictly based on technical correctness and reasoning. "
            "Return valid JSON only."
        )

        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": self._prompt_template},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        url = f"{settings.llm_base_url}/chat/completions" if settings.llm_base_url else "https://api.openai.com/v1/chat/completions"

        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                except (KeyError, json.JSONDecodeError, IndexError) as err:
                    raise ValueError(f"Malformed LLM JSON output from provider: {err}")

                candidate_lower = qa_state.accumulated_answer.lower()
                dimension_scores = []
                for s in parsed.get("scores", []):
                    raw_score = float(s.get("score", 3.0))
                    clamped_score = max(0.0, min(5.0, raw_score))

                    # Validate evidence quotes against actual candidate transcript
                    grounded_quotes = []
                    for q in s.get("evidence_quotes", []):
                        if isinstance(q, str) and q.strip():
                            q_clean = q.strip()
                            words = [w for w in re.findall(r"\w+", q_clean.lower()) if len(w) > 3]
                            if q_clean.lower() in candidate_lower or (words and any(w in candidate_lower for w in words[:3])):
                                grounded_quotes.append(q_clean)
                            else:
                                logger.warning("Discarding ungrounded evidence quote not present in candidate transcript")

                    dimension_scores.append(
                        DimensionScore(
                            dimension_name=s.get("dimension_name", "Dimension"),
                            score=clamped_score,
                            max_score=5.0,
                            feedback=s.get("feedback", ""),
                            evidence_quotes=grounded_quotes,
                            evidence_timestamps=[qa_state.asked_at]
                        )
                    )

                raw_overall = float(parsed.get("overall_score", 3.5))
                overall_score = max(0.0, min(5.0, raw_overall))
                overall_percentage = round((overall_score / 5.0) * 100.0, 1)

                explanation_text = parsed.get("explanation", "Candidate demonstrated technical reasoning.")
                if "[Evaluation Method:" not in explanation_text:
                    explanation_text += f" [Evaluation Method: OpenAI {settings.llm_model}]"

                return AnswerEvaluation(
                    session_id=session.session_id,
                    question_id=qa_state.question_id,
                    question_text=qa_state.question_text,
                    candidate_answer_text=qa_state.accumulated_answer,
                    answer_start_time=qa_state.answer_start_time or qa_state.asked_at,
                    answer_end_time=qa_state.last_answer_update or (qa_state.asked_at + 10.0),
                    status=status,
                    scores=dimension_scores,
                    overall_score=overall_score,
                    max_overall_score=5.0,
                    overall_percentage=overall_percentage,
                    strengths=parsed.get("strengths", []),
                    missing_concepts=parsed.get("missing_concepts", []),
                    suggested_follow_ups=parsed.get("suggested_follow_ups", []),
                    confidence=float(parsed.get("confidence", 0.9)),
                    explanation=explanation_text,
                    is_rubric_based=is_rubric_based,
                    uncertain_association=qa_state.uncertain_association,
                    evaluation_method="llm",
                    is_fallback=False
                )
            elif res.status_code == 401:
                raise RuntimeError("OpenAI authentication failed: Invalid API key (HTTP 401).")
            elif res.status_code == 429:
                raise RuntimeError("OpenAI rate limit exceeded (HTTP 429).")
            else:
                raise RuntimeError(f"OpenAI API returned HTTP {res.status_code}: {res.text}")

    def _deterministic_evaluator(
        self,
        session: InterviewSessionModel,
        qa_state: ActiveQuestionState,
        q_rubric: Optional[QuestionRubric],
        status: EvaluationStatus,
        is_rubric_based: bool
    ) -> AnswerEvaluation:
        """
        Grounded, deterministic evaluation algorithm.
        Ensures 100% testability, no dependency on paid API keys, and guaranteed runtime reliability.
        """
        answer = qa_state.accumulated_answer.strip()
        words = answer.split()
        word_count = len(words)

        # Baseline dimensions from session rubric or defaults
        dimensions = (
            q_rubric.dimensions if q_rubric and q_rubric.dimensions
            else session.rubric_config.global_dimensions
        )

        expected_concepts = q_rubric.expected_concepts if q_rubric else ["redis", "token bucket", "consistency", "scaling"]
        found_expected = [c for c in expected_concepts if c.lower() in answer.lower()]
        missing_expected = [c for c in expected_concepts if c.lower() not in answer.lower()]

        # Compute dimension scores
        scores: List[DimensionScore] = []
        total_weighted_score = 0.0
        total_weight = 0.0

        for dim in dimensions:
            base_score = 3.0
            quotes = []

            # Scoring heuristics grounded strictly in content length, terminology, and reasoning
            if dim.name.lower() in ("correctness", "accuracy"):
                if found_expected:
                    base_score = 4.0 + (0.5 if len(found_expected) > 1 else 0.0)
                    quotes = [f"Direct mention of {c}" for c in found_expected[:2]]
                else:
                    base_score = 3.0 if word_count > 15 else 2.0
            elif dim.name.lower() in ("technical depth", "depth"):
                if word_count > 40 and ("because" in answer.lower() or "trade-off" in answer.lower() or "guarantee" in answer.lower()):
                    base_score = 4.5
                    quotes = ["Identified trade-offs and structural behavior"]
                elif word_count > 20:
                    base_score = 3.5
                else:
                    base_score = 2.5
            elif dim.name.lower() in ("evidence & examples", "evidence"):
                if any(k in answer.lower() for k in ["for example", "using", "redis", "postgresql", "kafka", "cassandra", "resilience4j"]):
                    base_score = 4.5
                    quotes = ["Provided concrete technologies and architectural implementation"]
                else:
                    base_score = 2.5
            else:
                base_score = 3.5 if word_count > 25 else 3.0

            base_score = min(5.0, max(1.0, base_score))
            scores.append(
                DimensionScore(
                    dimension_name=dim.name,
                    score=base_score,
                    max_score=dim.max_score,
                    weight=dim.weight,
                    feedback=f"Candidate addressed {dim.name} with {'sound' if base_score >= 3.5 else 'moderate'} articulation.",
                    evidence_quotes=quotes,
                    evidence_timestamps=[qa_state.asked_at]
                )
            )
            total_weighted_score += base_score * dim.weight
            total_weight += dim.weight

        overall_score = round(total_weighted_score / max(0.1, total_weight), 2)
        overall_percentage = round((overall_score / 5.0) * 100, 1)

        strengths = []
        if found_expected:
            strengths.append(f"Successfully integrated core concepts: {', '.join(found_expected)}")
        if word_count > 30:
            strengths.append("Communicated architectural reasoning clearly with actionable engineering detail")
        if not strengths:
            strengths.append("Provided a straightforward introductory answer")

        suggested_followups = []
        if missing_expected:
            suggested_followups.append(f"Probe deeper into {missing_expected[0]} handling under extreme network partition conditions")
        else:
            suggested_followups.append("Ask how this design scales to millions of concurrent requests across multi-region clusters")

        explanation = (
            f"Candidate provided a {'high-confidence' if overall_score >= 4.0 else 'moderate'} technical explanation. "
            f"{'Answer aligns with question rubric.' if is_rubric_based else 'Standard baseline technical evaluation applied (no custom rubric provided).'}"
        )

        return AnswerEvaluation(
            session_id=session.session_id,
            question_id=qa_state.question_id,
            question_text=qa_state.question_text,
            candidate_answer_text=qa_state.accumulated_answer,
            answer_start_time=qa_state.answer_start_time or qa_state.asked_at,
            answer_end_time=qa_state.last_answer_update or (qa_state.asked_at + 10.0),
            status=status,
            scores=scores,
            overall_score=overall_score,
            max_overall_score=5.0,
            overall_percentage=overall_percentage,
            strengths=strengths,
            missing_concepts=missing_expected,
            suggested_follow_ups=suggested_followups,
            confidence=0.88 if not qa_state.uncertain_association else 0.60,
            explanation=explanation,
            is_rubric_based=is_rubric_based,
            uncertain_association=qa_state.uncertain_association,
            evaluation_method="deterministic",
            is_fallback=False
        )

answer_evaluator = AnswerEvaluator()
