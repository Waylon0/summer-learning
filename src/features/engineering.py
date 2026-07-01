"""特征工程：PCA 降维、多项式、交互项、对数变换、异常值处理。"""

import numpy as np
import pandas as pd
from scipy.stats import zscore
from sklearn.decomposition import PCA


def add_polynomial_features(
    X: pd.DataFrame, columns: list[str], degree: int = 2
) -> pd.DataFrame:
    """为指定列添加多项式（幂）特征。

    Parameters
    ----------
    X : pd.DataFrame
        特征矩阵。
    columns : list[str]
        需生成多项式项的列名列表。
    degree : int
        最高多项式次数（>=2）。

    Returns
    -------
    pd.DataFrame
        扩充后的特征矩阵。
    """
    X = X.copy()
    for col in columns:
        for d in range(2, degree + 1):
            X[f"{col}_pow{d}"] = X[col] ** d
    return X


def add_interaction_features(
    X: pd.DataFrame, pairs: list[tuple[str, str]]
) -> pd.DataFrame:
    """添加两两特征交互（乘积）项。

    Parameters
    ----------
    X : pd.DataFrame
        特征矩阵。
    pairs : list[tuple[str, str]]
        交互对列表，每项为 (列名A, 列名B)。

    Returns
    -------
    pd.DataFrame
        扩充后的特征矩阵。
    """
    X = X.copy()
    for a, b in pairs:
        X[f"{a}_x_{b}"] = X[a] * X[b]
    return X


def add_log_features(X: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """为非正值自动平移后取对数的特征。

    Parameters
    ----------
    X : pd.DataFrame
        特征矩阵。
    columns : list[str]
        需对数变换的列名。

    Returns
    -------
    pd.DataFrame
        扩充后的特征矩阵。
    """
    X = X.copy()
    for col in columns:
        min_val = X[col].min()
        shift = abs(min_val) + 1 if min_val <= 0 else 0
        X[f"log_{col}"] = np.log(X[col] + shift)
    return X


def remove_outliers_zscore(
    X: pd.DataFrame, columns: list[str], threshold: float = 3.0
) -> pd.DataFrame:
    """删除指定列中 z-score 超过阈值的异常行。

    Parameters
    ----------
    X : pd.DataFrame
        特征矩阵。
    columns : list[str]
        需检测异常值的列。
    threshold : float
        z-score 阈值，默认 3.0。

    Returns
    -------
    pd.DataFrame
        剔除异常值后的数据框。
    """
    mask = pd.Series(True, index=X.index)
    for col in columns:
        mask &= np.abs(zscore(X[col])) < threshold
    return X[mask]


def apply_pca(
    X: pd.DataFrame,
    n_components: int | None = None,
    variance_threshold: float = 0.95,
) -> tuple[pd.DataFrame, PCA, np.ndarray]:
    """应用 PCA 降维。

    Parameters
    ----------
    X : pd.DataFrame
        特征矩阵。
    n_components : int or None
        固定主成分数。若为 None 则按方差阈值自动选择。
    variance_threshold : float
        保留方差比例（0 < threshold <= 1）。

    Returns
    -------
    tuple
        (X_pca 数据框, 训练好的 PCA 对象, 各成分解释方差比数组)。
    """
    if n_components is None:
        pca = PCA(n_components=variance_threshold, random_state=42)
    else:
        pca = PCA(n_components=n_components, random_state=42)
    X_pca = pca.fit_transform(X)
    cols = [f"PC{i + 1}" for i in range(X_pca.shape[1])]
    explained = pca.explained_variance_ratio_
    return (
        pd.DataFrame(X_pca, columns=cols, index=X.index),
        pca,
        explained,
    )


def add_cluster_features(
    X: pd.DataFrame, labels: np.ndarray, agg_funcs: list[str] | None = None,
) -> pd.DataFrame:
    """基于聚类标签添加聚类偏差特征（各样本距其所在聚类中心的偏差）。

    Parameters
    ----------
    X : pd.DataFrame
        特征矩阵（已标准化）。
    labels : np.ndarray
        各样本的聚类标签。
    agg_funcs : list[str] or None
        聚类聚合函数（当前仅使用 mean）。

    Returns
    -------
    pd.DataFrame
        扩充后的特征矩阵，新增 {列名}_cluster_dev 特征。
    """
    X_out = X.copy()
    X_out["_cluster"] = labels
    for col in X.columns:
        cluster_mean = X_out.groupby("_cluster")[col].transform("mean")
        X_out[f"{col}_cluster_dev"] = X_out[col] - cluster_mean
    X_out.drop(columns=["_cluster"], inplace=True)
    return X_out
