"""Model evaluation: metrics, cross-validation, model comparison."""

import logging

import numpy as np
import pandas as pd
from sklearn.metrics import (
    explained_variance_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import cross_val_score

logger = logging.getLogger("blueberry")


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Compute comprehensive regression metrics.

    Parameters
    ----------
    y_true : np.ndarray
        Ground truth values.
    y_pred : np.ndarray
        Predicted values.

    Returns
    -------
    dict
        Keys: r2, rmse, mae, mape, explained_variance.
    """
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "mape": float(np.mean(np.abs((y_true - y_pred) / denom)) * 100),
        "explained_variance": float(explained_variance_score(y_true, y_pred)),
    }


def cross_validate(
    model,
    X: pd.DataFrame,
    y: pd.Series,
    cv: int = 5,
    scoring: str = "r2",
) -> dict[str, float]:
    """Run k-fold cross-validation.

    Parameters
    ----------
    model : estimator
        Scikit-learn compatible model.
    X : pd.DataFrame
        Feature matrix.
    y : pd.Series
        Target vector.
    cv : int
        Number of folds.
    scoring : str
        Scoring metric name.

    Returns
    -------
    dict
        Keys: cv_mean (mean score), cv_std (std), cv_scores (list of per-fold scores).
    """
    scores = cross_val_score(model, X, y, cv=cv, scoring=scoring, n_jobs=-1)
    result = {
        "cv_mean": float(scores.mean()),
        "cv_std": float(scores.std()),
        "cv_scores": [float(s) for s in scores],
    }
    logger.info("CV %d-fold %s: %.4f +/- %.4f", cv, scoring, result["cv_mean"], result["cv_std"])
    return result


def compare_models(results: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Create a comparison table of model results.

    Parameters
    ----------
    results : dict
        {model_name: {metric_name: value}}.

    Returns
    -------
    pd.DataFrame
        Rows = models, columns = metrics. Rounded to 4 decimals.
    """
    df = pd.DataFrame(results).T
    return df.round(4)


def summarize_models(results: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Rank models by RMSE and return ordered comparison.

    Parameters
    ----------
    results : dict
        {model_name: {metric_name: value}}.

    Returns
    -------
    pd.DataFrame
        Sorted by RMSE ascending.
    """
    df = compare_models(results)
    if "rmse" in df.columns:
        df = df.sort_values("rmse", ascending=True)
    return df
