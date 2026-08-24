"""Contract validation tests."""

import pytest
from pydantic import ValidationError

from app.schemas import UserProfileUpdate, UserRegister, UserRole


def test_registration_normalizes_values_and_defaults_to_student() -> None:
    request = UserRegister(
        email="Student@Example.COM",
        password="securepass123",
        full_name="  Test Student  ",
    )

    assert request.email == "student@example.com"
    assert request.full_name == "Test Student"
    assert request.role is UserRole.STUDENT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "not-an-email"),
        ("password", "short"),
        ("full_name", "   "),
        ("full_name", "<script>alert('xss')</script>"),
        ("role", "owner"),
    ],
)
def test_registration_rejects_invalid_contract_values(field: str, value: str) -> None:
    data = {
        "email": "student@example.com",
        "password": "securepass123",
        "full_name": "Test Student",
        "role": "student",
    }
    data[field] = value

    with pytest.raises(ValidationError):
        UserRegister.model_validate(data)


def test_registration_accepts_all_documented_roles() -> None:
    for role in UserRole:
        request = UserRegister(
            email=f"{role.value}@example.com",
            password="securepass123",
            full_name="Test User",
            role=role,
        )
        assert request.role is role


def test_profile_update_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdate()


def test_profile_update_accepts_consent_changes() -> None:
    update = UserProfileUpdate(camera_consent=False, geolocation_consent=True)

    assert update.camera_consent is False
    assert update.geolocation_consent is True

