"""Linear regression models with automatic hyperparameter tuning."""

import logging

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge, RidgeCV, Lasso, LassoCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.config import RANDOM_STATE, CV_FOLDS

logger = logging.getLogger("blueberry")


def compute_vif(X: pd.DataFrame) -> pd.DataFrame:
    """Compute Variance Inflation Factor for multicollinearity diagnosis.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix.

    Returns
    -------
    pd.DataFrame
        Columns: feature, VIF. Sorted by VIF descending.
    """
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    vif_data = pd.DataFrame({
        "feature": X.columns,
        "VIF": [variance_inflation_factor(X.values, i) for i in range(X.shape[1])],
    })
    return vif_data.sort_values("VIF", ascending=False)


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Percentage Error with zero-value guard.

    Parameters
    ----------
    y_true : np.ndarray
        Ground truth values.
    y_pred : np.ndarray
        Predicted values.

    Returns
    -------
    float
        MAPE as percentage (0-100).
    """
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BlueberryLinearRegression:
    """Wrapper for OLS, Ridge, and Lasso regression with CV-tuning support."""

    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.model = None
        self.model_type: str | None = None

    def fit_ols(self, X_train: pd.DataFrame, y_train: pd.Series):
        """Fit Ordinary Least Squares regression.

        Parameters
        ----------
        X_train : pd.DataFrame
            Training features.
        y_train : pd.Series
            Training target.

        Returns
        -------
        self
        """
        self.model_type = "ols"
        self.model = LinearRegression()
        self.model.fit(X_train, y_train)
        logger.info("OLS fitted: intercept=%.4f", self.model.intercept_)
        return self

    def fit_ridge(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        alpha: float = 1.0,
        tune: bool = False,
        alphas: np.ndarray | None = None,
    ):
        """Fit Ridge regression, optionally with CV alpha tuning.

        Parameters
        ----------
        X_train : pd.DataFrame
            Training features.
        y_train : pd.Series
            Training target.
        alpha : float
            Regularization strength (ignored if tune=True).
        tune : bool
            If True, use RidgeCV to auto-select alpha.
        alphas : np.ndarray or None
            Alpha candidates for CV. Default logspace(-3, 3, 50).

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
            logger.info("RidgeCV fitted: alpha=%.4f", self.model.alpha_)
        else:
            self.model_type = "ridge"
            self.model = Ridge(alpha=alpha, random_state=self.random_state)
            self.model.fit(X_train, y_train)
            logger.info("Ridge fitted: alpha=%.4f", alpha)
        return self

    def fit_lasso(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        alpha: float = 0.1,
        tune: bool = False,
        alphas: np.ndarray | None = None,
    ):
        """Fit Lasso regression, optionally with CV alpha tuning.

        Parameters
        ----------
        X_train : pd.DataFrame
            Training features.
        y_train : pd.Series
            Training target.
        alpha : float
            Regularization strength (ignored if tune=True).
        tune : bool
            If True, use LassoCV to auto-select alpha.
        alphas : np.ndarray or None
            Alpha candidates for CV. Default logspace(-4, 1, 50).

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
            logger.info("LassoCV fitted: alpha=%.4f", self.model.alpha_)
        else:
            self.model_type = "lasso"
            self.model = Lasso(
                alpha=alpha, random_state=self.random_state, max_iter=5000,
            )
            self.model.fit(X_train, y_train)
            logger.info("Lasso fitted: alpha=%.4f", alpha)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate predictions.

        Parameters
        ----------
        X : pd.DataFrame
            Features to predict on.

        Returns
        -------
        np.ndarray
            Predicted yield values.
        """
        return self.model.predict(X)

    def evaluate(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        """Compute regression metrics.

        Parameters
        ----------
        y_true : np.ndarray
            Ground truth.
        y_pred : np.ndarray
            Predictions.

        Returns
        -------
        dict
            Keys: r2, rmse, mae, mape.
        """
        return {
            "r2": float(r2_score(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": _safe_mape(y_true, y_pred),
        }

    def get_coefficients(self, feature_names: list[str]) -> pd.DataFrame:
        """Return sorted coefficient table.

        Parameters
        ----------
        feature_names : list[str]
            Feature names matching coefficient order.

        Returns
        -------
        pd.DataFrame
            Columns: feature, coefficient, abs_coef. Sorted by abs_coef desc.
        """
        coef_df = pd.DataFrame({
            "feature": feature_names,
            "coefficient": self.model.coef_,
        })
        coef_df["abs_coef"] = coef_df["coefficient"].abs()
        return coef_df.sort_values("abs_coef", ascending=False)

    def get_intercept(self) -> float:
        """Return model intercept.

        Returns
        -------
        float
        """
        return float(self.model.intercept_)
