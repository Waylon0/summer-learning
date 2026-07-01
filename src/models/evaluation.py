"""模型评估：综合指标计算、交叉验证、模型对比。"""

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
    """计算全面的回归评估指标。

    Parameters
    ----------
    y_true : np.ndarray
        真实值。
    y_pred : np.ndarray
        预测值。

    Returns
    -------
    dict
        包含 r2、rmse、mae、mape、explained_variance。
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
    """执行 k 折交叉验证。

    Parameters
    ----------
    model : estimator
        已训练的 sklearn 兼容模型。
    X : pd.DataFrame
        特征矩阵。
    y : pd.Series
        目标向量。
    cv : int
        折数。
    scoring : str
        评分指标名称。

    Returns
    -------
    dict
        包含 cv_mean（均值）、cv_std（标准差）、cv_scores（各折得分列表）。
    """
    scores = cross_val_score(model, X, y, cv=cv, scoring=scoring, n_jobs=-1)
    result = {
        "cv_mean": float(scores.mean()),
        "cv_std": float(scores.std()),
        "cv_scores": [float(s) for s in scores],
    }
    logger.info("CV %d折 %s: %.4f +/- %.4f", cv, scoring, result["cv_mean"], result["cv_std"])
    return result


def compare_models(results: dict[str, dict[str, float]]) -> pd.DataFrame:
    """创建模型结果对比表。

    Parameters
    ----------
    results : dict
        {模型名称: {指标名: 值}}。

    Returns
    -------
    pd.DataFrame
        行=模型，列=指标。保留 4 位小数。
    """
    df = pd.DataFrame(results).T
    return df.round(4)


def summarize_models(results: dict[str, dict[str, float]]) -> pd.DataFrame:
    """按 RMSE 升序排列模型对比表。

    Parameters
    ----------
    results : dict
        {模型名称: {指标名: 值}}。

    Returns
    -------
    pd.DataFrame
        按 RMSE 升序排列。
    """
    df = compare_models(results)
    if "rmse" in df.columns:
        df = df.sort_values("rmse", ascending=True)
    return df
