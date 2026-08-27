"""Logistic-regression baseline for municipality-year fire occurrence.

Every later model is judged against this. A model that cannot beat it does not
belong in the report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def build_baseline(numeric_features: list[str]) -> Pipeline:
    """Impute -> scale -> logistic regression, as one fitted-together pipeline.

    Wrapping the preprocessing in the pipeline is what keeps the imputer and
    scaler from being fitted on the validation fold.
    """
    pre = ColumnTransformer(
        [("num", Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]), numeric_features)],
        remainder="drop",
    )
    return Pipeline([
        ("pre", pre),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])


def coefficient_table(pipeline: Pipeline, numeric_features: list[str]) -> pd.DataFrame:
    """Readable coefficients, sorted by magnitude — the interpretable output."""
    coefs = pipeline.named_steps["clf"].coef_[0]
    return (
        pd.DataFrame({"feature": numeric_features, "coefficient": coefs})
        .assign(odds_ratio=lambda d: np.exp(d["coefficient"]))
        .sort_values("coefficient", key=abs, ascending=False)
        .reset_index(drop=True)
    )
