"""Initial interview agent PostgreSQL persistence schema

Revision ID: 001_interview_persistence
Revises: 
Create Date: 2026-10-17 19:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001_interview_persistence'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. interview_sessions
    op.create_table(
        'interview_sessions',
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False, server_default='Technical Interview'),
        sa.Column('candidate_id', sa.String(length=128), nullable=False),
        sa.Column('candidate_name', sa.String(length=255), nullable=False),
        sa.Column('interviewer_id', sa.String(length=128), nullable=False),
        sa.Column('interviewer_name', sa.String(length=255), nullable=False, server_default='Interviewer'),
        sa.Column('organization_id', sa.String(length=128), nullable=True),
        sa.Column('owner_id', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='created'),
        sa.Column('consent_obtained', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rubric_config', sa.JSON(), nullable=True),
        sa.Column('session_metadata', sa.JSON(), nullable=True),
        sa.Column('participants', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('session_id')
    )
    op.create_index('idx_session_org_status', 'interview_sessions', ['organization_id', 'status'])
    op.create_index('idx_session_owner_created', 'interview_sessions', ['owner_id', 'created_at'])
    op.create_index('idx_session_candidate', 'interview_sessions', ['candidate_id'])
    op.create_index('idx_session_interviewer', 'interview_sessions', ['interviewer_id'])

    # 2. interview_transcript_segments
    op.create_table(
        'interview_transcript_segments',
        sa.Column('segment_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('speaker_id', sa.String(length=128), nullable=False),
        sa.Column('speaker_name', sa.String(length=255), nullable=False),
        sa.Column('speaker_role', sa.String(length=32), nullable=False),
        sa.Column('start_time', sa.Float(), nullable=False),
        sa.Column('end_time', sa.Float(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('is_final', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('language', sa.String(length=16), nullable=False, server_default='en'),
        sa.Column('sequence_number', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('segment_id'),
        sa.UniqueConstraint('session_id', 'speaker_id', 'sequence_number', name='uq_session_speaker_sequence')
    )
    op.create_index('idx_segment_session_time', 'interview_transcript_segments', ['session_id', 'start_time'])

    # 3. interview_notes
    op.create_table(
        'interview_notes',
        sa.Column('note_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('question_id', sa.String(length=64), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('answer_summary', sa.Text(), nullable=False),
        sa.Column('key_concepts', sa.JSON(), nullable=False),
        sa.Column('examples_provided', sa.JSON(), nullable=False),
        sa.Column('omissions', sa.JSON(), nullable=False),
        sa.Column('follow_up_points', sa.JSON(), nullable=False),
        sa.Column('start_time', sa.Float(), nullable=False),
        sa.Column('end_time', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('note_id')
    )
    op.create_index('idx_note_session_question', 'interview_notes', ['session_id', 'question_id'])

    # 4. interview_evaluations
    op.create_table(
        'interview_evaluations',
        sa.Column('evaluation_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('question_id', sa.String(length=64), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('candidate_answer_text', sa.Text(), nullable=False),
        sa.Column('answer_start_time', sa.Float(), nullable=False),
        sa.Column('answer_end_time', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('overall_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('max_overall_score', sa.Float(), nullable=False, server_default='5.0'),
        sa.Column('overall_percentage', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.85'),
        sa.Column('explanation', sa.Text(), nullable=False, server_default=''),
        sa.Column('is_rubric_based', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('uncertain_association', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('scores', sa.JSON(), nullable=False),
        sa.Column('strengths', sa.JSON(), nullable=False),
        sa.Column('missing_concepts', sa.JSON(), nullable=False),
        sa.Column('suggested_follow_ups', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('evaluation_id')
    )
    op.create_index('idx_eval_session_question', 'interview_evaluations', ['session_id', 'question_id'])

    # 5. interview_final_reports
    op.create_table(
        'interview_final_reports',
        sa.Column('report_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('candidate_name', sa.String(length=255), nullable=False),
        sa.Column('candidate_id', sa.String(length=128), nullable=False),
        sa.Column('interview_title', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('executive_summary', sa.Text(), nullable=False),
        sa.Column('aggregate_score', sa.Float(), nullable=False),
        sa.Column('max_possible_score', sa.Float(), nullable=False, server_default='5.0'),
        sa.Column('aggregate_percentage', sa.Float(), nullable=False),
        sa.Column('top_strengths', sa.JSON(), nullable=False),
        sa.Column('key_areas_for_improvement', sa.JSON(), nullable=False),
        sa.Column('dimension_scores', sa.JSON(), nullable=False),
        sa.Column('evaluations', sa.JSON(), nullable=False),
        sa.Column('proctoring_suspicion_score', sa.Float(), nullable=True),
        sa.Column('recommendation', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('report_id'),
        sa.UniqueConstraint('session_id')
    )


def downgrade() -> None:
    op.drop_table('interview_final_reports')
    op.drop_table('interview_evaluations')
    op.drop_table('interview_notes')
    op.drop_table('interview_transcript_segments')
    op.drop_table('interview_sessions')
