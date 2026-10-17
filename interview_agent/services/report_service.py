from datetime import datetime
from typing import List
from interview_agent.models.interview_session import InterviewSessionModel
from interview_agent.schemas.evaluation import FinalReport

class ReportService:
    """
    Generates the final structured interview summary report and question-wise breakdown.
    Ensures strict isolation between technical interview score and proctoring suspicion score.
    """

    def generate_final_report(self, session: InterviewSessionModel) -> FinalReport:
        evaluations = session.evaluations
        notes = session.notes

        if evaluations:
            total_score = sum(e.overall_score for e in evaluations)
            avg_score = round(total_score / len(evaluations), 2)
            avg_percentage = round((avg_score / 5.0) * 100, 1)
        else:
            avg_score = 0.0
            avg_percentage = 0.0

        # Aggregate strengths
        all_strengths: List[str] = []
        for e in evaluations:
            all_strengths.extend(e.strengths)
        top_strengths = list(dict.fromkeys(all_strengths))[:5]

        # Aggregate missing concepts / improvement areas
        all_missing: List[str] = []
        for e in evaluations:
            all_missing.extend(e.missing_concepts)
        key_improvements = list(dict.fromkeys(all_missing))[:5]

        # Generate concise executive summary with transparent evaluation methodology disclosure
        if evaluations:
            llm_count = sum(1 for e in evaluations if getattr(e, "evaluation_method", "") == "llm")
            fallback_count = sum(1 for e in evaluations if getattr(e, "is_fallback", False))
            
            method_label = ""
            if fallback_count > 0:
                method_label = f" [Methodology Notice: {fallback_count} evaluation(s) used local deterministic fallback due to LLM provider error/timeout.]"
            elif llm_count > 0:
                method_label = " [Methodology: Evaluated with LLM (OpenAI).]"
            else:
                method_label = " [Methodology: Evaluated with deterministic rule-based evaluation engine.]"

            summary = (
                f"Candidate {session.candidate_name} completed {len(evaluations)} technical question evaluation(s) "
                f"with an overall technical proficiency score of {avg_score}/5.0 ({avg_percentage}%). "
                f"Demonstrated strongest capabilities in {top_strengths[0] if top_strengths else 'system fundamentals'}. "
                f"Recommended focus areas include: {', '.join(key_improvements) if key_improvements else 'advanced distributed edge-cases'}."
                f"{method_label}"
            )
        else:
            summary = f"Interview session completed with no formal evaluated question turns."

        report = FinalReport(
            session_id=session.session_id,
            candidate_name=session.candidate_name,
            candidate_id=session.candidate_id,
            interview_title=session.title,
            status=session.status.value,
            started_at=session.created_at,
            completed_at=datetime.utcnow(),
            executive_summary=summary,
            aggregate_score=avg_score,
            max_possible_score=5.0,
            aggregate_percentage=avg_percentage,
            top_strengths=top_strengths,
            key_areas_for_improvement=key_improvements,
            question_evaluations=evaluations,
            notes=notes
        )

        session.final_report = report
        session.touch()
        return report

report_service = ReportService()
