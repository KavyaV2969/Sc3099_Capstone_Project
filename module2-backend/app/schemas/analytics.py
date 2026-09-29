"""Statistics and export response schemas."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, UUID4


class CountByDay(BaseModel):
    date: date
    count: int


class RateByDay(BaseModel):
    date: date
    rate: float | None


class OverviewTrends(BaseModel):
    checkins_by_day: list[CountByDay]
    attendance_rate_by_day: list[RateByDay]


class OverviewStatistics(BaseModel):
    coverage: dict[str, Any] = Field(default_factory=dict)
    total_sessions: int
    active_sessions: int
    total_checkins_today: int
    total_checkins_week: int
    average_attendance_rate: float | None
    flagged_pending_review: int
    approval_rate: float
    average_risk_score: float
    high_risk_checkins_today: int
    trends: OverviewTrends


class CheckinTimelineBucket(BaseModel):
    minute: int
    count: int


class SessionStatistics(BaseModel):
    coverage: dict[str, Any] = Field(default_factory=dict)
    session_id: UUID4
    session_name: str
    course_code: str
    scheduled_start: datetime
    status: str
    total_enrolled: int | None
    approved_attendance: int | None = None
    checked_in: int
    attendance_rate: float | None
    by_status: dict[str, int]
    average_risk_score: float
    average_distance_meters: float
    average_checkin_time_minutes: float
    risk_distribution: dict[str, int]
    checkin_timeline: list[CheckinTimelineBucket]


class CourseSessionStatistics(BaseModel):
    session_id: UUID4
    name: str
    date: date
    attendance_rate: float | None
    checked_in: int


class StudentAttendanceStatistics(BaseModel):
    total_sessions: int = 0
    student_id: UUID4
    student_name: str
    sessions_attended: int
    attendance_rate: float | None
    average_risk_score: float


class LowAttendanceAlert(BaseModel):
    student_id: UUID4
    student_name: str
    attendance_rate: float | None
    sessions_missed: int


class CourseStatistics(BaseModel):
    coverage: dict[str, Any] = Field(default_factory=dict)
    course_id: UUID4
    course_code: str
    course_name: str
    total_sessions: int
    total_enrolled: int
    overall_attendance_rate: float | None
    sessions: list[CourseSessionStatistics]
    student_attendance: list[StudentAttendanceStatistics]
    low_attendance_alerts: list[LowAttendanceAlert]


class StudentCourseStatistics(BaseModel):
    course_id: UUID4
    course_code: str
    attendance_rate: float | None
    sessions_attended: int
    total_sessions: int
    average_risk_score: float


class RecentCheckinStatistics(BaseModel):
    session_name: str
    course_code: str
    checked_in_at: datetime
    status: str


class StudentStatistics(BaseModel):
    coverage: dict[str, Any] = Field(default_factory=dict)
    student_id: UUID4
    student_name: str
    student_email: str
    courses: list[StudentCourseStatistics]
    recent_checkins: list[RecentCheckinStatistics]


class ExportSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    summary: dict[str, Any]
    checkins: list[dict[str, Any]]
