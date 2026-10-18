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

        # Meeting Date
        meeting_date_str = session.created_at.strftime("%Y-%m-%d %H:%M UTC")

        # Reliably established participants only (no fabricated identities)
        active_speakers = {s.speaker_id for s in session.transcript_segments}
        verified_participants = []
        for p_id, p in session.participants.items():
            if not active_speakers or p_id in active_speakers:
                role_val = p.role.value if hasattr(p.role, "value") else str(p.role)
                verified_participants.append(f"{p.name} ({role_val.title()})")
        for seg in session.transcript_segments:
            if seg.speaker_name and seg.speaker_id not in session.participants and seg.speaker_role != ParticipantRole.UNKNOWN:
                role_val = seg.speaker_role.value if hasattr(seg.speaker_role, "value") else str(seg.speaker_role)
                verified_participants.append(f"{seg.speaker_name} ({role_val.title()})")
        established_participants = list(dict.fromkeys(verified_participants))

        # Technical concepts discussed (grounded in candidate answers and notes)
        all_concepts = []
        for n in notes:
            all_concepts.extend(n.key_concepts)
        technical_concepts = list(dict.fromkeys(all_concepts))

        # Decisions and follow-up actions (grounded in actual notes and evaluations)
        all_actions = []
        for n in notes:
            all_actions.extend(n.follow_up_points)
        for e in evaluations:
            all_actions.extend(e.suggested_follow_ups)
        decisions_actions = list(dict.fromkeys(all_actions))[:6]

        # Unanswered or unclear questions
        unanswered = []
        if session.current_question_text and not session.current_answer_buffer:
            unanswered.append(session.current_question_text)
        for n in notes:
            if n.omissions:
                for om in n.omissions:
                    unanswered.append(f"{n.question_text}: {om}")
        unanswered_list = list(dict.fromkeys(unanswered))[:5]

        # Transcript provenance breakdown
        provenance = {
            "bridge": 0,
            "local_microphone": 0,
            "simulation": 0
        }
        for seg in session.transcript_segments:
            src = getattr(seg, "source", None)
            if not src:
                src = "simulation" if getattr(seg, "is_simulated", False) else "bridge"
            if src not in provenance:
                provenance[src] = 0
            provenance[src] += 1

        report = FinalReport(
            session_id=session.session_id,
            candidate_name=session.candidate_name,
            candidate_id=session.candidate_id,
            interview_title=session.title,
            status=session.status.value,
            started_at=session.created_at,
            completed_at=datetime.utcnow(),
            meeting_date=meeting_date_str,
            participants=established_participants,
            executive_summary=summary,
            aggregate_score=avg_score,
            max_possible_score=5.0,
            aggregate_percentage=avg_percentage,
            top_strengths=top_strengths,
            key_areas_for_improvement=key_improvements,
            technical_concepts_discussed=technical_concepts,
            decisions_and_actions=decisions_actions,
            unanswered_questions=unanswered_list,
            question_evaluations=evaluations,
            notes=notes,
            transcript_provenance=provenance
        )

        session.final_report = report
        session.touch()
        return report

report_service = ReportService()
