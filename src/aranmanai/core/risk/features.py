"""Feature extraction for the acquittal-risk model.

Trained feature set (13 features, from models/acquittal_risk_v1_meta.json):
  evidence_strength (0=STRONG, 1=MEDIUM, 2=WEAK)
  witness_count (raw int)
  hostile_witness_pct (0.0-1.0)
  lapse_count (raw int)
  fatal_lapse_count (raw int)
  fatal_lapse_ratio (0.0-1.0)
  fsl_overdue (0/1)
  bnss_173_compliant (0/1)
  days_since_fir (0-730)
  offence_type (0=pocso, 1=murder, 2=ndps, 3=dowry, 4=scst, 5=other)
  has_cctv (0/1)
  evidence_chain_broken (0/1)
  witness_not_contacted_14d (0/1)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aranmanai.observability import get_logger

log = get_logger(__name__)

_MODELS_DIR = Path(__file__).resolve().parents[3].parent.parent / "models"


# Evidence strength encoding
_EVIDENCE_STRENGTH_ENCODING = {"STRONG": 0, "MEDIUM": 1, "WEAK": 2}
_FSL_STATUS_ENCODING = {"returned": 0, "sent": 1, "in_queue": 2, "not_sent": 3, "overdue": 4}
_OFFENCE_ENCODING = {
    "pocso": 0, "posco": 0,
    "murder": 1, "homicide": 1,
    "ndps": 2, "drugs": 2, "ndps_act": 2,
    "dowry": 3, "304b": 3, "dowry_death": 3,
    "scst": 4, "poa": 4, "sc_st": 4,
}
_FEATURE_COLS = [
    "evidence_strength",
    "witness_count",
    "hostile_witness_pct",
    "lapse_count",
    "fatal_lapse_count",
    "fatal_lapse_ratio",
    "fsl_overdue",
    "bnss_173_compliant",
    "days_since_fir",
    "offence_type",
    "has_cctv",
    "evidence_chain_broken",
    "witness_not_contacted_14d",
]


def get_feature_cols() -> list[str]:
    """Return the model's expected feature columns."""
    meta_path = _MODELS_DIR / "acquittal_risk_v1_meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        return meta.get("feature_cols", _FEATURE_COLS)
    return _FEATURE_COLS


@dataclass
class FeatureVector:
    """Numerical features matching the trained LightGBM model."""
    evidence_strength: float
    witness_count: float
    hostile_witness_pct: float
    lapse_count: float
    fatal_lapse_count: float
    fatal_lapse_ratio: float
    fsl_overdue: float
    bnss_173_compliant: float
    days_since_fir: float
    offence_type: float
    has_cctv: float
    evidence_chain_broken: float
    witness_not_contacted_14d: float

    def to_array(self) -> list[float]:
        return [
            self.evidence_strength,
            self.witness_count,
            self.hostile_witness_pct,
            self.lapse_count,
            self.fatal_lapse_count,
            self.fatal_lapse_ratio,
            self.fsl_overdue,
            self.bnss_173_compliant,
            self.days_since_fir,
            self.offence_type,
            self.has_cctv,
            self.evidence_chain_broken,
            self.witness_not_contacted_14d,
        ]


def compute_features(
    evidence_strength: str,
    witness_count: int,
    hostile_witness_count: int,
    fsl_status: str,
    bnss_173_compliant: bool,
    lapse_count: int,
    fatal_lapse_count: int,
    offence_type: str = "other",
    days_since_fir: int = 0,
    has_cctv: bool = False,
    evidence_chain_broken: bool = False,
    witness_last_contact_days: int | None = None,
) -> FeatureVector:
    """Build the FeatureVector from raw case attributes.

    Defaults are conservative (low-risk) when data is unavailable.
    """
    es_val = _EVIDENCE_STRENGTH_ENCODING.get(evidence_strength.upper(), 1)
    wc = float(max(witness_count, 0))
    hw_pct = float(hostile_witness_count) / float(max(witness_count, 1))
    lc = float(max(lapse_count, 0))
    flc = float(min(fatal_lapse_count, lapse_count))
    fl_ratio = min(flc, 5.0) / float(max(min(lc, 5.0), 1))
    fsl_over = 1.0 if fsl_status.lower() in ("overdue", "not_sent") else 0.0
    bnss = 1.0 if bnss_173_compliant else 0.0
    dsf = float(max(0, min(days_since_fir, 730)))
    ot = float(_OFFENCE_ENCODING.get(offence_type.lower(), 5))
    cctv = 1.0 if has_cctv else 0.0
    ecb = 1.0 if evidence_chain_broken else 0.0
    wn14 = 1.0 if (witness_last_contact_days is None or witness_last_contact_days >= 14) else 0.0

    return FeatureVector(
        evidence_strength=es_val,
        witness_count=wc,
        hostile_witness_pct=hw_pct,
        lapse_count=lc,
        fatal_lapse_count=flc,
        fatal_lapse_ratio=fl_ratio,
        fsl_overdue=fsl_over,
        bnss_173_compliant=bnss,
        days_since_fir=dsf,
        offence_type=ot,
        has_cctv=cctv,
        evidence_chain_broken=ecb,
        witness_not_contacted_14d=wn14,
    )
