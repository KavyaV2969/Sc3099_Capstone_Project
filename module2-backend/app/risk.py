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


NETWORK_SIGNALS = ("vpn_detected", "proxy_detected", "tor_detected")


def _signal_type(category: str, *, critical: bool, liveness_missing: bool, known_device: bool,
                 shared_device: bool, network_signal: str, out_of_bounds: bool, accuracy_low: bool) -> str:
    """Name a category's contribution with the recommended schema's signal types.

    Non-schema names (liveness_missing, device_untrusted, device_shared, geo_distance)
    cover cases the schema list does not distinguish; see BACKEND-DEVIATIONS.md.
    """
    if category == "liveness":
        return "liveness_failed" if critical else "liveness_missing" if liveness_missing else "liveness_low_confidence"
    if category == "face_match":
        return "face_match_failed" if critical else "face_match_low_confidence"
    if category == "device":
        return "device_shared" if shared_device else "device_untrusted" if known_device else "device_unknown"
    if category == "network":
        return network_signal
    return "geo_out_of_bounds" if out_of_bounds else "geo_accuracy_low" if accuracy_low else "geo_distance"


def assess_risk(
    *, distance: float, radius: float, location_accuracy: float | None,
    require_liveness: bool, require_face: bool,
    liveness_score: float | None, liveness_passed: bool | None,
    face_score: float | None, face_passed: bool | None,
    known_device: bool, trusted_device: bool, local_network: bool,
    threshold: float, network_risk: float | None = None, impossible_travel: bool = False,
    liveness_requested: bool = False, shared_device: bool = False, network_signal: str = "vpn_detected",
) -> RiskDecision:
    """Score a check-in.

    ``require_liveness`` means liveness evidence was evaluated; ``liveness_requested``
    means the session asked for it. Requested-but-missing evidence is maximum
    liveness risk, as in the recommended integration guide, never a free pass.
    Review reasons (outside geofence, unknown/shared device, impossible travel,
    requested liveness not performed)
    flag an otherwise approved check-in without adding a rejection rule.

    Each factor's ``weight`` is its contribution to the score (as in the API
    example), so the weights of a check-in's factors sum to its risk score.
    """
    if not all(isfinite(v) for v in (distance, radius, threshold)) or (
        distance < 0 or radius <= 0 or not 0 <= threshold <= 1
        or (location_accuracy is not None and (not isfinite(location_accuracy) or location_accuracy < 0))
    ):
        raise ValueError("invalid risk inputs")
    if network_signal not in NETWORK_SIGNALS:
        raise ValueError("unknown network signal type")
    geo_risk = min(1.0, distance / radius)
    if network_risk is not None and (not isfinite(network_risk) or not 0 <= network_risk <= 1):
        raise ValueError("invalid network signal")
    accuracy_low = location_accuracy is None or location_accuracy > radius
    if accuracy_low:
        geo_risk = min(1.0, geo_risk + .25)
    liveness_missing = liveness_requested and not require_liveness
    if liveness_missing:
        if liveness_score is not None or liveness_passed is not None:
            raise ValueError("skipped liveness must have no evidence")
        liveness_risk = 1.0
    else:
        liveness_risk = _biometric_risk(require_liveness, liveness_score, liveness_passed, .6)
    signals = {
        "liveness": liveness_risk,
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
        {"type": _signal_type(name, critical=critical.get(name, False), liveness_missing=liveness_missing,
                              known_device=known_device, shared_device=shared_device,
                              network_signal=network_signal, out_of_bounds=distance > radius,
                              accuracy_low=accuracy_low),
         "category": name,
         "severity": "critical" if critical.get(name, False) else
                     "high" if value >= .7 else "medium" if value >= .3 else "low",
         "weight": round(contributions[name], 4), "risk": value,
         "critical": critical.get(name, False)}
        for name, value in signals.items() if value > 0 or critical.get(name, False)
    ]
    if impossible_travel:  # A behavioral reason with no score contribution.
        factors.append({"type": "impossible_travel", "category": "behavioral", "severity": "high",
                        "weight": 0.0, "risk": 1.0, "critical": False})
    score = round(min(1.0, sum(contributions.values())), 4)
    status = "rejected" if any(critical.values()) or score >= .7 else "flagged" if score >= threshold else "approved"
    # Skipping a liveness check the session requires must never auto-approve.
    review_reason = (distance > radius or not known_device or shared_device or impossible_travel
                     or liveness_missing)
    if status == "approved" and review_reason:
        status = "flagged"
    return RiskDecision(score, status, factors, contributions)
