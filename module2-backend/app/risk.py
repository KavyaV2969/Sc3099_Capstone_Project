"""Documented weighted risk policy for attendance verification."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskDecision:
    score: float
    status: str
    factors: list[dict]


def assess_risk(
    *, distance: float, radius: float, location_accuracy: float,
    liveness_score: float | None, liveness_passed: bool | None,
    face_score: float | None, face_passed: bool | None,
    known_device: bool, trusted_device: bool, local_network: bool,
    threshold: float,
) -> RiskDecision:
    geo_risk = min(1.0, distance / max(radius, 1.0))
    if location_accuracy > radius:
        geo_risk = min(1.0, geo_risk + 0.25)
    signals = {
        "liveness": 1.0 - liveness_score if liveness_score is not None else (1.0 if liveness_passed is False else 0.0),
        "face_match": 1.0 - face_score if face_score is not None else (1.0 if face_passed is False else 0.0),
        "device": 0.0 if trusted_device else (0.5 if known_device else 1.0),
        "network": 0.0 if local_network else 0.2,
        "geolocation": geo_risk,
    }
    weights = {"liveness": .25, "face_match": .25, "device": .20, "network": .15, "geolocation": .15}
    factors = [
        {"type": name, "severity": "high" if value >= .7 else "medium" if value >= .3 else "low", "weight": weights[name]}
        for name, value in signals.items() if value > 0
    ]
    score = round(min(1.0, sum(signals[name] * weights[name] for name in weights)), 4)
    critical_failure = liveness_passed is False or face_passed is False or distance > 2 * radius
    status = "rejected" if critical_failure or score >= .7 else "flagged" if score >= threshold else "approved"
    return RiskDecision(score=score, status=status, factors=factors)
