"""Risk predictor.

For v1, this is a WEIGHTED LINEAR combination of features with coefficients
derived from BPRD / Quint / DCRE studies. Coefficients reflect the causal
weight of each acquittal driver. No ML training data needed at v1.

When real conviction/outcome data accumulates (months 3-6 pilot), this can
be replaced with a LightGBM model trained on that data. The interface
stays the same.

Coefficients (interpretable, ADVISORY):
- fatal_lapses:    0.35  (1 FATAL lapse alone ≈ +0.07 score)
- hostile_ratio:   0.20  (per unit, capped at 1.0)
- fsl_overdue:     0.15
- evidence_weak:   0.10
- bnss_173 == 0:   0.10  (AV recording missing is a procedural risk)
- total_lapses:    0.05
- witness_count_norm: 0.05 (more witnesses, slightly more risk of hostility)

Sum caps at 1.0. The score is the predicted probability of acquittal —
higher = more risky.
"""
from __future__ import annotations

from dataclasses import dataclass

from aranmanai.core.risk.features import FeatureVector
from aranmanai.observability import get_logger

log = get_logger(__name__)


# Coefficients (interpretable, derived from research)
_COEFF = {
    "fatal_lapses": 0.35,
    "hostile_ratio": 0.20,
    "fsl_overdue": 0.15,
    "evidence_weak": 0.10,
    "bnss_173_compliant": 0.10,  # contribution when 0
    "total_lapses": 0.05,
    "witness_count_norm": 0.05,
}


@dataclass
class RiskPrediction:
    score: float           # 0-1
    band: str              # "low" / "medium" / "high"
    top_factors: list[str] # human-readable contributing factors


class RiskPredictor:
    """Compute acquittal-risk score from features. Deterministic."""

    def __init__(self) -> None:
        # No model state in v1. Future: load LightGBM pickle from
        # models/risk_v1.pkl. The interface (predict_proba, band, top_factors)
        # stays the same.
        pass

    def predict_proba(self, fv: FeatureVector) -> float:
        """Returns probability of acquittal (0-1). Higher = riskier."""
        score = 0.0
        score += _COEFF["fatal_lapses"] * fv.fatal_lapses
        score += _COEFF["hostile_ratio"] * fv.hostile_ratio
        score += _COEFF["fsl_overdue"] * fv.fsl_overdue
        score += _COEFF["evidence_weak"] * fv.evidence_weak
        score += _COEFF["bnss_173_compliant"] * (1.0 - fv.bnss_173_compliant)
        score += _COEFF["total_lapses"] * fv.total_lapses
        score += _COEFF["witness_count_norm"] * fv.witness_count_norm
        return min(max(score, 0.0), 1.0)

    def band(self, score: float) -> str:
        # Bands per test thresholds: [0, 0.3)=low, [0.3, 0.7)=medium, [0.7, 1]=high
        if score < 0.3:
            return "low"
        if score < 0.7:
            return "medium"
        return "high"

    def top_factors(self, fv: FeatureVector, k: int = 3) -> list[str]:
        """Return top-k contributing factors as human-readable strings."""
        contributions: list[tuple[float, str]] = []
        if fv.fatal_lapses > 0:
            contributions.append((_COEFF["fatal_lapses"] * fv.fatal_lapses, f"FATAL lapses present (weight {_COEFF['fatal_lapses']:.2f})"))
        if fv.hostile_ratio > 0.1:
            contributions.append((_COEFF["hostile_ratio"] * fv.hostile_ratio, f"hostile witnesses ({fv.hostile_ratio:.0%})"))
        if fv.fsl_overdue > 0.5:
            contributions.append((_COEFF["fsl_overdue"] * fv.fsl_overdue, "FSL status overdue or not sent"))
        if fv.evidence_weak > 0.5:
            contributions.append((_COEFF["evidence_weak"] * fv.evidence_weak, "weak evidence strength"))
        if fv.bnss_173_compliant < 0.5:
            contributions.append((_COEFF["bnss_173_compliant"] * (1.0 - fv.bnss_173_compliant), "BNSS §173 AV recording missing"))
        if fv.total_lapses > 0.3:
            contributions.append((_COEFF["total_lapses"] * fv.total_lapses, f"multiple lapses ({fv.total_lapses:.0%} saturation)"))
        if fv.witness_count_norm > 0.5:
            contributions.append((_COEFF["witness_count_norm"] * fv.witness_count_norm, "many witnesses (hostility surface)"))
        contributions.sort(key=lambda x: -x[0])
        return [c[1] for c in contributions[:k]]
