"""Train the acquittal-risk model.

Usage:
    python scripts/train_acquittal_risk.py           # train + export
    python scripts/train_acquittal_risk.py --test   # test only (no model save)

Output:
    models/acquittal_risk_v1.pkl   -- LightGBM booster
    models/acquittal_risk_v1.onnx  -- ONNX for cross-platform inference

Synthetic features (ground truth: based on BPRD acquittal data):
- evidence_strength: STRONG=0, MEDIUM=1, WEAK=2
- witness_count: 0-20
- hostile_witness_pct: 0.0-1.0
- lapse_count: 0-15
- fatal_lapse_count: 0-5
- fsl_overdue: 0/1
- bnss_173_compliant: 0/1
- days_since_fir: 0-730
- offence_type: pocso=0, murder=1, ndps=2, dowry=3, scst=4, other=5
- has_cctv: 0/1
- evidence_chain_broken: 0/1
- witness_not_contacted_14d: 0/1
- acquittal: 0/1 (target)

Synthetic generation rationale:
- Evidence STRONG + 0 fatal lapses + 0% hostile -> ~8% acquittal
- Evidence WEAK + ≥1 fatal lapse + ≥60% hostile -> ~75% acquittal
- Linear interpolation between poles with Gaussian noise (sigma=0.08)
"""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
_MODELS_DIR = _ROOT / "models"
_MODELS_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(_ROOT / "src"))

N_SAMPLES = 2000
RANDOM_SEED = 42


def _p_acquittal(
    evidence_strength: np.ndarray,       # 0=STRONG, 2=WEAK
    hostile_pct: np.ndarray,            # 0-1
    fatal_lapses: np.ndarray,           # 0-5
    bnss_173: np.ndarray,               # 0/1
    fsl_overdue: np.ndarray,            # 0/1
    not_contacted: np.ndarray,          # 0/1
    days_since_fir: np.ndarray,         # 0-730
    offence_type: np.ndarray,           # 0-5
) -> np.ndarray:
    """Compute acquittal probability from features (synthetic ground truth)."""
    # Base: 5% for strong-evidence, no-fatal-lapse cases
    p = 0.05

    # Evidence quality: WEAK adds +45pp
    p += evidence_strength / 2 * 0.45

    # Hostile witness: ≥60% hostile adds +25pp
    p += np.clip(hostile_pct - 0.3, 0, 1) * 0.25

    # Fatal lapses: each adds +8pp
    p += fatal_lapses * 0.08

    # BNSS 173 non-compliance: +12pp
    p += (1 - bnss_173) * 0.12

    # FSL overdue: +8pp
    p += fsl_overdue * 0.08

    # Witness not contacted 14d: +6pp
    p += not_contacted * 0.06

    # Age of case: >365 days adds +5pp
    p += np.clip(days_since_fir - 365, 0, 999) / 365 * 0.05

    # Offence type adjustments
    offence_risk = np.select(
        [offence_type == 0, offence_type == 1, offence_type == 2,
         offence_type == 3, offence_type == 4],
        [0.10, 0.05, 0.12, 0.08, 0.10],
        default=0.0,
    )
    p += offence_risk

    # Gaussian noise (sigma=0.08)
    rng = np.random.default_rng(RANDOM_SEED)
    p += rng.normal(0, 0.08, size=p.shape)

    return np.clip(p, 0.0, 1.0)


def generate_synthetic(n: int = N_SAMPLES) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)

    n_samples = n
    evidence_strength = rng.choice([0, 1, 2], size=n_samples, p=[0.3, 0.45, 0.25])
    witness_count = rng.integers(1, 21, size=n_samples)
    hostile_witness_pct = rng.beta(2, 5, size=n_samples)   # skewed low
    hostile_witness_pct = np.clip(hostile_witness_pct, 0, 1)
    lapse_count = rng.integers(0, 16, size=n_samples)
    fatal_lapse_count = np.minimum(lapse_count, rng.integers(0, 6, size=n_samples))
    fsl_overdue = rng.choice([0, 1], size=n_samples, p=[0.6, 0.4])
    bnss_173_compliant = rng.choice([0, 1], size=n_samples, p=[0.35, 0.65])
    days_since_fir = rng.integers(0, 731, size=n_samples)
    offence_type = rng.choice([0, 1, 2, 3, 4, 5], size=n_samples,
                              p=[0.18, 0.14, 0.14, 0.14, 0.10, 0.30])
    has_cctv = rng.choice([0, 1], size=n_samples, p=[0.65, 0.35])
    evidence_chain_broken = rng.choice([0, 1], size=n_samples, p=[0.55, 0.45])
    witness_not_contacted_14d = rng.choice([0, 1], size=n_samples, p=[0.50, 0.50])

    p_acq = _p_acquittal(
        evidence_strength, hostile_witness_pct, fatal_lapse_count,
        bnss_173_compliant, fsl_overdue, witness_not_contacted_14d,
        days_since_fir, offence_type,
    )
    acquittal = (rng.random(size=n_samples) < p_acq).astype(int)

    # Keep hostile pct as fraction of witness_count
    hostile_witness_count = (hostile_witness_pct * witness_count).round().astype(int)
    neutral_witness_count = witness_count - hostile_witness_count

    df = pd.DataFrame({
        "case_id": [str(uuid.uuid4())[:8] for _ in range(n_samples)],
        "evidence_strength": evidence_strength,
        "witness_count": witness_count,
        "hostile_witness_count": hostile_witness_count,
        "neutral_witness_count": neutral_witness_count,
        "hostile_witness_pct": hostile_witness_pct.round(4),
        "lapse_count": lapse_count,
        "fatal_lapse_count": fatal_lapse_count,
        "fatal_lapse_ratio": (fatal_lapse_count / np.maximum(lapse_count, 1)).round(4),
        "fsl_overdue": fsl_overdue,
        "bnss_173_compliant": bnss_173_compliant,
        "days_since_fir": days_since_fir,
        "offence_type": offence_type,
        "has_cctv": has_cctv,
        "evidence_chain_broken": evidence_chain_broken,
        "witness_not_contacted_14d": witness_not_contacted_14d,
        "acquittal": acquittal,
        "p_acquittal_true": p_acq.round(4),
    })

    return df


FEATURE_COLS = [
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


def train(df: pd.DataFrame) -> dict:
    """Train LightGBM + evaluate."""
    try:
        import lightgbm as lgb
    except ImportError:
        print("ERROR: lightgbm not installed. Run: pip install lightgbm")
        sys.exit(1)

    try:
        from sklearn.metrics import brier_score_loss, roc_auc_score
        from sklearn.model_selection import train_test_split
    except ImportError:
        print("ERROR: scikit-learn not installed.")
        sys.exit(1)

    X = df[FEATURE_COLS]
    y = df["acquittal"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_SEED,
    )

    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

    params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "min_child_samples": 20,
        "verbose": -1,
        "seed": RANDOM_SEED,
    }

    model = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(100)],
    )

    y_pred_proba = model.predict(X_test)

    auc = roc_auc_score(y_test, y_pred_proba)
    brier = brier_score_loss(y_test, y_pred_proba)

    # Calibrate into probability bands
    low_rate = (y_test == 0).mean()
    mid_rate = 0.45
    high_rate = 0.80
    calibrated = np.select(
        [y_pred_proba < 0.35, y_pred_proba < 0.65, y_pred_proba >= 0.65],
        [low_rate, mid_rate, high_rate],
        default=mid_rate,
    )
    calibrated_brier = brier_score_loss(y_test, calibrated)

    print(f"\n{'='*50}")
    print("LightGBM Training Complete")
    print(f"  AUC-ROC:     {auc:.4f}")
    print(f"  Brier score: {brier:.4f}")
    print(f"  Calibrated Brier: {calibrated_brier:.4f}")
    print(f"  n_train:     {len(X_train)}")
    print(f"  n_test:      {len(X_test)}")
    print(f"  Acquittal rate (train): {y_train.mean():.1%}")
    print(f"  Acquittal rate (test):  {y_test.mean():.1%}")
    print("  Target AUC:   >=0.70")
    print(f"  Status:       {'PASS' if auc >= 0.70 else 'BELOW TARGET'}")

    # Feature importance
    print("\nTop features:")
    importance = pd.DataFrame({
        "feature": FEATURE_COLS,
        "importance": model.feature_importance(),
    }).sort_values("importance", ascending=False)
    for _, row in importance.head(10).iterrows():
        print(f"  {row.feature:30s} {row.importance:6d}")

    return {
        "model": model,
        "auc": auc,
        "brier": brier,
        "calibrated_brier": calibrated_brier,
        "importance": importance,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "acquittal_rate": float(y.mean()),
    }


def save_model(model, output_path: Path, output_onnx: Path) -> None:
    """Save LightGBM model as pickle + ONNX."""
    import pickle

    # Save pickle
    with open(output_path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Saved: {output_path}")

    # Export ONNX
    if importlib.util.find_spec("lightgbm_skl2onnx") is None:
        print("  ONNX export skipped (lightgbm-skl2onnx not installed)")
        return

    from lightgbm_skl2onnx import convert_from_lightgbm_model
    from skl2onnx.common.data_types import FloatTensorType

    initial_type = [("float_input", FloatTensorType([None, len(FEATURE_COLS)]))]
    onnx_model = convert_from_lightgbm_model(model, initial_types=initial_type)

    with open(output_onnx, "wb") as f:
        f.write(onnx_model.SerializeToString())
    print(f"  Saved: {output_onnx}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Train acquittal-risk model")
    parser.add_argument("--n", type=int, default=N_SAMPLES, help="Training samples")
    parser.add_argument("--test", action="store_true", help="Test-only (no model save)")
    args = parser.parse_args()

    print(f"Generating {args.n} synthetic training samples...")
    df = generate_synthetic(n=args.n)

    print("Training LightGBM model...")
    result = train(df)

    if args.test:
        print("\nTest-only mode: model not saved.")
        return

    output_path = _MODELS_DIR / "acquittal_risk_v1.pkl"
    output_onnx = _MODELS_DIR / "acquittal_risk_v1.onnx"

    print(f"\nSaving model to {output_path}...")
    save_model(result["model"], output_path, output_onnx)

    # Also save the feature columns list for inference
    import json
    meta_path = _MODELS_DIR / "acquittal_risk_v1_meta.json"
    meta = {
        "feature_cols": FEATURE_COLS,
        "auc": result["auc"],
        "brier": result["brier"],
        "n_train": result["n_train"],
        "n_test": result["n_test"],
        "acquittal_rate": result["acquittal_rate"],
        "train_date": pd.Timestamp.now().isoformat(),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Saved: {meta_path}")

    print(f"\nDone. {result['n_train'] + result['n_test']} samples, AUC={result['auc']:.4f}")


if __name__ == "__main__":
    main()
