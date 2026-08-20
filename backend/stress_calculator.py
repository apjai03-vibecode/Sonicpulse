"""
stress_calculator.py
---------------------
Converts loudness (normalized dB), the detected sound category, and the
classifier's confidence into a single 0-100 "Urban Stress Index", plus a
categorical state label the frontend uses for colour-coding.

Formula (matches the project spec):

    Urban_Stress_Score = min(100, round(Normalized_dB * Category_Multiplier
                                         * Confidence, 1))

Where:
    Normalized_dB      -> peak dBFS rescaled to a 0-100 loudness scale
    Category_Multiplier-> severity weight for the detected sound class
    Confidence          -> classifier confidence as a 0-1 fraction
"""

from __future__ import annotations

# Severity multipliers per acoustic category. Higher = more stress-inducing
# for a given loudness. Unknown/unlisted classes default to a neutral 1.0.
CATEGORY_MULTIPLIERS: dict[str, float] = {
    "Siren / Alarm": 1.6,
    "Jackhammer / Drilling": 1.5,
    "Heavy Machinery": 1.45,
    "Train Horn": 1.35,
    "Car Horn / Traffic": 1.3,
    "Bus / Diesel Engine": 1.25,
    "Dog Bark": 1.1,
    "Ambient / Speech": 0.5,
    "Nature / Wind": 0.2,
}

DEFAULT_MULTIPLIER = 1.0

# Stress-state thresholds, kept in lockstep with the frontend's CSS
# breakpoints (sp-badge-calm / moderate / severe / critical).
_THRESHOLDS = (
    (85, "CRITICAL"),
    (65, "SEVERE"),
    (35, "MODERATE"),
)


def normalize_dbfs(peak_dbfs: float, floor_db: float = -60.0, ceiling_db: float = -3.0) -> float:
    """
    Rescale a peak dBFS reading (typically -60 dB silence to -3 dB near
    clipping) onto a 0-100 "loudness" scale used by the stress formula.
    """
    span = ceiling_db - floor_db
    normalized = (peak_dbfs - floor_db) / span * 100.0
    return max(0.0, min(100.0, normalized))


def category_multiplier(sound_class: str) -> float:
    return CATEGORY_MULTIPLIERS.get(sound_class, DEFAULT_MULTIPLIER)


def stress_state(score: float) -> str:
    for threshold, label in _THRESHOLDS:
        if score >= threshold:
            return label
    return "CALM"


def compute_stress_index(peak_dbfs: float, sound_class: str, confidence_pct: float) -> dict:
    """
    Returns {"stressIndex": float, "stressState": str} for the given
    acoustic reading.

    confidence_pct is expected on a 0-100 scale (as returned by the
    classifier / sent to the frontend); it's converted to a 0-1 fraction
    for the formula.
    """
    normalized_db = normalize_dbfs(peak_dbfs)
    multiplier = category_multiplier(sound_class)
    confidence_fraction = max(0.0, min(1.0, confidence_pct / 100.0))

    raw_score = normalized_db * multiplier * confidence_fraction
    stress_index = round(min(100.0, raw_score), 1)

    return {
        "stressIndex": stress_index,
        "stressState": stress_state(stress_index),
    }
