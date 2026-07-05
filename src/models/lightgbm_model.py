"""LightGBM 回归模型（Kaggle 竞赛主流选择之一）。

LightGBM 原理：
  - 基于直方图的决策树算法，将连续特征离散化为 bins，大幅降低计算量
  - 使用 Leaf-wise（按叶生长）策略，每次选择收益最大的叶子分裂，
    比 XGBoost 的 Level-wise 更快更准
  - 原生支持类别特征，无需 One-Hot 编码
  - GOSS（基于梯度的单边采样）保留大梯度样本、随机采样小梯度样本
  - EFB（互斥特征绑定）合并互斥特征减少维度

需要安装：pip install lightgbm
"""

import logging

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.config import CV_FOLDS, RANDOM_STATE

logger = logging.getLogger("blueberry")

LGB_AVAILABLE = False
try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except (ImportError, OSError):
    logger.warning("LightGBM 不可用（需安装 lightgbm 且系统支持）。将自动跳过。")


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BlueberryLightGBM:
    """LightGBM 回归器（Kaggle Top 模型之一）。

    若 lightgbm 不可用，初始化时抛出 ImportError。
    """

    def __init__(self, random_state: int = RANDOM_STATE):
        if not LGB_AVAILABLE:
            raise ImportError("LightGBM 不可用。安装：pip install lightgbm")
        self.random_state = random_state
        self.model: lgb.LGBMRegressor | None = None
        self.best_params: dict | None = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
        n_estimators: int = 300,
        max_depth: int = -1,
        learning_rate: float = 0.05,
        num_leaves: int = 31,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        n_jobs: int = -1,
    ):
        """训练 LightGBM。

        Parameters
        ----------
        X_train, y_train : 训练数据
        X_val, y_val : 验证数据（用于早停）
        n_estimators : 迭代轮数
        max_depth : 最大树深（-1 为不限制）
        learning_rate : 学习率
        num_leaves : 最大叶子数（控制模型复杂度）
        subsample : 样本采样率
        colsample_bytree : 特征采样率
        n_jobs : 并行线程
        """
        self.model = lgb.LGBMRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            num_leaves=num_leaves,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            random_state=self.random_state,
            n_jobs=n_jobs,
            verbosity=-1,
        )

        eval_set = [(X_val, y_val)] if X_val is not None and y_val is not None else None
        eval_metric = None
        callbacks = None
        if eval_set:
            callbacks = [lgb.early_stopping(stopping_rounds=50, verbose=False)]
            eval_metric = "rmse"

        self.model.fit(
            X_train, y_train,
            eval_set=eval_set,
            eval_metric=eval_metric,
            callbacks=callbacks,
        )

        logger.info("LightGBM 训练完成，%d 棵树，叶子=%d，学习率=%.3f",
                     n_estimators, num_leaves, learning_rate)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def evaluate(self, y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
        return {
            "r2": float(r2_score(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": _safe_mape(y_true, y_pred),
        }

    def get_feature_importance(self, feature_names: list[str]) -> pd.DataFrame:
        imp = pd.DataFrame({
            "feature": feature_names,
            "importance": self.model.feature_importances_,
        })
        return imp.sort_values("importance", ascending=False)
