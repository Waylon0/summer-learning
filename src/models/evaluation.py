import numpy as np
import pandas as pd
from sklearn.metrics import (
    r2_score,
    mean_squared_error,
    mean_absolute_error,
    explained_variance_score,
)
from sklearn.model_selection import cross_val_score


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "r2": r2_score(y_true, y_pred),
        "rmse": np.sqrt(mean_squared_error(y_true, y_pred)),
        "mae": mean_absolute_error(y_true, y_pred),
        "mape": np.mean(np.abs((y_true - y_pred) / np.where(y_true == 0, 1, y_true))) * 100,
        "explained_variance": explained_variance_score(y_true, y_pred),
    }


def cross_validate(model, X: pd.DataFrame, y: pd.Series, cv: int = 5) -> dict[str, float]:
    scores = cross_val_score(model, X, y, cv=cv, scoring="r2")
    return {
        "cv_mean_r2": scores.mean(),
        "cv_std_r2": scores.std(),
        "cv_scores": scores.tolist(),
    }


def compare_models(results: dict[str, dict[str, float]]) -> pd.DataFrame:
    df = pd.DataFrame(results).T
    return df.round(4)
