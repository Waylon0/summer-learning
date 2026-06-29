# -*- coding: utf-8 -*-
"""
野生蓝莓产量预测 —— 全流程主脚本
运行: uv run python main.py
"""
import sys
import os
import matplotlib
matplotlib.use('Agg')  # 非交互后端，只保存图片不弹窗
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import (
    TRAIN_PATH, TEST_PATH, RANDOM_STATE, FIGURES_DIR, MODELS_DIR,
    FRUIT_FEATURES, TARGET,
)
from src.data.loader import load_train, load_test
from src.data.preprocessor import DataPreprocessor
from src.features.engineering import apply_pca
from src.models.clustering import BlueberryClustering
from src.models.linear_regression import BlueberryLinearRegression, compute_vif
from src.models.random_forest import BlueberryRandomForest
from src.models.evaluation import regression_metrics, cross_validate, compare_models
from src.visualization.plots import (
    plot_correlation_heatmap, plot_distribution, plot_elbow,
    plot_cluster_scatter, plot_residuals, plot_feature_importance,
    plot_model_comparison, plot_actual_vs_predicted,
)

os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)


def main():
    print("=" * 60)
    print("  野生蓝莓产量预测 —— 全流程分析")
    print("=" * 60)

    # ============================================================
    # 0. 加载数据
    # ============================================================
    train = load_train()
    test = load_test()
    print(f"\n训练集: {train.shape[0]} 行, {train.shape[1]} 列")
    print(f"测试集: {test.shape[0]} 行, {test.shape[1]} 列")

    # ============================================================
    # 1. 数据预处理
    # ============================================================
    print("\n[1/6] 数据预处理...")
    preprocessor = DataPreprocessor()
    X_train, X_val, y_train, y_val = preprocessor.pipeline(train)
    feature_names = X_train.columns.tolist()
    print(f"  特征数: {len(feature_names)}")
    print(f"  训练集: {X_train.shape[0]} 行")
    print(f"  验证集: {X_val.shape[0]} 行")

    # ============================================================
    # 2. EDA 可视化
    # ============================================================
    print("\n[2/6] EDA 可视化...")
    df_full = pd.concat([X_train, y_train.rename(TARGET)], axis=1)
    plot_correlation_heatmap(df_full, "蓝莓各变量相关性热力图")

    # 打印与 yield 的相关系数
    corr = df_full.corr()[TARGET].drop(TARGET).sort_values(key=abs, ascending=False)
    print("  各变量与 yield 的相关系数:")
    for col, val in corr.items():
        bar = "█" * int(abs(val) * 20)
        print(f"    {col:25s}: {val:+.3f}  {bar}")

    # ============================================================
    # 3. K-Means 聚类分析
    # ============================================================
    print("\n[3/6] K-Means 聚类分析...")
    cluster = BlueberryClustering()
    results = cluster.find_optimal_k(X_train)
    best_k = results["best_k"]
    print(f"  最优 K = {best_k}")
    print(f"  轮廓系数 = {results['optimal_metrics']['silhouette']:.4f}")

    plot_elbow(results["inertias"], results["k_range"], optimal_k=best_k)
    cluster.fit(X_train, k=best_k)
    labels = cluster.get_predictions()

    # PCA 降维可视化
    X_pca, pca, explained = apply_pca(X_train, n_components=2)
    plot_cluster_scatter(X_pca.values, labels,
                         f"K-Means 聚类结果 (K={best_k}, PCA降维)")

    # 聚类群组解读
    print("\n  ── 聚类群组解读 ──")
    for i in range(best_k):
        mask = labels == i
        n = mask.sum()
        y_mean = y_train[mask].mean()
        print(f"\n  簇 {i} (n={n})  平均 yield = {y_mean:+.2f}")
        # 计算该簇在各特征上的均值偏离
        for col in X_train.columns:
            col_idx = list(X_train.columns).index(col)
            dev = X_train.iloc[:, col_idx][mask].mean()
            if abs(dev) > 0.3:
                direction = "↑" if dev > 0 else "↓"
                print(f"    {direction} {col}: {dev:+.2f}")

    # ============================================================
    # 4. 线性回归（带 vs 不带果实特征）
    # ============================================================
    print("\n[4/6] 线性回归（果实特征对照）...")
    no_fruit_features = [c for c in feature_names if c not in FRUIT_FEATURES]
    all_metrics = {}

    for fs_name, fs_cols in [
        ("全部特征", feature_names),
        ("排除果实特征", no_fruit_features),
    ]:
        Xt = X_train[fs_cols]
        Xv = X_val[fs_cols]

        # VIF 诊断
        vif_df = compute_vif(Xt)
        high_vif_count = len(vif_df[vif_df["VIF"] > 10])

        # PCA 降维
        Xt_pca, pca_model, explained_var = apply_pca(Xt, variance_threshold=0.95)
        Xv_pca = pd.DataFrame(
            pca_model.transform(Xv),
            columns=[f"PC{i+1}" for i in range(Xt_pca.shape[1])],
        )

        print(f"\n  {fs_name} ({len(fs_cols)} 特征, VIF>10: {high_vif_count}个, PCA→{Xt_pca.shape[1]}维)")

        # Ridge
        lr = BlueberryLinearRegression()
        lr.fit_ridge(Xt_pca, y_train, alpha=1.0)
        y_pred = lr.predict(Xv_pca)
        m = regression_metrics(y_val.values, y_pred)
        all_metrics[f"Ridge-{fs_name}"] = m
        print(f"    Ridge  R²={m['r2']:.4f}  RMSE={m['rmse']:.1f}  MAE={m['mae']:.1f}")

        # Lasso
        lr.fit_lasso(Xt_pca, y_train, alpha=0.1)
        y_pred_l = lr.predict(Xv_pca)
        m_l = regression_metrics(y_val.values, y_pred_l)
        all_metrics[f"Lasso-{fs_name}"] = m_l
        print(f"    Lasso  R²={m_l['r2']:.4f}  RMSE={m_l['rmse']:.1f}  MAE={m_l['mae']:.1f}")

        if fs_name == "全部特征":
            plot_residuals(y_val.values, y_pred)
            plot_actual_vs_predicted(y_val.values, y_pred, "Ridge回归")

    print("\n  ★ 果实特征(fruitset/fruitmass/seeds)与yield高度共线(R>0.8),")
    print("    排除后R²会下降，但模型更合理——只用可干预变量做预测。")

    # ============================================================
    # 5. 随机森林
    # ============================================================
    print("\n[5/6] 随机森林...")
    Xt_nf = X_train[no_fruit_features]
    Xv_nf = X_val[no_fruit_features]

    rf = BlueberryRandomForest()
    rf.fit(Xt_nf, y_train, n_estimators=200)
    y_pred_rf = rf.predict(Xv_nf)
    rf_m = regression_metrics(y_val.values, y_pred_rf)
    all_metrics["随机森林"] = rf_m
    print(f"  R²={rf_m['r2']:.4f}  RMSE={rf_m['rmse']:.1f}  MAE={rf_m['mae']:.1f}")

    # 特征重要性
    imp_df = rf.get_feature_importance(no_fruit_features)
    print("\n  特征重要性 Top 5:")
    for _, row in imp_df.head(5).iterrows():
        print(f"    {row['feature']:25s}: {row['importance']:.4f}")

    plot_feature_importance(imp_df["feature"].tolist(), imp_df["importance"].values)
    plot_residuals(y_val.values, y_pred_rf)
    plot_actual_vs_predicted(y_val.values, y_pred_rf, "随机森林")

    # ============================================================
    # 6. 模型对比 + 测试集预测
    # ============================================================
    print("\n[6/6] 模型对比与测试集预测...")

    print(f"\n  {'模型':35s}  {'R²':>6s}  {'RMSE':>8s}  {'MAE':>8s}")
    print("  " + "-" * 61)
    for name, m in all_metrics.items():
        print(f"  {name:35s}  {m['r2']:>6.4f}  {m['rmse']:>8.1f}  {m['mae']:>8.1f}")

    plot_model_comparison(all_metrics, "r2")
    plot_model_comparison(all_metrics, "rmse")

    # 测试集预测（用随机森林 + 排除果实特征）
    test_clean = preprocessor.clean(test)
    X_te, _ = preprocessor.split_features_target(test_clean)
    X_te_scaled = preprocessor.scale(X_te, fit=False)
    X_te_nf = X_te_scaled[no_fruit_features]
    test_pred = rf.predict(X_te_nf)

    submission = pd.DataFrame({"id": range(len(test_pred)), "yield": test_pred})
    sub_path = os.path.join(MODELS_DIR, "test_predictions.csv")
    submission.to_csv(sub_path, index=False)
    print(f"\n  测试集预测已保存: {sub_path}")
    print(f"  预测均值={test_pred.mean():.1f}, 范围=[{test_pred.min():.1f}, {test_pred.max():.1f}]")

    print("\n" + "=" * 60)
    print("  全流程分析完成！")
    print(f"  图表: {FIGURES_DIR}/")
    print(f"  预测: {sub_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
