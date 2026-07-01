"""可视化函数：相关性热力图、聚类可视化、模型诊断、对比图表。"""

import logging
import os
import warnings

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# ---- 自动检测并使用系统中支持中文的字体 ----
_CJK_CANDIDATES = [
    "SimHei",                # Windows 黑体
    "Microsoft YaHei",       # Windows 微软雅黑
    "STHeiti",               # macOS
    "PingFang SC",           # macOS
    "Heiti SC",              # macOS
    "WenQuanYi Micro Hei",   # Linux
    "WenQuanYi Zen Hei",     # Linux
    "Noto Sans CJK SC",      # Linux
    "Noto Sans SC",          # Linux
    "AR PL UMing CN",        # Linux
]
_FALLBACK_FONT = "DejaVu Sans"


def _setup_chinese_font() -> str:
    """检测并激活系统中支持中文的字体。

    若找到中文字体则使用，否则静默所有 UserWarning 避免 Glyph 刷屏。
    """
    # 将系统字体目录加入 matplotlib 搜索路径
    _extra_dirs = []
    if os.name == "nt":
        _windir = os.environ.get("WINDIR", "C:\\Windows")
        _d = os.path.join(_windir, "Fonts")
        if os.path.isdir(_d):
            _extra_dirs.append(_d)
    elif os.sys.platform == "darwin":
        _extra_dirs.extend(["/System/Library/Fonts", "/Library/Fonts"])

    for _d in _extra_dirs:
        for _f in os.listdir(_d):
            if _f.lower().endswith((".ttf", ".ttc", ".otf")):
                try:
                    fm.fontManager.addfont(os.path.join(_d, _f))
                except Exception:
                    pass

    # 扫描已知中文字体
    available = {f.name for f in fm.fontManager.ttflist}
    chosen = None
    for name in _CJK_CANDIDATES:
        if name in available:
            chosen = name
            break

    if chosen:
        matplotlib.rcParams["font.sans-serif"] = [chosen, _FALLBACK_FONT]
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["axes.unicode_minus"] = False
        return chosen
    else:
        matplotlib.rcParams["font.sans-serif"] = [_FALLBACK_FONT]
        matplotlib.rcParams["axes.unicode_minus"] = False
        # 全局静默 UserWarning，避免每个图表都输出 Glyph 缺字警告
        warnings.filterwarnings("ignore", category=UserWarning)
        return _FALLBACK_FONT


_setup_chinese_font()

from src.config import FIGURES_DIR

os.makedirs(FIGURES_DIR, exist_ok=True)


def save(fig: plt.Figure, name: str) -> str:
    """保存图表到 outputs/figures/ 并关闭。

    Parameters
    ----------
    fig : plt.Figure
        Matplotlib 图表对象。
    name : str
        文件名（如 'correlation_heatmap.png'）。

    Returns
    -------
    str
        保存文件的完整路径。
    """
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ------------------------------------------------------------------ 相关性分析


def plot_correlation_heatmap(
    df: pd.DataFrame,
    title: str = "特征相关性热力图",
    mask_upper: bool = True,
) -> plt.Figure:
    """绘制上三角相关性热力图。

    Parameters
    ----------
    df : pd.DataFrame
        包含特征（和可选目标）的数据框。
    title : str
        图表标题。
    mask_upper : bool
        是否遮蔽上三角避免冗余。

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


# --------------------------------------------------------------- 分布可视化


def plot_distribution(
    df: pd.DataFrame,
    columns: list[str],
    rows: int | None = None,
    cols: int = 4,
) -> plt.Figure:
    """绘制多列特征的直方图网格。

    Parameters
    ----------
    df : pd.DataFrame
        包含特征列的数据框。
    columns : list[str]
        需要绘制的列名。
    rows : int or None
        行数（None 表示自动计算）。
    cols : int
        列数。

    Returns
    -------
    plt.Figure
    """
    n = len(columns)
    if rows is None:
        rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3))
    if n == 1:
        axes = np.array([axes])
    else:
        axes = axes.flatten()
    for i, col in enumerate(columns):
        ax = axes[i]
        ax.hist(df[col].dropna(), bins=50, edgecolor="white", alpha=0.7, color="steelblue")
        ax.set_title(col, fontsize=9)
        ax.set_xlabel("")
    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)
    fig.suptitle("特征分布直方图", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "feature_distributions.png")
    return fig


# ------------------------------------------------------------------ 聚类可视化


def plot_elbow(
    inertias: list[float],
    k_range: range,
    optimal_k: int | None = None,
) -> plt.Figure:
    """绘制肘部法则曲线，可选标注最优 K。

    Parameters
    ----------
    inertias : list[float]
        各 K 对应的惯性值。
    k_range : range
        K 的取值序列。
    optimal_k : int or None
        需要高亮标注的最优 K。

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(list(k_range), inertias, "bo-", markersize=6)
    if optimal_k is not None:
        ax.axvline(optimal_k, color="red", linestyle="--", label=f"最优 K={optimal_k}")
        ax.legend()
    ax.set_xlabel("聚类数 K")
    ax.set_ylabel("惯性（WCSS）")
    ax.set_title("肘部法则确定最优 K 值")
    ax.grid(True, alpha=0.3)
    save(fig, "elbow_method.png")
    return fig


def plot_cluster_metrics(results: dict) -> plt.Figure:
    """绘制轮廓系数、Davies-Bouldin 指数和 Calinski-Harabasz 分数随 K 的变化。

    Parameters
    ----------
    results : dict
        BlueberryClustering.find_optimal_k() 的输出。

    Returns
    -------
    plt.Figure
    """
    k_range = results["k_range"]
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    axes[0].plot(k_range, results["silhouette_scores"], "bo-", markersize=6)
    best_k = results["best_k"]
    axes[0].axvline(best_k, color="red", linestyle="--")
    axes[0].set_title("轮廓系数（越高越好）")
    axes[0].set_xlabel("K")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(k_range, results["davies_bouldin_scores"], "go-", markersize=6)
    axes[1].axvline(best_k, color="red", linestyle="--")
    axes[1].set_title("Davies-Bouldin 指数（越低越好）")
    axes[1].set_xlabel("K")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(k_range, results["calinski_harabasz_scores"], "mo-", markersize=6)
    axes[2].axvline(best_k, color="red", linestyle="--")
    axes[2].set_title("Calinski-Harabasz 分数（越高越好）")
    axes[2].set_xlabel("K")
    axes[2].grid(True, alpha=0.3)

    fig.suptitle("聚类质量指标随 K 值变化", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "cluster_metrics.png")
    return fig


def plot_cluster_scatter(
    X_pca: np.ndarray,
    labels: np.ndarray,
    title: str = "聚类可视化（PCA 二维投影）",
) -> plt.Figure:
    """将 PCA 降维后的数据按聚类着色绘制散点图。

    Parameters
    ----------
    X_pca : np.ndarray
        PCA 二维坐标。
    labels : np.ndarray
        聚类标签。
    title : str
        图表标题。

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(X_pca[:, 0], X_pca[:, 1], c=labels, cmap="tab10",
                         alpha=0.6, s=8)
    ax.set_xlabel("第一主成分 (PC1)")
    ax.set_ylabel("第二主成分 (PC2)")
    ax.set_title(title)
    plt.colorbar(scatter, ax=ax, label="聚类")
    save(fig, "cluster_scatter.png")
    return fig


def plot_cluster_radar(
    radar_data: pd.DataFrame,
    title: str = "聚类画像（归一化特征均值雷达图）",
) -> plt.Figure:
    """雷达图展示各聚类在特征维度上的归一化均值分布。

    Parameters
    ----------
    radar_data : pd.DataFrame
        行=聚类，列=特征（取值范围 [0, 1]）。
    title : str
        图表标题。

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
                label=f"聚类 {int(idx)}", markersize=4)
        ax.fill(angles, values, alpha=0.1, color=colors[i])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(features, fontsize=9)
    ax.set_ylim(0, 1.1)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.0))
    save(fig, "cluster_radar.png")
    return fig


# ------------------------------------------------------------------ 回归诊断


def plot_residuals(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    model_name: str = "模型",
) -> plt.Figure:
    """残差诊断图：残差 vs 预测值散点图 + 残差分布直方图。

    Parameters
    ----------
    y_true : np.ndarray
        真实值。
    y_pred : np.ndarray
        预测值。
    model_name : str
        模型名称。

    Returns
    -------
    plt.Figure
    """
    residuals = y_true - y_pred
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    axes[0].scatter(y_pred, residuals, alpha=0.5, s=10, color="steelblue")
    axes[0].axhline(0, color="red", linestyle="--", linewidth=1.5)
    axes[0].set_xlabel("预测产量")
    axes[0].set_ylabel("残差（真实值 - 预测值）")
    axes[0].set_title(f"残差 vs 预测值 - {model_name}")

    axes[1].hist(residuals, bins=50, edgecolor="white", alpha=0.7, color="steelblue")
    axes[1].axvline(0, color="red", linestyle="--", linewidth=1.5)
    axes[1].axvline(residuals.mean(), color="orange", linestyle="--", linewidth=1.5,
                    label=f"均值={residuals.mean():.2f}")
    axes[1].set_xlabel("残差")
    axes[1].set_title(f"残差分布 - {model_name}")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    safe_name = model_name.replace(" ", "_").lower()
    save(fig, f"residuals_{safe_name}.png")
    return fig


def plot_actual_vs_predicted(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    model_name: str = "模型",
) -> plt.Figure:
    """绘制真实值 vs 预测值散点图，含理想预测线。

    Parameters
    ----------
    y_true : np.ndarray
        真实值。
    y_pred : np.ndarray
        预测值。
    model_name : str
        模型名称。

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(y_true, y_pred, alpha=0.3, s=10, color="steelblue")
    mn = min(y_true.min(), y_pred.min())
    mx = max(y_true.max(), y_pred.max())
    ax.plot([mn, mx], [mn, mx], "r--", linewidth=1.5, label="理想预测")
    ax.set_xlabel("真实产量")
    ax.set_ylabel("预测产量")
    ax.set_title(f"真实值 vs 预测值 - {model_name}")
    ax.legend()
    safe_name = model_name.replace(" ", "_").lower()
    save(fig, f"actual_vs_predicted_{safe_name}.png")
    return fig


# -------------------------------------------------------------- 特征重要性


def plot_feature_importance(
    features: list[str],
    importances: np.ndarray,
    model_name: str = "模型",
    top_n: int = 20,
) -> plt.Figure:
    """水平条形图展示特征重要性排名。

    Parameters
    ----------
    features : list[str]
        特征名列表。
    importances : np.ndarray
        重要性数值。
    model_name : str
        模型名称。
    top_n : int
        仅展示 Top N 个特征。

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
    ax.set_xlabel("重要性")
    ax.set_title(f"特征重要性 (Top {top_n}) - {model_name}")
    fig.tight_layout()
    safe_name = model_name.replace(" ", "_").lower()
    save(fig, f"feature_importance_{safe_name}.png")
    return fig


# ---------------------------------------------------------------- 模型对比


def plot_model_comparison(
    metrics: dict[str, dict[str, float]],
    metric_name: str = "r2",
) -> plt.Figure:
    """柱状图对比多个模型在某一指标上的表现。

    Parameters
    ----------
    metrics : dict
        {模型名称: {指标名: 值}}。
    metric_name : str
        要绘制的指标名（r2、rmse、mae、mape）。

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
    ax.set_title(f"模型对比 - {metric_name.upper()}")
    ax.tick_params(axis="x", rotation=15)
    fig.tight_layout()
    save(fig, f"model_comparison_{metric_name}.png")
    return fig


def plot_learning_curves(
    model,
    X: pd.DataFrame,
    y: pd.Series,
    model_name: str = "模型",
    cv: int = 5,
) -> plt.Figure:
    """学习曲线：训练得分和验证得分随训练集大小的变化。

    Parameters
    ----------
    model : estimator
        sklearn 兼容模型。
    X : pd.DataFrame
        特征矩阵。
    y : pd.Series
        目标向量。
    model_name : str
        模型名称。
    cv : int
        交叉验证折数。

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
    ax.plot(train_sizes, train_mean, "o-", color="steelblue", label="训练集 R²")
    ax.plot(train_sizes, val_mean, "o-", color="coral", label="验证集 R²")
    ax.set_xlabel("训练集大小")
    ax.set_ylabel("R² 得分")
    ax.set_title(f"学习曲线 - {model_name}")
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
    """两个特征对产量的交互散点图。

    Parameters
    ----------
    df : pd.DataFrame
        包含特征和产量的数据框。
    feat_x : str
        X 轴特征。
    feat_y : str
        Y 轴特征。
    target : str
        颜色映射的目标列。

    Returns
    -------
    plt.Figure
    """
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(df[feat_x], df[feat_y], c=df[target],
                         cmap="viridis", alpha=0.4, s=8)
    ax.set_xlabel(feat_x)
    ax.set_ylabel(feat_y)
    ax.set_title(f"{feat_x} vs {feat_y}（颜色=产量）")
    plt.colorbar(scatter, ax=ax, label=target)
    save(fig, f"interaction_{feat_x}_vs_{feat_y}.png")
    return fig


def plot_pca_variance(
    explained_variance: np.ndarray,
    cumulative_variance: np.ndarray | None = None,
    threshold: float = 0.95,
) -> plt.Figure:
    """PCA 各主成分解释方差比及累计方差比曲线。

    Parameters
    ----------
    explained_variance : np.ndarray
        各主成分解释方差比数组。
    cumulative_variance : np.ndarray or None
        累计方差比（若为 None 则自动计算）。
    threshold : float
        方差保留阈值线。

    Returns
    -------
    plt.Figure
    """
    if cumulative_variance is None:
        cumulative_variance = np.cumsum(explained_variance)

    fig, ax1 = plt.subplots(figsize=(10, 5))
    n = len(explained_variance)
    x = range(1, n + 1)

    ax1.bar(x, explained_variance, color="steelblue", alpha=0.6, label="各成分方差比")
    ax1.set_xlabel("主成分")
    ax1.set_ylabel("解释方差比例", color="steelblue")
    ax1.tick_params(axis="y", labelcolor="steelblue")

    ax2 = ax1.twinx()
    ax2.plot(x, cumulative_variance, "ro-", markersize=4, label="累计方差比")
    ax2.axhline(threshold, color="green", linestyle="--", label=f"{threshold:.0%} 阈值线")
    ax2.set_ylabel("累计方差比例", color="coral")
    ax2.tick_params(axis="y", labelcolor="coral")

    ax1.set_title("PCA 主成分解释方差分析")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower right")
    save(fig, "pca_variance.png")
    return fig


# ---------------------------------------------------------- 因果链与中间变量分析


def plot_env_fruit_importance(
    env_importance: dict[str, pd.DataFrame],
    top_n: int = 8,
) -> plt.Figure:
    """并排条形图：环境因素对各果实指标（fruitset/fruitmass/seeds）的影响重要性。

    Parameters
    ----------
    env_importance : dict
        {fruit_name: importance_dataframe}, 来自 IntermediateAnalyzer。
    top_n : int
        每个子图展示 Top N 个环境特征。

    Returns
    -------
    plt.Figure
    """
    n_fruits = len(env_importance)
    fig, axes = plt.subplots(1, n_fruits, figsize=(6 * n_fruits, 6))
    if n_fruits == 1:
        axes = [axes]

    colors = ["steelblue", "coral", "seagreen"]
    for idx, (fruit, imp) in enumerate(env_importance.items()):
        ax = axes[idx]
        top = imp.head(top_n).iloc[::-1]  # 翻转使最大的在顶部
        ax.barh(range(len(top)), top["importance"].values, color=colors[idx % len(colors)])
        ax.set_yticks(range(len(top)))
        ax.set_yticklabels(top["feature"].values, fontsize=9)
        ax.set_xlabel("重要性")
        ax.set_title(f"环境因素 → {fruit}")

    fig.suptitle("环境因素对果实发育指标的影响", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "env_to_fruit_importance.png")
    return fig


def plot_env_only_feature_importance(
    importance: pd.DataFrame,
    model_name: str = "随机森林（仅环境）",
    top_n: int = 15,
) -> plt.Figure:
    """纯环境因素 → 产量的特征重要性水平条形图。

    Parameters
    ----------
    importance : pd.DataFrame
        特征重要性表（feature + importance 列）。
    model_name : str
        模型名称。
    top_n : int
        展示 Top N 个特征。

    Returns
    -------
    plt.Figure
    """
    indices = np.argsort(importance["importance"].values)[::-1][:top_n]
    top = importance.iloc[indices].iloc[::-1]

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(range(len(top)), top["importance"].values, color="steelblue")
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(top["feature"].values)
    ax.invert_yaxis()
    ax.set_xlabel("重要性")
    ax.set_title(f"纯环境因素 → 产量 特征重要性 - {model_name}")
    fig.tight_layout()
    save(fig, "env_only_feature_importance.png")
    return fig


def plot_env_vs_full_comparison(
    env_metrics: dict,
    full_metrics: dict,
    env_cv: dict | None = None,
    full_cv: dict | None = None,
) -> plt.Figure:
    """对比纯环境模型与全模型的 R² 和 CV R²。

    Parameters
    ----------
    env_metrics : dict
        纯环境模型指标。
    full_metrics : dict
        全模型指标。
    env_cv : dict or None
        纯环境模型交叉验证结果。
    full_cv : dict or None
        全模型交叉验证结果。

    Returns
    -------
    plt.Figure
    """
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # 左图：R² 对比
    models = ["纯环境模型", "全模型（含果实指标）"]
    r2_values = [env_metrics.get("r2", 0), full_metrics.get("r2", 0)]
    colors = ["steelblue", "coral"]
    axes[0].bar(models, r2_values, color=colors, edgecolor="white")
    for i, v in enumerate(r2_values):
        axes[0].text(i, v + 0.01, f"{v:.4f}", ha="center", fontweight="bold")
    axes[0].set_ylabel("R²")
    axes[0].set_title("验证集 R² 对比")
    axes[0].set_ylim(0, max(r2_values) * 1.15)

    # 右图：CV R² 对比
    if env_cv and full_cv:
        cv_models = ["纯环境模型", "全模型"]
        cv_values = [env_cv.get("cv_mean", 0), full_cv.get("cv_mean", 0)]
        cv_stds = [env_cv.get("cv_std", 0), full_cv.get("cv_std", 0)]
        axes[1].bar(cv_models, cv_values, yerr=cv_stds, color=colors,
                    edgecolor="white", capsize=10, error_kw={"linewidth": 2})
        for i, (v, s) in enumerate(zip(cv_values, cv_stds)):
            axes[1].text(i, v + s + 0.005, f"{v:.4f}±{s:.4f}",
                         ha="center", fontsize=9, fontweight="bold")
        axes[1].set_ylabel("CV R²")
        axes[1].set_title("5 折交叉验证 R² 对比")

    fig.suptitle("纯环境模型 vs 全模型：果实指标的中介效应",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    save(fig, "env_vs_full_comparison.png")
    return fig


def plot_env_factor_grouped_importance(
    importance: pd.DataFrame,
) -> plt.Figure:
    """按因素大类（温度/降雨/蜂群/克隆株）汇总纯环境模型的影响力占比饼图。

    Parameters
    ----------
    importance : pd.DataFrame
        环境特征重要性表。

    Returns
    -------
    plt.Figure
    """
    from src.config import BEE_FEATURES, UPPER_TEMP_FEATURES, LOWER_TEMP_FEATURES, RAIN_FEATURES

    groups = {
        "克隆株大小": ["clonesize"],
        "蜂群密度": BEE_FEATURES,
        "最高温带温度": UPPER_TEMP_FEATURES,
        "最低温带温度": LOWER_TEMP_FEATURES,
        "降雨": RAIN_FEATURES,
    }

    grouped = {}
    for group_name, feats in groups.items():
        grouped[group_name] = importance.set_index("feature").loc[feats]["importance"].sum()

    total = sum(grouped.values())
    if total > 0:
        grouped = {k: v / total for k, v in grouped.items()}

    # 合并温度
    temp_total = grouped.get("最高温带温度", 0) + grouped.get("最低温带温度", 0)
    grouped_merged = {
        "温度因素": temp_total,
        "蜂群密度": grouped.get("蜂群密度", 0),
        "降雨": grouped.get("降雨", 0),
        "克隆株大小": grouped.get("克隆株大小", 0),
    }

    fig, ax = plt.subplots(figsize=(8, 8))
    labels = list(grouped_merged.keys())
    sizes = list(grouped_merged.values())
    colors_pie = ["coral", "gold", "steelblue", "seagreen", "mediumpurple"][:len(labels)]

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.1f%%",
        colors=colors_pie, startangle=90,
        textprops={"fontsize": 11},
    )
    for at in autotexts:
        at.set_fontweight("bold")
    ax.set_title("纯环境因素 → 产量 影响力占比", fontsize=14, fontweight="bold")
    save(fig, "env_factor_influence_pie.png")
    return fig
