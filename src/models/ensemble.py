"""Stacking 集成学习：组合多个基回归器。"""

import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import StackingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.config import CV_FOLDS, RANDOM_STATE

logger = logging.getLogger("blueberry")


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """安全计算 MAPE。"""
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BlueberryEnsemble:
    """Stacking 集成模型，使用 Ridge 作为元学习器。"""

    def __init__(self, random_state: int = RANDOM_STATE):
        """初始化集成模型。

        Parameters
        ----------
        random_state : int
            随机种子。
        """
        self.random_state = random_state
        self.model: StackingRegressor | None = None
        self.base_estimators: list | None = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        estimators: list | None = None,
        final_estimator=None,
        cv: int = CV_FOLDS,
        n_jobs: int = -1,
    ):
        """训练 Stacking 集成模型。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        estimators : list or None
            (名称, 模型) 元组列表。
        final_estimator : estimator or None
            元学习器，默认使用 Ridge()。
        cv : int
            Stacking 使用的交叉验证折数。
        n_jobs : int
            并行线程数。

        Returns
        -------
        self

        Raises
        ------
        ValueError
            若未提供基学习器。
        """
        if estimators is None:
            raise ValueError("必须提供基学习器列表用于 Stacking 集成。")
        if final_estimator is None:
            final_estimator = Ridge()

        self.model = StackingRegressor(
            estimators=estimators,
            final_estimator=final_estimator,
            cv=cv,
            n_jobs=n_jobs,
            passthrough=False,
        )
        self.base_estimators = estimators
        self.model.fit(X_train, y_train)
        logger.info(
            "Stacking 集成训练完成，包含 %d 个基学习器", len(estimators),
        )
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """生成预测值。

        Parameters
        ----------
        X : pd.DataFrame
            待预测的特征矩阵。

        Returns
        -------
        np.ndarray
            预测产量数组。
        """
        return self.model.predict(X)

    def evaluate(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        """计算回归评估指标。

        Parameters
        ----------
        y_true : np.ndarray
            真实值。
        y_pred : np.ndarray
            预测值。

        Returns
        -------
        dict
            包含 r2、rmse、mae、mape。
        """
        return {
            "r2": float(r2_score(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": _safe_mape(y_true, y_pred),
        }
