"""Feature extraction for the acquittal-risk model.

Features (5-7 inputs, all derivable from the case file in Aranmanai):
1. Evidence strength (STRONG/MEDIUM/WEAK) — one-hot encoded
2. Witness count (int, normalized)
3. Hostile witness ratio (float 0-1)
4. FSL status (categorical, encoded)
5. BNSS §173 compliance (bool)
6. Total lapses detected (int)
7. FATAL lapses detected (int, dominant weight)
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Evidence strength encoding
_EVIDENCE_STRENGTH_ENCODING = {"STRONG": 0.0, "MEDIUM": 0.5, "WEAK": 1.0}
# FSL status encoding (more overdue = higher risk)
_FSL_STATUS_ENCODING = {"returned": 0.0, "in_queue": 0.5, "sent": 0.6, "not_sent": 0.7, "overdue": 1.0}


@dataclass
class FeatureVector:
    """Numerical features for the risk model."""
    evidence_weak: float       # 0=strong, 1=weak
    witness_count_norm: float  # 0=0 witnesses, 1=many (capped at 10)
    hostile_ratio: float       # 0-1
    fsl_overdue: float         # 0-1
    bnss_173_compliant: float  # 0 or 1
    total_lapses: float        # raw int, normalized
    fatal_lapses: float        # raw int (heavy weight)
    raw: dict[str, float] = field(default_factory=dict)


def compute_features(
    evidence_strength: str,
    witness_count: int,
    hostile_witness_count: int,
    fsl_status: str,
    bnss_173_compliant: bool,
    lapse_count: int,
    fatal_lapse_count: int,
) -> FeatureVector:
    """Build the FeatureVector from raw case attributes.

    The model is meant to be ADVISORY. Coefficients here are derived from
    BPRD / Quint 500 / DCRE studies on acquittal drivers, not learned from
    Aranmanai data (which we don't have at v1).
    """
    evidence_weak = _EVIDENCE_STRENGTH_ENCODING.get(evidence_strength.upper(), 0.5)
    witness_count_norm = min(witness_count, 10) / 10.0
    hostile_ratio = (hostile_witness_count / max(witness_count, 1)) if witness_count > 0 else 0.0
    fsl_overdue = _FSL_STATUS_ENCODING.get(fsl_status.lower(), 0.7)
    bnss_173 = 1.0 if bnss_173_compliant else 0.0
    total_lapses = min(lapse_count, 10) / 10.0
    fatal_lapses = min(fatal_lapse_count, 5) / 5.0

    return FeatureVector(
        evidence_weak=evidence_weak,
        witness_count_norm=witness_count_norm,
        hostile_ratio=hostile_ratio,
        fsl_overdue=fsl_overdue,
        bnss_173_compliant=bnss_173,
        total_lapses=total_lapses,
        fatal_lapses=fatal_lapses,
        raw={
            "evidence_weak": evidence_weak,
            "witness_count_norm": witness_count_norm,
            "hostile_ratio": hostile_ratio,
            "fsl_overdue": fsl_overdue,
            "bnss_173_compliant": bnss_173,
            "total_lapses": total_lapses,
            "fatal_lapses": fatal_lapses,
        },
    )
