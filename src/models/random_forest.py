import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
from src.config import RANDOM_STATE


class BlueberryRandomForest:
    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.model = None
        self.best_params = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        n_estimators: int = 200,
        max_depth: int = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        max_features: str = "sqrt",
        n_jobs: int = -1,
    ):
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
        return self

    def grid_search(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        param_grid: dict = None,
        cv: int = 5,
        n_jobs: int = -1,
        verbose: int = 0,
    ):
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
            rf, param_grid, cv=cv, scoring="r2", n_jobs=n_jobs, verbose=verbose
        )
        search.fit(X_train, y_train)
        self.best_params = search.best_params_
        self.model = search.best_estimator_
        return search.cv_results_

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

    def get_feature_importance(self, feature_names: list[str]) -> pd.DataFrame:
        imp_df = pd.DataFrame({
            "feature": feature_names,
            "importance": self.model.feature_importances_,
        })
        imp_df = imp_df.sort_values("importance", ascending=False)
        return imp_df
