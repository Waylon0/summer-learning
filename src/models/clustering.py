"""K-Means clustering for wild blueberry yield segmentation."""

import logging

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import (
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)

from src.config import RANDOM_STATE, TARGET

logger = logging.getLogger("blueberry")


class BlueberryClustering:
    """K-Means clustering with optimal K selection and business-oriented profiling."""

    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.model: KMeans | None = None
        self.labels: np.ndarray | None = None
        self.k: int | None = None
        self.optimal_results: dict | None = None

    def find_optimal_k(
        self,
        X: pd.DataFrame,
        k_range: range | None = None,
    ) -> dict:
        """Evaluate K-Means for a range of K values using four metrics.

        Parameters
        ----------
        X : pd.DataFrame
            Scaled feature matrix.
        k_range : range
            Range of K values to try. Default range(2, 11).

        Returns
        -------
        dict
            Keys: k_range, inertias, silhouette_scores, davies_bouldin_scores,
            calinski_harabasz_scores, best_k, optimal_metrics.
        """
        if k_range is None:
            k_range = range(2, 11)

        inertias = []
        silhouette_scores = []
        db_scores = []
        ch_scores = []

        for k in k_range:
            km = KMeans(n_clusters=k, random_state=self.random_state, n_init=10)
            labels = km.fit_predict(X)
            inertias.append(km.inertia_)
            silhouette_scores.append(silhouette_score(X, labels))
            db_scores.append(davies_bouldin_score(X, labels))
            ch_scores.append(calinski_harabasz_score(X, labels))

        results = {
            "k_range": list(k_range),
            "inertias": inertias,
            "silhouette_scores": silhouette_scores,
            "davies_bouldin_scores": db_scores,
            "calinski_harabasz_scores": ch_scores,
        }

        best_k_sil = list(k_range)[np.argmax(silhouette_scores)]
        results["best_k"] = best_k_sil
        results["optimal_metrics"] = {
            "silhouette": max(silhouette_scores),
            "davies_bouldin": min(db_scores),
            "calinski_harabasz": max(ch_scores),
        }
        self.optimal_results = results
        return results

    def fit(self, X: pd.DataFrame, k: int):
        """Fit K-Means with the specified K.

        Parameters
        ----------
        X : pd.DataFrame
            Scaled feature matrix.
        k : int
            Number of clusters.

        Returns
        -------
        self
        """
        self.k = k
        self.model = KMeans(n_clusters=k, random_state=self.random_state, n_init=10)
        self.labels = self.model.fit_predict(X)
        logger.info("K-Means fitted with K=%d", k)
        return self

    def get_cluster_stats(self, X: pd.DataFrame) -> pd.DataFrame:
        """Return per-cluster mean and std for all features.

        Parameters
        ----------
        X : pd.DataFrame
            Scaled feature matrix.

        Returns
        -------
        pd.DataFrame
            Multi-level columns: (feature, mean) and (feature, std).
        """
        X_with_labels = X.copy()
        X_with_labels["cluster"] = self.labels
        return X_with_labels.groupby("cluster").agg(["mean", "std"])

    def get_cluster_profiles(
        self, X: pd.DataFrame, y: pd.Series | None = None
    ) -> pd.DataFrame:
        """Return business-oriented cluster profiles with yield statistics.

        Parameters
        ----------
        X : pd.DataFrame
            Original (unscaled) feature matrix for interpretable profiles.
        y : pd.Series or None
            Yield values for computing cluster-level yield stats.

        Returns
        -------
        pd.DataFrame
            Per-cluster summary with count, mean yield, and key feature means.
        """
        profiles = pd.DataFrame({"cluster": self.labels})
        profiles["count"] = 1
        profiles = profiles.groupby("cluster")["count"].count().to_frame()
        profiles["pct"] = (profiles["count"] / len(self.labels) * 100).round(2)

        if y is not None:
            profiles["yield_mean"] = pd.Series(y).groupby(self.labels).mean()
            profiles["yield_std"] = pd.Series(y).groupby(self.labels).std()
            profiles["yield_min"] = pd.Series(y).groupby(self.labels).min()
            profiles["yield_max"] = pd.Series(y).groupby(self.labels).max()

        for col in X.columns:
            profiles[f"{col}_mean"] = pd.Series(X[col]).groupby(self.labels).mean()

        profiles = profiles.sort_values("yield_mean", ascending=False) if y is not None else profiles
        return profiles.round(3)

    def get_radar_data(self, X: pd.DataFrame) -> pd.DataFrame:
        """Prepare normalized per-cluster feature means for radar visualization.

        Parameters
        ----------
        X : pd.DataFrame
            Original (unscaled) feature matrix.

        Returns
        -------
        pd.DataFrame
            Per-cluster means normalized to [0, 1] across clusters.
        """
        profile = X.copy()
        profile["cluster"] = self.labels
        means = profile.groupby("cluster").mean()
        mins, maxs = means.min(), means.max()
        denom = maxs - mins
        denom[denom == 0] = 1
        normalized = (means - mins) / denom
        return normalized

    def get_predictions(self) -> np.ndarray:
        """Return cluster labels for all samples.

        Returns
        -------
        np.ndarray
            Cluster assignment array.
        """
        return self.labels
