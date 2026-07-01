"""Visualization functions: correlation, clustering, model diagnostics, comparison."""

import os

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

from src.config import FIGURES_DIR

os.makedirs(FIGURES_DIR, exist_ok=True)


def save(fig: plt.Figure, name: str) -> str:
    """Save figure to outputs/figures/ and close it.

    Parameters
    ----------
    fig : plt.Figure
        Matplotlib figure.
    name : str
        Filename (e.g. 'correlation_heatmap.png').

    Returns
    -------
    str
        Full path to saved file.
    """
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ------------------------------------------------------------------ Correlation


def plot_correlation_heatmap(
    df: pd.DataFrame,
    title: str = "Feature Correlation Heatmap",
    mask_upper: bool = True,
) -> plt.Figure:
    """Plot upper-triangle correlation heatmap.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe (features + optionally target).
    title : str
        Plot title.
    mask_upper : bool
        Mask upper triangle to avoid redundancy.

    Returns
    -------
    plt.Figure
    """
    corr = df.corr(numeric_only=True)
    mask = np.triu(np.ones_like(corr, dtype=bool)) if mask_upper else None
    fig, ax = plt.subplots(figsize=(14, 12))
    sns.heatmap(
        corr, mask=mask, annot=True, fmt=".2f", cmap="RdBu_r",
        center=0, square=True, linewidths=0.5, ax=ax,
        cbar_kws={"shrink": 0.8},
    )
    ax.set_title(title, fontsize=14, fontweight="bold")
    save(fig, "correlation_heatmap.png")
    return fig


# --------------------------------------------------------------- Distribution


def plot_distribution(
    df: pd.DataFrame,
    columns: list[str],
    rows: int | None = None,
    cols: int = 4,
) -> plt.Figure:
    """Plot histograms for multiple columns in a grid.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe with feature columns.
    columns : list[str]
        Column names to plot.
    rows : int or None
        Number of rows (auto-computed if None).
    cols : int
        Number of columns.

    Returns
    -------
    plt.Figure
    """
    n = len(columns)
    if rows is None:
        rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3))
    axes = axes.flatten()
    for i, col in enumerate(columns):
        ax = axes[i]
        ax.hist(df[col].dropna(), bins=50, edgecolor="white", alpha=0.7, color="steelblue")
        ax.set_title(col, fontsize=9)
        ax.set_xlabel("")
    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)
    fig.suptitle("Feature Distributions", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "feature_distributions.png")
    return fig


# ------------------------------------------------------------------ Clustering


def plot_elbow(
    inertias: list[float],
    k_range: range,
    optimal_k: int | None = None,
) -> plt.Figure:
    """Plot Elbow method curve with optional optimal-K vertical line.

    Parameters
    ----------
    inertias : list[float]
        Inertia values per K.
    k_range : range
        Range of K values.
    optimal_k : int or None
        Highlighted optimal K.

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(list(k_range), inertias, "bo-", markersize=6)
    if optimal_k is not None:
        ax.axvline(optimal_k, color="red", linestyle="--", label=f"Optimal K={optimal_k}")
        ax.legend()
    ax.set_xlabel("K (Number of Clusters)")
    ax.set_ylabel("Inertia (WCSS)")
    ax.set_title("Elbow Method for Optimal K")
    ax.grid(True, alpha=0.3)
    save(fig, "elbow_method.png")
    return fig


def plot_cluster_metrics(
    results: dict,
) -> plt.Figure:
    """Plot silhouette, Davies-Bouldin, and Calinski-Harabasz scores vs K.

    Parameters
    ----------
    results : dict
        Output from BlueberryClustering.find_optimal_k().

    Returns
    -------
    plt.Figure
    """
    k_range = results["k_range"]
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    axes[0].plot(k_range, results["silhouette_scores"], "bo-", markersize=6)
    best_k = results["best_k"]
    axes[0].axvline(best_k, color="red", linestyle="--")
    axes[0].set_title("Silhouette Score")
    axes[0].set_xlabel("K")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(k_range, results["davies_bouldin_scores"], "go-", markersize=6)
    axes[1].axvline(best_k, color="red", linestyle="--")
    axes[1].set_title("Davies-Bouldin Index")
    axes[1].set_xlabel("K")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(k_range, results["calinski_harabasz_scores"], "mo-", markersize=6)
    axes[2].axvline(best_k, color="red", linestyle="--")
    axes[2].set_title("Calinski-Harabasz Score")
    axes[2].set_xlabel("K")
    axes[2].grid(True, alpha=0.3)

    fig.suptitle("Clustering Quality Metrics by K", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "cluster_metrics.png")
    return fig


def plot_cluster_scatter(
    X_pca: np.ndarray,
    labels: np.ndarray,
    title: str = "Cluster Visualization (PCA 2D)",
) -> plt.Figure:
    """Scatter plot of PCA-reduced data coloured by cluster assignment.

    Parameters
    ----------
    X_pca : np.ndarray
        2D PCA-transformed coordinates.
    labels : np.ndarray
        Cluster labels.
    title : str
        Plot title.

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(X_pca[:, 0], X_pca[:, 1], c=labels, cmap="tab10",
                         alpha=0.6, s=8)
    ax.set_xlabel("Principal Component 1")
    ax.set_ylabel("Principal Component 2")
    ax.set_title(title)
    plt.colorbar(scatter, ax=ax, label="Cluster")
    save(fig, "cluster_scatter.png")
    return fig


def plot_cluster_radar(
    radar_data: pd.DataFrame,
    title: str = "Cluster Profiles (Normalized Feature Means)",
) -> plt.Figure:
    """Radar chart showing normalized per-cluster feature profiles.

    Parameters
    ----------
    radar_data : pd.DataFrame
        Rows = clusters, columns = features (values in [0, 1]).
    title : str
        Plot title.

    Returns
    -------
    plt.Figure
    """
    features = list(radar_data.columns)
    n_features = len(features)
    angles = np.linspace(0, 2 * np.pi, n_features, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw={"projection": "polar"})
    colors = plt.cm.tab10(np.linspace(0, 1, len(radar_data)))

    for i, (idx, row) in enumerate(radar_data.iterrows()):
        values = row.values.tolist()
        values += values[:1]
        ax.plot(angles, values, "o-", linewidth=2, color=colors[i],
                label=f"Cluster {int(idx)}", markersize=4)
        ax.fill(angles, values, alpha=0.1, color=colors[i])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(features, fontsize=9)
    ax.set_ylim(0, 1.1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.0))
    save(fig, "cluster_radar.png")
    return fig


# ------------------------------------------------------------------ Regression


def plot_residuals(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    model_name: str = "Model",
) -> plt.Figure:
    """Residual diagnostics: scatter (residuals vs predicted) and histogram.

    Parameters
    ----------
    y_true : np.ndarray
        Ground truth.
    y_pred : np.ndarray
        Predicted values.
    model_name : str
        Model identifier.

    Returns
    -------
    plt.Figure
    """
    residuals = y_true - y_pred
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    axes[0].scatter(y_pred, residuals, alpha=0.5, s=10, color="steelblue")
    axes[0].axhline(0, color="red", linestyle="--", linewidth=1.5)
    axes[0].set_xlabel("Predicted Yield")
    axes[0].set_ylabel("Residuals (Actual - Predicted)")
    axes[0].set_title(f"Residuals vs Predicted - {model_name}")

    axes[1].hist(residuals, bins=50, edgecolor="white", alpha=0.7, color="steelblue")
    axes[1].axvline(0, color="red", linestyle="--", linewidth=1.5)
    axes[1].axvline(residuals.mean(), color="orange", linestyle="--", linewidth=1.5,
                    label=f"Mean={residuals.mean():.2f}")
    axes[1].set_xlabel("Residuals")
    axes[1].set_title(f"Residual Distribution - {model_name}")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    safe_name = model_name.replace(" ", "_").lower()
    save(fig, f"residuals_{safe_name}.png")
    return fig


def plot_actual_vs_predicted(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    model_name: str = "Model",
) -> plt.Figure:
    """Scatter plot of actual vs predicted yield with identity line.

    Parameters
    ----------
    y_true : np.ndarray
        Ground truth.
    y_pred : np.ndarray
        Predictions.
    model_name : str
        Model identifier.

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(y_true, y_pred, alpha=0.3, s=10, color="steelblue")
    mn = min(y_true.min(), y_pred.min())
    mx = max(y_true.max(), y_pred.max())
    ax.plot([mn, mx], [mn, mx], "r--", linewidth=1.5, label="Perfect Prediction")
    ax.set_xlabel("Actual Yield")
    ax.set_ylabel("Predicted Yield")
    ax.set_title(f"Actual vs Predicted - {model_name}")
    ax.legend()
    safe_name = model_name.replace(" ", "_").lower()
    save(fig, f"actual_vs_predicted_{safe_name}.png")
    return fig


# -------------------------------------------------------------- Feature Importance


def plot_feature_importance(
    features: list[str],
    importances: np.ndarray,
    model_name: str = "Model",
    top_n: int = 20,
) -> plt.Figure:
    """Horizontal bar chart of feature importances.

    Parameters
    ----------
    features : list[str]
        Feature names.
    importances : np.ndarray
        Importance values.
    model_name : str
        Model identifier.
    top_n : int
        Show only top N features.

    Returns
    -------
    plt.Figure
    """
    indices = np.argsort(importances)[::-1][:top_n]
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(range(len(indices)), importances[indices], color="steelblue")
    ax.set_yticks(range(len(indices)))
    ax.set_yticklabels([features[i] for i in indices])
    ax.invert_yaxis()
    ax.set_xlabel("Importance")
    ax.set_title(f"Feature Importance (Top {top_n}) - {model_name}")
    fig.tight_layout()
    safe_name = model_name.replace(" ", "_").lower()
    save(fig, f"feature_importance_{safe_name}.png")
    return fig


# ---------------------------------------------------------------- Model Comparison


def plot_model_comparison(
    metrics: dict[str, dict[str, float]],
    metric_name: str = "r2",
) -> plt.Figure:
    """Grouped bar chart comparing models on a single metric.

    Parameters
    ----------
    metrics : dict
        {model_name: {metric_name: value}}.
    metric_name : str
        Metric to plot (r2, rmse, mae, mape).

    Returns
    -------
    plt.Figure
    """
    models = list(metrics.keys())
    values = [metrics[m].get(metric_name, 0) for m in models]
    colors = ["steelblue", "coral", "seagreen", "gold", "mediumpurple", "sienna"][:len(models)]
    fig, ax = plt.subplots(figsize=(max(8, len(models) * 2), 5))
    bars = ax.bar(models, values, color=colors, edgecolor="white")
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.002 * max(values),
                f"{val:.4f}", ha="center", fontweight="bold", fontsize=9)
    ax.set_ylabel(metric_name.upper())
    ax.set_title(f"Model Comparison - {metric_name.upper()}")
    ax.tick_params(axis="x", rotation=15)
    fig.tight_layout()
    save(fig, f"model_comparison_{metric_name}.png")
    return fig


def plot_learning_curves(
    model,
    X: pd.DataFrame,
    y: pd.Series,
    model_name: str = "Model",
    cv: int = 5,
) -> plt.Figure:
    """Plot learning curves: training and validation scores vs training size.

    Parameters
    ----------
    model : estimator
        Scikit-learn compatible model.
    X : pd.DataFrame
        Feature matrix.
    y : pd.Series
        Target.
    model_name : str
        Model identifier.
    cv : int
        Cross-validation folds.

    Returns
    -------
    plt.Figure
    """
    from sklearn.model_selection import learning_curve
    train_sizes, train_scores, val_scores = learning_curve(
        model, X, y, cv=cv, n_jobs=-1,
        train_sizes=np.linspace(0.1, 1.0, 10),
        scoring="r2",
    )
    train_mean = train_scores.mean(axis=1)
    train_std = train_scores.std(axis=1)
    val_mean = val_scores.mean(axis=1)
    val_std = val_scores.std(axis=1)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.fill_between(train_sizes, train_mean - train_std, train_mean + train_std,
                    alpha=0.2, color="steelblue")
    ax.fill_between(train_sizes, val_mean - val_std, val_mean + val_std,
                    alpha=0.2, color="coral")
    ax.plot(train_sizes, train_mean, "o-", color="steelblue", label="Training R²")
    ax.plot(train_sizes, val_mean, "o-", color="coral", label="Validation R²")
    ax.set_xlabel("Training Set Size")
    ax.set_ylabel("R² Score")
    ax.set_title(f"Learning Curves - {model_name}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    safe_name = model_name.replace(" ", "_").lower()
    save(fig, f"learning_curve_{safe_name}.png")
    return fig


def plot_feature_interaction(
    df: pd.DataFrame,
    feat_x: str,
    feat_y: str,
    target: str = "yield",
) -> plt.Figure:
    """Scatter plot of two features coloured by target yield.

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe with feature columns and target.
    feat_x : str
        X-axis feature.
    feat_y : str
        Y-axis feature.
    target : str
        Target column for colour coding.

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(df[feat_x], df[feat_y], c=df[target],
                         cmap="viridis", alpha=0.4, s=8)
    ax.set_xlabel(feat_x)
    ax.set_ylabel(feat_y)
    ax.set_title(f"{feat_x} vs {feat_y} (coloured by {target})")
    plt.colorbar(scatter, ax=ax, label=target)
    save(fig, f"interaction_{feat_x}_vs_{feat_y}.png")
    return fig


def plot_pca_variance(
    explained_variance: np.ndarray,
    cumulative_variance: np.ndarray | None = None,
    threshold: float = 0.95,
) -> plt.Figure:
    """Plot explained variance per PC and cumulative variance.

    Parameters
    ----------
    explained_variance : np.ndarray
        Per-component explained variance ratio.
    cumulative_variance : np.ndarray or None
        Cumulative variance ratio (auto-computed if None).
    threshold : float
        Variance threshold line.

    Returns
    -------
    plt.Figure
    """
    if cumulative_variance is None:
        cumulative_variance = np.cumsum(explained_variance)

    fig, ax1 = plt.subplots(figsize=(10, 5))
    n = len(explained_variance)
    x = range(1, n + 1)

    bars = ax1.bar(x, explained_variance, color="steelblue", alpha=0.6, label="Per Component")
    ax1.set_xlabel("Principal Component")
    ax1.set_ylabel("Explained Variance Ratio", color="steelblue")
    ax1.tick_params(axis="y", labelcolor="steelblue")

    ax2 = ax1.twinx()
    ax2.plot(x, cumulative_variance, "ro-", markersize=4, label="Cumulative")
    ax2.axhline(threshold, color="green", linestyle="--", label=f"{threshold:.0%} threshold")
    ax2.set_ylabel("Cumulative Variance Ratio", color="coral")
    ax2.tick_params(axis="y", labelcolor="coral")

    ax1.set_title("PCA Explained Variance")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower right")
    save(fig, "pca_variance.png")
    return fig
