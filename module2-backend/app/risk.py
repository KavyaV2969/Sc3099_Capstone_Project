"""One documented weighted policy; required evidence cannot become a zero signal."""
from dataclasses import dataclass
from math import isfinite

POLICY = "weighted-v1"
WEIGHTS = {"liveness": .25, "face_match": .25, "device": .20, "network": .15, "geolocation": .15}


@dataclass(frozen=True)
class RiskDecision:
    score: float
    status: str
    factors: list[dict]
    contributions: dict[str, float]


def _biometric_risk(required: bool, score: float | None, passed: bool | None, cutoff: float) -> float:
    if not required:
        if score is not None or passed is not None:
            raise ValueError("disabled verification must have no evidence")
        return 0.0
    if type(passed) is not bool or type(score) not in {int, float} or not isfinite(score) or not 0 <= score <= 1:
        raise ValueError("required verification evidence is incomplete")
    if passed != (score >= cutoff):
        raise ValueError("verification evidence is inconsistent")
    return 1.0 - score


def assess_risk(
    *, distance: float, radius: float, location_accuracy: float,
    require_liveness: bool, require_face: bool,
    liveness_score: float | None, liveness_passed: bool | None,
    face_score: float | None, face_passed: bool | None,
    known_device: bool, trusted_device: bool, local_network: bool,
    threshold: float, network_risk: float | None = None, impossible_travel: bool = False,
) -> RiskDecision:
    if not all(isfinite(v) for v in (distance, radius, location_accuracy, threshold)) or (
        distance < 0 or radius <= 0 or location_accuracy < 0 or not 0 <= threshold <= 1
    ):
        raise ValueError("invalid risk inputs")
    geo_risk = min(1.0, distance / radius)
    if network_risk is not None and (not isfinite(network_risk) or not 0 <= network_risk <= 1):
        raise ValueError("invalid network signal")
    if location_accuracy > radius:
        geo_risk = min(1.0, geo_risk + .25)
    signals = {
        "liveness": _biometric_risk(require_liveness, liveness_score, liveness_passed, .6),
        "face_match": _biometric_risk(require_face, face_score, face_passed, .7),
        "device": 0.0 if known_device and trusted_device else .5 if known_device else 1.0,
        "network": network_risk if network_risk is not None else 0.0 if local_network else .2,
        "geolocation": geo_risk,
    }
    critical = {
        "liveness": require_liveness and liveness_passed is False,
        "face_match": require_face and face_passed is False,
        "geolocation": distance > 2 * radius,
    }
    contributions = {name: value * WEIGHTS[name] for name, value in signals.items()}
    factors = [
        {"type": name, "severity": "high" if value >= .7 else "medium" if value >= .3 else "low",
         "weight": WEIGHTS[name], "risk": value, "contribution": contributions[name],
         "critical": critical.get(name, False)}
        for name, value in signals.items() if value > 0 or critical.get(name, False)
    ]
    score = round(min(1.0, sum(contributions.values())), 4)
    status = "rejected" if any(critical.values()) or score >= .7 else "flagged" if score >= threshold else "approved"
    if impossible_travel:
        factors.append({"type": "impossible_travel", "severity": "high", "critical": False,
                        "risk": 1.0, "weight": 0.0, "contribution": 0.0})
        if status == "approved":
            status = "flagged"
    return RiskDecision(score, status, factors, contributions)
