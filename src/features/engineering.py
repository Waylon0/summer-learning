"""Feature engineering: PCA, polynomial, interaction, log transforms, outlier removal."""

import numpy as np
import pandas as pd
from scipy.stats import zscore
from sklearn.decomposition import PCA


def add_polynomial_features(
    X: pd.DataFrame, columns: list[str], degree: int = 2
) -> pd.DataFrame:
    """Add polynomial (power) terms for specified columns.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix.
    columns : list[str]
        Columns to generate polynomial terms for.
    degree : int
        Maximum polynomial degree (>=2).

    Returns
    -------
    pd.DataFrame
        Augmented feature matrix.
    """
    X = X.copy()
    for col in columns:
        for d in range(2, degree + 1):
            X[f"{col}_pow{d}"] = X[col] ** d
    return X


def add_interaction_features(
    X: pd.DataFrame, pairs: list[tuple[str, str]]
) -> pd.DataFrame:
    """Add pairwise interaction (product) features.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix.
    pairs : list[tuple[str, str]]
        List of (col_a, col_b) pairs.

    Returns
    -------
    pd.DataFrame
        Augmented feature matrix.
    """
    X = X.copy()
    for a, b in pairs:
        X[f"{a}_x_{b}"] = X[a] * X[b]
    return X


def add_log_features(X: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Add log-transformed features with shift for non-positive values.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix.
    columns : list[str]
        Columns to log-transform.

    Returns
    -------
    pd.DataFrame
        Augmented feature matrix.
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
    """Remove rows where any specified column exceeds z-score threshold.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix.
    columns : list[str]
        Columns to check for outliers.
    threshold : float
        Z-score cutoff. Default 3.0.

    Returns
    -------
    pd.DataFrame
        Filtered dataframe.
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
    """Apply PCA dimensionality reduction.

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix.
    n_components : int or None
        Fixed number of components. If None, variance_threshold is used.
    variance_threshold : float
        Fraction of variance to retain (0 < threshold <= 1).

    Returns
    -------
    tuple
        (X_pca dataframe, fitted PCA object, explained_variance_ratio array).
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
    """Add cluster-based aggregate features (centroid distances, etc.).

    Parameters
    ----------
    X : pd.DataFrame
        Feature matrix (scaled).
    labels : np.ndarray
        Cluster labels for each row.
    agg_funcs : list[str] or None
        Aggregation functions for cluster profiles.

    Returns
    -------
    pd.DataFrame
        Augmented feature matrix with cluster-based features.
    """
    X_out = X.copy()
    X_out["_cluster"] = labels
    for col in X.columns:
        cluster_mean = X_out.groupby("_cluster")[col].transform("mean")
        X_out[f"{col}_cluster_dev"] = X_out[col] - cluster_mean
    X_out.drop(columns=["_cluster"], inplace=True)
    return X_out
