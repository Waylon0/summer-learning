import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge, Lasso
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
from statsmodels.stats.outliers_influence import variance_inflation_factor
from src.config import RANDOM_STATE


def compute_vif(X: pd.DataFrame) -> pd.DataFrame:
    vif_data = pd.DataFrame({
        "feature": X.columns,
        "VIF": [variance_inflation_factor(X.values, i) for i in range(X.shape[1])],
    })
    vif_data = vif_data.sort_values("VIF", ascending=False)
    return vif_data


class BlueberryLinearRegression:
    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.model = None
        self.model_type = None

    def fit_ols(self, X_train: pd.DataFrame, y_train: pd.Series):
        self.model_type = "ols"
        self.model = LinearRegression()
        self.model.fit(X_train, y_train)
        return self

    def fit_ridge(
        self, X_train: pd.DataFrame, y_train: pd.Series, alpha: float = 1.0
    ):
        self.model_type = "ridge"
        self.model = Ridge(alpha=alpha, random_state=self.random_state)
        self.model.fit(X_train, y_train)
        return self

    def fit_lasso(
        self, X_train: pd.DataFrame, y_train: pd.Series, alpha: float = 1.0
    ):
        self.model_type = "lasso"
        self.model = Lasso(alpha=alpha, random_state=self.random_state, max_iter=5000)
        self.model.fit(X_train, y_train)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def evaluate(
        self, y_true: np.ndarray, y_pred: np.ndarray
    ) -> dict[str, float]:
        return {
            "r2": r2_score(y_true, y_pred),
            "rmse": np.sqrt(mean_squared_error(y_true, y_pred)),
            "mae": mean_absolute_error(y_true, y_pred),
            "mape": np.mean(np.abs((y_true - y_pred) / y_true)) * 100,
        }

    def get_coefficients(self, feature_names: list[str]) -> pd.DataFrame:
        coef_df = pd.DataFrame({
            "feature": feature_names,
            "coefficient": self.model.coef_,
        })
        coef_df["abs_coef"] = coef_df["coefficient"].abs()
        coef_df = coef_df.sort_values("abs_coef", ascending=False)
        return coef_df

    def get_intercept(self) -> float:
        return self.model.intercept_
