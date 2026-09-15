"""Course and enrollment schemas."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, UUID4, field_validator, model_validator

from .common import CourseCode, Latitude, Longitude, Radius, RiskScore, ShortName


class CourseCreate(BaseModel):
    code: CourseCode
    name: ShortName
    semester: CourseCode
    instructor_id: UUID4 | None = None
    venue_name: ShortName | None = None
    venue_latitude: Latitude | None = None
    venue_longitude: Longitude | None = None
    geofence_radius_meters: Radius = 100.0
    risk_threshold: RiskScore = 0.5


class CourseUpdate(BaseModel):
    code: CourseCode | None = None
    name: ShortName | None = None
    semester: CourseCode | None = None
    instructor_id: UUID4 | None = None
    venue_name: ShortName | None = None
    venue_latitude: Latitude | None = None
    venue_longitude: Longitude | None = None
    geofence_radius_meters: Radius | None = None
    risk_threshold: RiskScore | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def reject_required_nulls(self) -> "CourseUpdate":
        nullable = {"instructor_id", "venue_name", "venue_latitude", "venue_longitude"}
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class CourseResponse(CourseCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    instructor_name: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CourseListResponse(BaseModel):
    items: list[CourseResponse]
    total: int
    limit: int
    offset: int


class EnrollmentCreate(BaseModel):
    student_id: UUID4
    course_id: UUID4


class EnrollmentResponse(EnrollmentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    enrolled_at: datetime
    is_active: bool


class MyEnrollmentResponse(EnrollmentResponse):
    course_code: str
    course_name: str
    semester: str


class EnrolledStudentResponse(BaseModel):
    id: UUID4
    student_id: UUID4
    student_email: EmailStr
    student_name: str
    enrolled_at: datetime
    is_active: bool
    face_enrolled: bool


class CourseEnrollmentsResponse(BaseModel):
    course_id: UUID4
    course_code: str
    total_enrolled: int
    students: list[EnrolledStudentResponse]


class BulkEnrollmentCreate(BaseModel):
    course_id: UUID4
    student_emails: list[EmailStr] = Field(min_length=1, max_length=1000)
    create_accounts: bool = False

    @field_validator("student_emails")
    @classmethod
    def normalize_emails(cls, values: list[EmailStr]) -> list[str]:
        return [str(value).lower() for value in values]


class BulkEnrollmentDetail(BaseModel):
    email: EmailStr
    status: str


class BulkEnrollmentResponse(BaseModel):
    enrolled: int
    already_enrolled: int
    not_found: int
    created: int = 0
    details: list[BulkEnrollmentDetail]
