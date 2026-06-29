import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score
from src.config import RANDOM_STATE


class BlueberryClustering:
    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.model = None
        self.labels = None
        self.k = None

    def find_optimal_k(
        self,
        X: pd.DataFrame,
        k_range: range = range(2, 11),
    ) -> dict:
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
        return results

    def fit(self, X: pd.DataFrame, k: int):
        self.k = k
        self.model = KMeans(n_clusters=k, random_state=self.random_state, n_init=10)
        self.labels = self.model.fit_predict(X)
        return self

    def get_cluster_stats(self, X: pd.DataFrame) -> pd.DataFrame:
        X_with_labels = X.copy()
        X_with_labels["cluster"] = self.labels
        return X_with_labels.groupby("cluster").agg(["mean", "std"])

    def get_predictions(self) -> np.ndarray:
        return self.labels
