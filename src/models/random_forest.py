"""Random Forest regression with grid/random search tuning."""

import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV

from src.config import CV_FOLDS, RANDOM_STATE

logger = logging.getLogger("blueberry")


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BlueberryRandomForest:
    """Random Forest regressor with optional hyperparameter tuning."""

    def __init__(self, random_state: int = RANDOM_STATE):
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
        """Fit a Random Forest model.

        Parameters
        ----------
        X_train : pd.DataFrame
            Training features.
        y_train : pd.Series
            Training target.
        n_estimators : int
            Number of trees.
        max_depth : int or None
            Maximum tree depth.
        min_samples_split : int
            Minimum samples to split a node.
        min_samples_leaf : int
            Minimum samples per leaf.
        max_features : str
            Feature selection strategy.
        n_jobs : int
            Parallel jobs (-1 = all cores).

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
        logger.info("RandomForest fitted: %d trees", n_estimators)
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
        """Run GridSearchCV for hyperparameter optimization.

        Parameters
        ----------
        X_train : pd.DataFrame
            Training features.
        y_train : pd.Series
            Training target.
        param_grid : dict or None
            Parameter grid. Defaults to a predefined grid.
        cv : int
            Number of CV folds.
        n_jobs : int
            Parallel jobs.
        verbose : int
            Verbosity level.

        Returns
        -------
        dict
            Cross-validation results dict from sklearn.
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
        logger.info("GridSearchCV best params: %s", self.best_params)
        logger.info("GridSearchCV best score: %.4f", search.best_score_)
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
        """Run RandomizedSearchCV for faster hyperparameter exploration.

        Parameters
        ----------
        X_train : pd.DataFrame
            Training features.
        y_train : pd.Series
            Training target.
        param_dist : dict or None
            Parameter distributions.
        n_iter : int
            Number of random combinations to try.
        cv : int
            CV folds.
        n_jobs : int
            Parallel jobs.

        Returns
        -------
        dict
            CV results.
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
        logger.info("RandomizedSearchCV best params: %s", self.best_params)
        logger.info("RandomizedSearchCV best score: %.4f", search.best_score_)
        return search.cv_results_

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Generate predictions.

        Parameters
        ----------
        X : pd.DataFrame
            Features.

        Returns
        -------
        np.ndarray
            Predicted yield.
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

    def get_feature_importance(self, feature_names: list[str]) -> pd.DataFrame:
        """Return feature importance table sorted descending.

        Parameters
        ----------
        feature_names : list[str]
            Feature names matching importance order.

        Returns
        -------
        pd.DataFrame
            Columns: feature, importance.
        """
        imp_df = pd.DataFrame({
            "feature": feature_names,
            "importance": self.model.feature_importances_,
        })
        return imp_df.sort_values("importance", ascending=False)
