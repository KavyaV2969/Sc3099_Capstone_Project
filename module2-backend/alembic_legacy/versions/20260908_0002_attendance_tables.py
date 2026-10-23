"""Add the Week 3 course, enrollment, session and check-in tables."""
from alembic import op
import sqlalchemy as sa

revision = "20260908_0002"
down_revision = "20260825_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('courses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('semester', sa.String(length=20), nullable=False),
        sa.Column('instructor_id', sa.String(length=36), nullable=False),
        sa.Column('venue_name', sa.String(length=255), nullable=True),
        sa.Column('venue_latitude', sa.Float(), nullable=True),
        sa.Column('venue_longitude', sa.Float(), nullable=True),
        sa.Column('geofence_radius_meters', sa.Float(), nullable=False),
        sa.Column('risk_threshold', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('geofence_radius_meters > 0', name='ck_courses_radius'),
        sa.CheckConstraint('risk_threshold BETWEEN 0 AND 1', name='ck_courses_risk'),
        sa.CheckConstraint('venue_latitude BETWEEN -90 AND 90', name='ck_courses_latitude'),
        sa.CheckConstraint('venue_longitude BETWEEN -180 AND 180', name='ck_courses_longitude'),
        sa.ForeignKeyConstraint(['instructor_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_courses_instructor_id'), 'courses', ['instructor_id'], unique=False)
    op.create_index(op.f('ix_courses_semester'), 'courses', ['semester'], unique=False)
    op.create_table('course_tas',
        sa.Column('course_id', sa.String(length=36), nullable=False),
        sa.Column('ta_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['ta_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('course_id', 'ta_id')
    )
    op.create_table('enrollments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('course_id', sa.String(length=36), nullable=False),
        sa.Column('enrolled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'course_id', name='uq_enrollments_student_course')
    )
    op.create_index(op.f('ix_enrollments_course_id'), 'enrollments', ['course_id'], unique=False)
    op.create_table('sessions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('course_id', sa.String(length=36), nullable=False),
        sa.Column('instructor_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('session_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('checkin_opens_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('checkin_closes_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('venue_name', sa.String(length=255), nullable=True),
        sa.Column('venue_latitude', sa.Float(), nullable=False),
        sa.Column('venue_longitude', sa.Float(), nullable=False),
        sa.Column('geofence_radius_meters', sa.Float(), nullable=False),
        sa.Column('require_liveness_check', sa.Boolean(), nullable=False),
        sa.Column('require_face_match', sa.Boolean(), nullable=False),
        sa.Column('risk_threshold', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("session_type IN ('lecture', 'tutorial', 'lab', 'exam')", name='ck_sessions_type'),
        sa.CheckConstraint("status IN ('scheduled', 'active', 'closed', 'cancelled')", name='ck_sessions_status'),
        sa.CheckConstraint('checkin_closes_at > checkin_opens_at', name='ck_sessions_window'),
        sa.CheckConstraint('geofence_radius_meters > 0', name='ck_sessions_radius'),
        sa.CheckConstraint('risk_threshold BETWEEN 0 AND 1', name='ck_sessions_risk'),
        sa.CheckConstraint('scheduled_end > scheduled_start', name='ck_sessions_schedule'),
        sa.CheckConstraint('venue_latitude BETWEEN -90 AND 90', name='ck_sessions_latitude'),
        sa.CheckConstraint('venue_longitude BETWEEN -180 AND 180', name='ck_sessions_longitude'),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['instructor_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_course_id'), 'sessions', ['course_id'], unique=False)
    op.create_index(op.f('ix_sessions_instructor_id'), 'sessions', ['instructor_id'], unique=False)
    op.create_index(op.f('ix_sessions_scheduled_start'), 'sessions', ['scheduled_start'], unique=False)
    op.create_index(op.f('ix_sessions_status'), 'sessions', ['status'], unique=False)
    op.create_table('checkins',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('student_id', sa.String(length=36), nullable=False),
        sa.Column('checked_in_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('location_accuracy_meters', sa.Float(), nullable=False),
        sa.Column('distance_from_venue_meters', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'flagged', 'rejected')", name='ck_checkins_status'),
        sa.CheckConstraint('distance_from_venue_meters >= 0', name='ck_checkins_distance'),
        sa.CheckConstraint('latitude BETWEEN -90 AND 90', name='ck_checkins_latitude'),
        sa.CheckConstraint('location_accuracy_meters >= 0', name='ck_checkins_accuracy'),
        sa.CheckConstraint('longitude BETWEEN -180 AND 180', name='ck_checkins_longitude'),
        sa.CheckConstraint('risk_score BETWEEN 0 AND 1', name='ck_checkins_risk'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'session_id', name='uq_checkins_student_session')
    )
    op.create_index(op.f('ix_checkins_session_id'), 'checkins', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_checkins_session_id'), table_name='checkins')
    op.drop_table('checkins')
    op.drop_index(op.f('ix_sessions_status'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_scheduled_start'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_instructor_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_course_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_enrollments_course_id'), table_name='enrollments')
    op.drop_table('enrollments')
    op.drop_table('course_tas')
    op.drop_index(op.f('ix_courses_semester'), table_name='courses')
    op.drop_index(op.f('ix_courses_instructor_id'), table_name='courses')
    op.drop_table('courses')
