"""Random Forest and XGBoost for fire occurrence, plus the evaluation used to
compare all three models on identical folds."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit


def build_random_forest(**kwargs) -> RandomForestClassifier:
    params = dict(
        n_estimators=500, min_samples_leaf=5,
        class_weight="balanced_subsample", n_jobs=-1, random_state=42,
    )
    params.update(kwargs)
    return RandomForestClassifier(**params)


def build_xgboost(**kwargs):
    from xgboost import XGBClassifier

    params = dict(
        n_estimators=600, learning_rate=0.05, max_depth=5,
        subsample=0.8, colsample_bytree=0.8,
        eval_metric="aucpr", random_state=42, n_jobs=-1,
    )
    params.update(kwargs)
    return XGBClassifier(**params)


def evaluate_temporal(model, X: pd.DataFrame, y: pd.Series, n_splits: int = 4) -> pd.DataFrame:
    """Score a model with forward-chaining splits over time.

    A plain random K-fold leaks the future into the past on panel data: rows from
    2024 end up training a model scored on 2021. ``X`` and ``y`` must already be
    sorted by year.

    PR-AUC leads because fire occurrence is imbalanced — ROC-AUC flatters a model
    that mostly predicts "no fire".
    """
    rows = []
    for fold, (train_idx, test_idx) in enumerate(TimeSeriesSplit(n_splits=n_splits).split(X), 1):
        model.fit(X.iloc[train_idx], y.iloc[train_idx])
        proba = model.predict_proba(X.iloc[test_idx])[:, 1]
        rows.append({
            "fold": fold,
            "n_train": len(train_idx),
            "n_test": len(test_idx),
            "pr_auc": average_precision_score(y.iloc[test_idx], proba),
            "roc_auc": roc_auc_score(y.iloc[test_idx], proba),
        })
    return pd.DataFrame(rows)


def importance_table(model, feature_names: list[str]) -> pd.DataFrame:
    imp = getattr(model, "feature_importances_", None)
    if imp is None:
        raise AttributeError(f"{type(model).__name__} exposes no feature_importances_")
    return (
        pd.DataFrame({"feature": feature_names, "importance": np.asarray(imp)})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )
