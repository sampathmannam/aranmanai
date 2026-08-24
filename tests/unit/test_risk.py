"""Unit tests for the risk scoring (features + predictor)."""
from __future__ import annotations


def test_compute_features_basic():
    from aranmanai.core.risk.features import compute_features
    fv = compute_features(
        evidence_strength="MEDIUM",
        witness_count=3,
        hostile_witness_count=1,
        fsl_status="sent",
        bnss_173_compliant=False,
        lapse_count=2,
        fatal_lapse_count=1,
    )
    assert fv.evidence_weak == 0.5
    assert fv.witness_count_norm == 0.3
    assert fv.hostile_ratio == 1 / 3
    assert fv.fsl_overdue == 0.6
    assert fv.bnss_173_compliant == 0.0
    assert fv.fatal_lapses == 0.2  # 1/5


def test_compute_features_normalizes_correctly():
    from aranmanai.core.risk.features import compute_features
    fv = compute_features(
        evidence_strength="WEAK",
        witness_count=20,  # capped at 10
        hostile_witness_count=5,
        fsl_status="overdue",
        bnss_173_compliant=True,
        lapse_count=20,  # capped at 10
        fatal_lapse_count=10,  # capped at 5
    )
    assert fv.witness_count_norm == 1.0
    assert fv.total_lapses == 1.0
    assert fv.fatal_lapses == 1.0


def test_risk_predictor_returns_score_0_to_1():
    from aranmanai.core.risk.features import compute_features
    from aranmanai.core.risk.predictor import RiskPredictor
    fv = compute_features(
        evidence_strength="STRONG",
        witness_count=5,
        hostile_witness_count=0,
        fsl_status="returned",
        bnss_173_compliant=True,
        lapse_count=0,
        fatal_lapse_count=0,
    )
    p = RiskPredictor()
    score = p.predict_proba(fv)
    assert 0.0 <= score <= 1.0
    assert score < 0.1  # strong case, low risk


def test_risk_predictor_high_when_many_fatal_lapses():
    from aranmanai.core.risk.features import compute_features
    from aranmanai.core.risk.predictor import RiskPredictor
    fv = compute_features(
        evidence_strength="WEAK",
        witness_count=2,
        hostile_witness_count=2,
        fsl_status="overdue",
        bnss_173_compliant=False,
        lapse_count=5,
        fatal_lapse_count=3,
    )
    p = RiskPredictor()
    score = p.predict_proba(fv)
    assert score >= 0.7


def test_risk_band_thresholds():
    from aranmanai.core.risk.predictor import RiskPredictor
    p = RiskPredictor()
    assert p.band(0.1) == "low"
    assert p.band(0.3) == "medium"
    assert p.band(0.5) == "medium"
    assert p.band(0.8) == "high"


def test_risk_top_factors_mentions_fatal_lapses():
    from aranmanai.core.risk.features import compute_features
    from aranmanai.core.risk.predictor import RiskPredictor
    fv = compute_features(
        evidence_strength="MEDIUM",
        witness_count=3,
        hostile_witness_count=1,
        fsl_status="sent",
        bnss_173_compliant=True,
        lapse_count=2,
        fatal_lapse_count=2,
    )
    p = RiskPredictor()
    factors = p.top_factors(fv)
    assert any("FATAL" in f for f in factors)
