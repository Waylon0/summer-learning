"""XGBoost 回归，支持网格搜索交叉验证和早停。

需要安装 xgboost：pip install xgboost
"""

import logging

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV

from src.config import CV_FOLDS, RANDOM_STATE

logger = logging.getLogger("blueberry")

XGB_AVAILABLE = False
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    logger.warning("xgboost 未安装，XGBoost 模型将不可用。"
                   "安装命令：pip install xgboost")


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """安全计算 MAPE。"""
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BlueberryXGBoost:
    """XGBoost 回归器，支持网格搜索和早停。

    若 xgboost 未安装，初始化时抛出 ImportError。
    """

    def __init__(self, random_state: int = RANDOM_STATE):
        """初始化 XGBoost 模型。

        Parameters
        ----------
        random_state : int
            随机种子。

        Raises
        ------
        ImportError
            若 xgboost 未安装。
        """
        if not XGB_AVAILABLE:
            raise ImportError(
                "xgboost 未安装。安装命令：pip install xgboost"
            )
        self.random_state = random_state
        self.model: xgb.XGBRegressor | None = None
        self.best_params: dict | None = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
        n_estimators: int = 300,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        n_jobs: int = -1,
    ):
        """训练 XGBoost 模型，可选早停。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        X_val : pd.DataFrame or None
            验证特征，用于早停。
        y_val : pd.Series or None
            验证目标，用于早停。
        n_estimators : int
            提升迭代轮数。
        max_depth : int
            树的最大深度。
        learning_rate : float
            学习率。
        subsample : float
            每棵树使用的训练样本比例。
        colsample_bytree : float
            每棵树使用的特征比例。
        n_jobs : int
            并行线程数。

        Returns
        -------
        self
        """
        self.model = xgb.XGBRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            random_state=self.random_state,
            n_jobs=n_jobs,
            verbosity=0,
        )

        if X_val is not None and y_val is not None:
            self.model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False,
            )
        else:
            self.model.fit(X_train, y_train)

        logger.info("XGBoost 训练完成，%d 棵树，深度=%d，学习率=%.3f",
                     n_estimators, max_depth, learning_rate)
        return self

    def grid_search(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        param_grid: dict | None = None,
        cv: int = CV_FOLDS,
        n_jobs: int = -1,
        verbose: int = 0,
    ) -> dict:
        """通过 GridSearchCV 搜索最优超参数。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        param_grid : dict or None
            参数搜索空间。
        cv : int
            交叉验证折数。
        n_jobs : int
            并行线程数。
        verbose : int
            日志详细程度。

        Returns
        -------
        dict
            sklearn.cv_results_ 字典。
        """
        if param_grid is None:
            param_grid = {
                "n_estimators": [100, 200, 300],
                "max_depth": [3, 6, 9],
                "learning_rate": [0.01, 0.05, 0.1],
                "subsample": [0.7, 0.8, 1.0],
                "colsample_bytree": [0.7, 0.8, 1.0],
            }

        model = xgb.XGBRegressor(
            random_state=self.random_state, n_jobs=n_jobs, verbosity=0,
        )
        search = GridSearchCV(
            model, param_grid, cv=cv, scoring="r2",
            n_jobs=n_jobs, verbose=verbose,
        )
        search.fit(X_train, y_train)
        self.best_params = search.best_params_
        self.model = search.best_estimator_
        logger.info("XGBoost GridSearchCV 最优参数: %s", self.best_params)
        logger.info("XGBoost GridSearchCV 最优得分: %.4f", search.best_score_)
        return search.cv_results_

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

    def get_feature_importance(self, feature_names: list[str]) -> pd.DataFrame:
        """返回按重要性降序排列的特征重要性表。

        Parameters
        ----------
        feature_names : list[str]
            特征名列表。

        Returns
        -------
        pd.DataFrame
            列：feature、importance。
        """
        imp_df = pd.DataFrame({
            "feature": feature_names,
            "importance": self.model.feature_importances_,
        })
        return imp_df.sort_values("importance", ascending=False)
