"""K-Means 聚类：应用于野生蓝莓产量场景分组。"""

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
    """K-Means 聚类，支持最优 K 值自动选择与面向业务解读的聚类画像。"""

    def __init__(self, random_state: int = RANDOM_STATE):
        """初始化聚类器。

        Parameters
        ----------
        random_state : int
            随机种子，确保结果可复现。
        """
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
        """在指定的 K 值范围内，用四种指标评估最佳的聚类数。

        Parameters
        ----------
        X : pd.DataFrame
            标准化后的特征矩阵。
        k_range : range
            K 的取值范围，默认 range(2, 11)。

        Returns
        -------
        dict
            包含 k_range、inertias、silhouette_scores、
            davies_bouldin_scores、calinski_harabasz_scores、
            best_k、optimal_metrics。
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
        """使用指定的 K 值训练 K-Means。

        Parameters
        ----------
        X : pd.DataFrame
            标准化后的特征矩阵。
        k : int
            聚类数。

        Returns
        -------
        self
        """
        self.k = k
        self.model = KMeans(n_clusters=k, random_state=self.random_state, n_init=10)
        self.labels = self.model.fit_predict(X)
        logger.info("K-Means 训练完成，K=%d", k)
        return self

    def get_cluster_stats(self, X: pd.DataFrame) -> pd.DataFrame:
        """返回每个聚类在各特征上的均值和标准差。

        Parameters
        ----------
        X : pd.DataFrame
            标准化后的特征矩阵。

        Returns
        -------
        pd.DataFrame
            多层列索引：(特征, mean) 和 (特征, std)。
        """
        X_with_labels = X.copy()
        X_with_labels["cluster"] = self.labels
        return X_with_labels.groupby("cluster").agg(["mean", "std"])

    def get_cluster_profiles(
        self, X: pd.DataFrame, y: pd.Series | None = None
    ) -> pd.DataFrame:
        """返回面向业务解读的聚类画像，含产量统计。

        Parameters
        ----------
        X : pd.DataFrame
            原始（未缩放）特征矩阵，使画像值可解释。
        y : pd.Series or None
            产量列，用于计算聚类级别的产量统计。

        Returns
        -------
        pd.DataFrame
            每聚类一行，包含样本数、占比、产量均值/标准差/最小/最大、
            以及各特征的聚类均值。按产量降序排列。
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
        """为雷达图准备归一化后的聚类特征均值数据。

        Parameters
        ----------
        X : pd.DataFrame
            原始（未缩放）特征矩阵。

        Returns
        -------
        pd.DataFrame
            每行一个聚类，每列一个特征，值归一化到 [0, 1] 区间。
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
        """返回所有样本的聚类标签。

        Returns
        -------
        np.ndarray
            聚类标签数组。
        """
        return self.labels
