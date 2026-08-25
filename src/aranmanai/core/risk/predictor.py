"""Acquittal-risk predictor.

Uses the trained LightGBM model at models/acquittal_risk_v1.pkl (AUC=0.72 on
synthetic data). Falls back to the linear heuristic if the model is not
available (e.g., first run before training).

The predict_proba / band / top_factors interface is stable and shared by both.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

from aranmanai.core.risk.features import FeatureVector
from aranmanai.observability import get_logger

log = get_logger(__name__)

# Project root = 4 levels up from core/risk/predictor.py:
#   predictor.py → core → aranmanai → src → <repo-root>
_MODELS_DIR = Path(__file__).resolve().parents[3].parent.parent / "models"
_MODEL_PATH = _MODELS_DIR / "acquittal_risk_v1.pkl"
_META_PATH = _MODELS_DIR / "acquittal_risk_v1_meta.json"

# Linear fallback coefficients (from BPRD / Quint / DCRE studies)
_LINEAR_COEFF = {
    "fatal_lapses": 0.35,
    "hostile_ratio": 0.20,
    "fsl_overdue": 0.15,
    "evidence_weak": 0.10,
    "bnss_173_compliant": 0.10,
    "total_lapses": 0.05,
    "witness_count_norm": 0.05,
}


class RiskPredictor:
    """Compute acquittal-risk score from features.

    Loads the trained LightGBM model if available; falls back to linear heuristic.
    """

    def __init__(self) -> None:
        self._model = None
        self._feature_cols: list[str] = []
        self._auc: float | None = None
        self._loaded = False
        self._load()

    def _load(self) -> None:
        if not _MODEL_PATH.exists():
            log.warning("risk.model_not_found fallback=linear model_path=%s", _MODEL_PATH)
            return
        try:
            with open(_MODEL_PATH, "rb") as f:
                self._model = pickle.load(f)
            import json
            if _META_PATH.exists():
                with open(_META_PATH) as f:
                    meta = json.load(f)
                    self._auc = meta.get("auc")
                    self._feature_cols = meta.get("feature_cols", [])
            self._loaded = True
            log.info("risk.model_loaded path=%s auc=%s", _MODEL_PATH, self._auc)
        except Exception as e:
            log.warning("risk.model_load_failed error=%s", e)
            self._model = None

    @property
    def has_model(self) -> bool:
        return self._loaded and self._model is not None

    def predict_proba(self, fv: FeatureVector) -> float:
        """Return probability of acquittal (0-1). Higher = riskier."""
        if self._model is not None:
            arr = np.array([fv.to_array()], dtype=np.float32)
            return float(np.clip(self._model.predict(arr)[0], 0.0, 1.0))
        return self._linear_score(fv)

    def _linear_score(self, fv: FeatureVector) -> float:
        """Fallback linear heuristic."""
        score = 0.0
        score += _LINEAR_COEFF["fatal_lapses"] * min(fv.fatal_lapse_count, 5) / 5.0
        score += _LINEAR_COEFF["hostile_ratio"] * fv.hostile_witness_pct
        score += _LINEAR_COEFF["fsl_overdue"] * fv.fsl_overdue
        score += _LINEAR_COEFF["evidence_weak"] * (fv.evidence_strength / 2.0)
        score += _LINEAR_COEFF["bnss_173_compliant"] * (1.0 - fv.bnss_173_compliant)
        score += _LINEAR_COEFF["total_lapses"] * min(fv.lapse_count, 10) / 10.0
        score += _LINEAR_COEFF["witness_count_norm"] * min(fv.witness_count, 10) / 10.0
        return min(max(score, 0.0), 1.0)

    def band(self, score: float) -> str:
        if score < 0.3:
            return "low"
        if score < 0.7:
            return "medium"
        return "high"

    def top_factors(self, fv: FeatureVector, k: int = 3) -> list[str]:
        """Return top-k contributing risk factors as human-readable strings."""
        contributions: list[tuple[float, str]] = []

        if fv.fatal_lapse_count > 0:
            contributions.append((
                fv.fatal_lapse_count / 5.0,
                f"{int(fv.fatal_lapse_count)} FATAL lapse(s) detected",
            ))
        if fv.hostile_witness_pct > 0.1:
            contributions.append((
                fv.hostile_witness_pct,
                f"hostile witness rate: {fv.hostile_witness_pct:.0%}",
            ))
        if fv.fsl_overdue > 0.5:
            contributions.append((
                0.15,
                "FSL report overdue or not sent",
            ))
        if fv.evidence_strength >= 1.5:
            contributions.append((
                fv.evidence_strength / 2.0,
                "evidence quality rated WEAK",
            ))
        if fv.bnss_173_compliant < 0.5:
            contributions.append((
                0.10,
                "BNSS section 173 non-compliant",
            ))
        if fv.lapse_count > 3:
            contributions.append((
                min(fv.lapse_count, 10) / 10.0,
                f"{int(fv.lapse_count)} total lapses",
            ))
        if fv.witness_not_contacted_14d > 0.5 and fv.witness_count > 0:
            contributions.append((
                0.06,
                "witness(es) not contacted in 14+ days",
            ))
        if fv.evidence_chain_broken > 0.5:
            contributions.append((
                0.05,
                "evidence chain of custody broken",
            ))
        if fv.days_since_fir > 365:
            contributions.append((
                0.05,
                f"case {int(fv.days_since_fir)} days old (>1 yr)",
            ))

        contributions.sort(key=lambda x: -x[0])
        return [c[1] for c in contributions[:k]]
