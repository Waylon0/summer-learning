import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd
import os

matplotlib.rcParams["font.sans-serif"] = ["SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

from src.config import FIGURES_DIR

os.makedirs(FIGURES_DIR, exist_ok=True)


def save(fig: plt.Figure, name: str):
    fig.savefig(os.path.join(FIGURES_DIR, name), dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_correlation_heatmap(df: pd.DataFrame, title: str = "各变量相关性热力图"):
    corr = df.corr()
    mask = np.triu(np.ones_like(corr, dtype=bool))
    fig, ax = plt.subplots(figsize=(14, 12))
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap="RdBu_r",
                center=0, square=True, linewidths=0.5, ax=ax)
    ax.set_title(title, fontsize=14, fontweight="bold")
    save(fig, "correlation_heatmap.png")
    return fig


def plot_distribution(df: pd.DataFrame, columns: list[str], rows: int = None, cols: int = 4):
    n = len(columns)
    if rows is None:
        rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3))
    axes = axes.flatten()
    for i, col in enumerate(columns):
        ax = axes[i]
        ax.hist(df[col].dropna(), bins=50, edgecolor="white", alpha=0.7, color="steelblue")
        ax.set_title(col, fontsize=9)
    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)
    fig.suptitle("各特征分布直方图", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "feature_distributions.png")
    return fig


def plot_elbow(inertias: list[float], k_range: range, optimal_k: int = None):
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(k_range, inertias, "bo-", markersize=6)
    if optimal_k is not None:
        ax.axvline(optimal_k, color="red", linestyle="--", label=f"最优 K={optimal_k}")
        ax.legend()
    ax.set_xlabel("聚类数 K")
    ax.set_ylabel("惯性 (Inertia)")
    ax.set_title("肘部法则确定最优 K 值")
    save(fig, "elbow_method.png")
    return fig


def plot_cluster_scatter(X_pca: np.ndarray, labels: np.ndarray, title: str = "聚类结果 PCA 可视化"):
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(X_pca[:, 0], X_pca[:, 1], c=labels, cmap="tab10", alpha=0.6, s=10)
    ax.set_xlabel("主成分 1")
    ax.set_ylabel("主成分 2")
    ax.set_title(title)
    plt.colorbar(scatter, ax=ax, label="簇编号")
    save(fig, "cluster_scatter.png")
    return fig


def plot_residuals(y_true: np.ndarray, y_pred: np.ndarray):
    residuals = y_true - y_pred
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].scatter(y_pred, residuals, alpha=0.5, s=10, color="steelblue")
    axes[0].axhline(0, color="red", linestyle="--")
    axes[0].set_xlabel("预测值")
    axes[0].set_ylabel("残差")
    axes[0].set_title("残差 vs 预测值")
    axes[1].hist(residuals, bins=50, edgecolor="white", alpha=0.7, color="steelblue")
    axes[1].axvline(0, color="red", linestyle="--")
    axes[1].set_xlabel("残差")
    axes[1].set_title("残差分布直方图")
    fig.tight_layout()
    save(fig, "residual_analysis.png")
    return fig


def plot_feature_importance(features: list[str], importances: np.ndarray, model_name: str = "随机森林"):
    indices = np.argsort(importances)[::-1]
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(range(len(indices)), importances[indices], color="steelblue")
    ax.set_yticks(range(len(indices)))
    ax.set_yticklabels([features[i] for i in indices])
    ax.invert_yaxis()
    ax.set_xlabel("重要性")
    ax.set_title(f"特征重要性排名 - {model_name}")
    fig.tight_layout()
    save(fig, "feature_importance.png")
    return fig


def plot_model_comparison(metrics: dict[str, dict[str, float]], metric_name: str = "r2"):
    models = list(metrics.keys())
    values = [metrics[m].get(metric_name, 0) for m in models]
    colors = ["steelblue", "coral", "seagreen", "gold"][:len(models)]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(models, values, color=colors, edgecolor="white")
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f"{val:.4f}", ha="center", fontweight="bold")
    ax.set_ylabel(metric_name.upper())
    ax.set_title(f"模型对比 - {metric_name.upper()}")
    save(fig, "model_comparison.png")
    return fig


def plot_actual_vs_predicted(y_true: np.ndarray, y_pred: np.ndarray, model_name: str = "Model"):
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(y_true, y_pred, alpha=0.3, s=10, color="steelblue")
    mn = min(y_true.min(), y_pred.min())
    mx = max(y_true.max(), y_pred.max())
    ax.plot([mn, mx], [mn, mx], "r--", linewidth=1.5)
    ax.set_xlabel("真实产量")
    ax.set_ylabel("预测产量")
    ax.set_title(f"真实值 vs 预测值 - {model_name}")
    save(fig, f"actual_vs_predicted_{model_name}.png")
    return fig
