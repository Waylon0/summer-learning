import pandas as pd
import numpy as np
from sklearn.decomposition import PCA
from scipy.stats import zscore


def add_polynomial_features(
    X: pd.DataFrame, columns: list[str], degree: int = 2
) -> pd.DataFrame:
    X = X.copy()
    for col in columns:
        for d in range(2, degree + 1):
            X[f"{col}_pow{d}"] = X[col] ** d
    return X


def add_interaction_features(X: pd.DataFrame, pairs: list[tuple[str, str]]) -> pd.DataFrame:
    X = X.copy()
    for a, b in pairs:
        X[f"{a}_x_{b}"] = X[a] * X[b]
    return X


def add_log_features(X: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    X = X.copy()
    for col in columns:
        min_val = X[col].min()
        shift = abs(min_val) + 1 if min_val <= 0 else 0
        X[f"log_{col}"] = np.log(X[col] + shift)
    return X


def remove_outliers_zscore(
    X: pd.DataFrame, columns: list[str], threshold: float = 3.0
) -> pd.DataFrame:
    mask = pd.Series(True, index=X.index)
    for col in columns:
        mask &= np.abs(zscore(X[col])) < threshold
    return X[mask]


def apply_pca(X: pd.DataFrame, n_components: int = None, variance_threshold: float = 0.95):
    if n_components is None:
        pca = PCA(n_components=variance_threshold)
    else:
        pca = PCA(n_components=n_components)
    X_pca = pca.fit_transform(X)
    cols = [f"PC{i+1}" for i in range(X_pca.shape[1])]
    explained = pca.explained_variance_ratio_
    return pd.DataFrame(X_pca, columns=cols, index=X.index), pca, explained
