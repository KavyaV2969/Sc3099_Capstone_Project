"""Standard Haversine distances and invalid coordinate inputs."""
import pytest

from app.utils.geolocation import haversine_distance


def test_identical_coordinates():
    assert haversine_distance(1.3483, 103.6831, 1.3483, 103.6831) == pytest.approx(0)


def test_nearby_coordinates():
    assert haversine_distance(1.3483, 103.6831, 1.3493, 103.6831) == pytest.approx(111.195, abs=0.01)


def test_antipodal_and_dateline_coordinates():
    assert haversine_distance(0, 0, 0, 180) == pytest.approx(20_015_087, abs=1)
    assert haversine_distance(0, 179.999, 0, -179.999) == pytest.approx(222.39, abs=0.1)


@pytest.mark.parametrize("coordinates", [(91, 0, 0, 0), (0, 181, 0, 0), (0, 0, -91, 0),
                                         (0, 0, 0, -181), (float('nan'), 0, 0, 0),
                                         (0, float('inf'), 0, 0)])
def test_invalid_coordinates(coordinates):
    with pytest.raises(ValueError):
        haversine_distance(*coordinates)
