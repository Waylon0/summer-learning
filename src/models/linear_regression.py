"""线性回归模型：OLS、Ridge、Lasso，支持自动超参数调优。"""

import logging

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge, RidgeCV, Lasso, LassoCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.config import RANDOM_STATE, CV_FOLDS

logger = logging.getLogger("blueberry")


def compute_vif(X: pd.DataFrame) -> pd.DataFrame:
    """计算方差膨胀因子（VIF），用于多重共线性诊断。

    需要 statsmodels 库；若不可用则自动降级为基于相关矩阵的近似计算。

    Parameters
    ----------
    X : pd.DataFrame
        特征矩阵。

    Returns
    -------
    pd.DataFrame
        列：feature（特征名）、VIF（方差膨胀因子值），按 VIF 降序排列。
    """
    try:
        from statsmodels.stats.outliers_influence import variance_inflation_factor

        vif_data = pd.DataFrame({
            "feature": X.columns,
            "VIF": [variance_inflation_factor(X.values, i) for i in range(X.shape[1])],
        })
        return vif_data.sort_values("VIF", ascending=False)
    except ImportError:
        logging.getLogger("blueberry").warning(
            "statsmodels 未安装，VIF 使用相关矩阵近似计算。"
            "安装命令：pip install statsmodels"
        )
        corr = X.corr().abs()
        vif_data = pd.DataFrame({
            "feature": X.columns,
            "VIF": [1.0 / (1.0 - corr.loc[col].drop(col).max() ** 2) if len(X.columns) > 1 else 1.0
                    for col in X.columns],
        })
        return vif_data.sort_values("VIF", ascending=False)


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """安全计算 MAPE（平均绝对百分比误差），对真值为零的情况做保护。

    Parameters
    ----------
    y_true : np.ndarray
        真实值。
    y_pred : np.ndarray
        预测值。

    Returns
    -------
    float
        MAPE 百分比值（0-100）。
    """
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BlueberryLinearRegression:
    """OLS、Ridge 和 Lasso 回归的封装，支持交叉验证自动调优正则化强度。"""

    def __init__(self, random_state: int = RANDOM_STATE):
        """初始化线性回归器。

        Parameters
        ----------
        random_state : int
            随机种子。
        """
        self.random_state = random_state
        self.model = None
        self.model_type: str | None = None

    def fit_ols(self, X_train: pd.DataFrame, y_train: pd.Series):
        """训练普通最小二乘（OLS）回归。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。

        Returns
        -------
        self
        """
        self.model_type = "ols"
        self.model = LinearRegression()
        self.model.fit(X_train, y_train)
        logger.info("OLS 训练完成，截距=%.4f", self.model.intercept_)
        return self

    def fit_ridge(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        alpha: float = 1.0,
        tune: bool = False,
        alphas: np.ndarray | None = None,
    ):
        """训练 Ridge（L2 正则化）回归，可选自动 CV 调优 alpha。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        alpha : float
            正则化强度（tune=False 时使用）。
        tune : bool
            若为 True，使用 RidgeCV 自动选择 alpha。
        alphas : np.ndarray or None
            CV 搜索的 alpha 候选值，默认 logspace(-3, 3, 50)。

        Returns
        -------
        self
        """
        if tune:
            if alphas is None:
                alphas = np.logspace(-3, 3, 50)
            self.model = RidgeCV(alphas=alphas, cv=CV_FOLDS)
            self.model.fit(X_train, y_train)
            self.model_type = "ridge_cv"
            logger.info("RidgeCV 训练完成，alpha=%.4f", self.model.alpha_)
        else:
            self.model_type = "ridge"
            self.model = Ridge(alpha=alpha, random_state=self.random_state)
            self.model.fit(X_train, y_train)
            logger.info("Ridge 训练完成，alpha=%.4f", alpha)
        return self

    def fit_lasso(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        alpha: float = 0.1,
        tune: bool = False,
        alphas: np.ndarray | None = None,
    ):
        """训练 Lasso（L1 正则化）回归，可选自动 CV 调优 alpha。

        Parameters
        ----------
        X_train : pd.DataFrame
            训练特征。
        y_train : pd.Series
            训练目标。
        alpha : float
            正则化强度（tune=False 时使用）。
        tune : bool
            若为 True，使用 LassoCV 自动选择 alpha。
        alphas : np.ndarray or None
            CV 搜索的 alpha 候选值，默认 logspace(-4, 1, 50)。

        Returns
        -------
        self
        """
        if tune:
            if alphas is None:
                alphas = np.logspace(-4, 1, 50)
            self.model = LassoCV(
                alphas=alphas, cv=CV_FOLDS, random_state=self.random_state,
                max_iter=5000,
            )
            self.model.fit(X_train, y_train)
            self.model_type = "lasso_cv"
            logger.info("LassoCV 训练完成，alpha=%.4f", self.model.alpha_)
        else:
            self.model_type = "lasso"
            self.model = Lasso(
                alpha=alpha, random_state=self.random_state, max_iter=5000,
            )
            self.model.fit(X_train, y_train)
            logger.info("Lasso 训练完成，alpha=%.4f", alpha)
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
            包含 r2、rmse、mae、mape 四个指标。
        """
        return {
            "r2": float(r2_score(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": _safe_mape(y_true, y_pred),
        }

    def get_coefficients(self, feature_names: list[str]) -> pd.DataFrame:
        """返回按系数绝对值降序排列的系数表。

        Parameters
        ----------
        feature_names : list[str]
            与系数顺序对应的特征名列表。

        Returns
        -------
        pd.DataFrame
            列：feature、coefficient、abs_coef，按 abs_coef 降序排列。
        """
        coef_df = pd.DataFrame({
            "feature": feature_names,
            "coefficient": self.model.coef_,
        })
        coef_df["abs_coef"] = coef_df["coefficient"].abs()
        return coef_df.sort_values("abs_coef", ascending=False)

    def get_intercept(self) -> float:
        """返回模型截距。

        Returns
        -------
        float
            模型截距项。
        """
        return float(self.model.intercept_)
