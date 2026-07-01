"""随机森林回归，支持网格搜索/随机搜索超参数调优。"""

import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV

from src.config import CV_FOLDS, RANDOM_STATE

logger = logging.getLogger("blueberry")


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """安全计算 MAPE。"""
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BlueberryRandomForest:
    """随机森林回归器，支持可选的超参数搜索。"""

    def __init__(self, random_state: int = RANDOM_STATE):
        """初始化随机森林模型。

        Parameters
        ----------
        random_state : int
            随机种子。
        """
        self.random_state = random_state
        self.model: RandomForestRegressor | None = None
        self.best_params: dict | None = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        n_estimators: int = 200,
        max_depth: int | None = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        max_features: str = "sqrt",
        n_jobs: int = -1,
    ):
        """训练随机森林模型。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        n_estimators : int
            决策树数量。
        max_depth : int or None
            最大树深。
        min_samples_split : int
            节点分裂最小样本数。
        min_samples_leaf : int
            叶节点最小样本数。
        max_features : str
            特征选择策略。
        n_jobs : int
            并行线程数（-1 表示全部核）。

        Returns
        -------
        self
        """
        self.model = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            max_features=max_features,
            random_state=self.random_state,
            n_jobs=n_jobs,
        )
        self.model.fit(X_train, y_train)
        logger.info("随机森林训练完成，%d 棵树", n_estimators)
        return self

    def grid_search(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        param_grid: dict | None = None,
        cv: int = CV_FOLDS,
        n_jobs: int = -1,
        verbose: int = 0,
    ):
        """通过 GridSearchCV 查找最优超参数。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        param_grid : dict or None
            参数搜索空间，默认使用预定义网格。
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
                "max_depth": [None, 10, 20, 30],
                "min_samples_split": [2, 5, 10],
                "min_samples_leaf": [1, 2, 4],
                "max_features": ["sqrt", "log2"],
            }

        rf = RandomForestRegressor(random_state=self.random_state, n_jobs=n_jobs)
        search = GridSearchCV(
            rf, param_grid, cv=cv, scoring="r2", n_jobs=n_jobs, verbose=verbose,
        )
        search.fit(X_train, y_train)
        self.best_params = search.best_params_
        self.model = search.best_estimator_
        logger.info("GridSearchCV 最优参数: %s", self.best_params)
        logger.info("GridSearchCV 最优得分: %.4f", search.best_score_)
        return search.cv_results_

    def randomized_search(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        param_dist: dict | None = None,
        n_iter: int = 50,
        cv: int = CV_FOLDS,
        n_jobs: int = -1,
    ):
        """通过 RandomizedSearchCV 快速探索超参数空间。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        param_dist : dict or None
            参数分布。
        n_iter : int
            随机搜索组合数。
        cv : int
            交叉验证折数。
        n_jobs : int
            并行线程数。

        Returns
        -------
        dict
            sklearn.cv_results_ 字典。
        """
        if param_dist is None:
            param_dist = {
                "n_estimators": [50, 100, 200, 300, 400],
                "max_depth": [None, 5, 10, 20, 30, 40],
                "min_samples_split": [2, 5, 10],
                "min_samples_leaf": [1, 2, 4],
                "max_features": ["sqrt", "log2"],
            }

        rf = RandomForestRegressor(random_state=self.random_state, n_jobs=n_jobs)
        search = RandomizedSearchCV(
            rf, param_dist, n_iter=n_iter, cv=cv, scoring="r2",
            random_state=self.random_state, n_jobs=n_jobs,
        )
        search.fit(X_train, y_train)
        self.best_params = search.best_params_
        self.model = search.best_estimator_
        logger.info("RandomizedSearchCV 最优参数: %s", self.best_params)
        logger.info("RandomizedSearchCV 最优得分: %.4f", search.best_score_)
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
