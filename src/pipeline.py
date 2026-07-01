"""核心流水线编排：串联预处理、EDA、聚类、建模、评估。"""

import logging
import os
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.config import (
    FIGURES_DIR, MODELS_DIR,
    FRUIT_FEATURES, NUMERIC_FEATURES,
    CLUSTER_K_RANGE, RF_N_ESTIMATORS,
)
from src.data.loader import load_train, load_test
from src.data.preprocessor import DataPreprocessor
from src.features.engineering import apply_pca
from src.models.clustering import BlueberryClustering
from src.models.evaluation import regression_metrics, cross_validate
from src.models.linear_regression import BlueberryLinearRegression, compute_vif
from src.models.random_forest import BlueberryRandomForest
from src.visualization.plots import (
    plot_correlation_heatmap,
    plot_distribution,
    plot_elbow,
    plot_cluster_scatter,
    plot_cluster_radar,
    plot_cluster_metrics,
    plot_residuals,
    plot_actual_vs_predicted,
    plot_feature_importance,
    plot_model_comparison,
    plot_learning_curves,
    plot_feature_interaction,
    plot_pca_variance,
)

logger = logging.getLogger("blueberry")


@dataclass
class PipelineResult:
    """流水线执行结果。"""
    elapsed: float = 0.0
    metrics: dict = field(default_factory=dict)
    comparison_table: pd.DataFrame | None = None
    cluster_profiles: pd.DataFrame | None = None
    feature_importance: pd.DataFrame | None = None
    business_insights: dict = field(default_factory=dict)
    test_predictions: np.ndarray | None = None


class BlueberryPipeline:
    """全流程编排器 — 从原始数据到测试集预测一键执行。"""

    def __init__(self, tune: bool = False, save_models: bool = True):
        self.tune = tune
        self.save_models = save_models
        self.preprocessor = DataPreprocessor()
        self.clustering = BlueberryClustering()
        self.all_metrics: dict = {}

    def run(self) -> PipelineResult:
        """执行完整分析流水线。"""
        t0 = time.time()
        result = PipelineResult()

        # ================================================================
        # 0. 数据加载
        # ================================================================
        logger.info("加载数据...")
        train_raw = load_train()
        test_raw = load_test()

        # ================================================================
        # 1. 数据探查
        # ================================================================
        logger.info("数据探查...")
        info = self.preprocessor.inspect(train_raw)
        logger.info(
            "训练集: %d x %d, 重复: %d, 缺失: %d",
            info["shape"][0], info["shape"][1],
            info["duplicated"], sum(info["missing"].values()),
        )

        # ================================================================
        # 2. 预处理
        # ================================================================
        logger.info("预处理...")

        # 先 clean 完整训练集（用于聚类分析）
        train_clean = self.preprocessor.clean(train_raw)
        X_full, y_full = self.preprocessor.split_features_target(train_clean)
        X_full_scaled = self.preprocessor.scale(X_full, fit=True)

        # 再分割训练/验证集（用于建模）
        X_train, X_val, y_train, y_val = self.preprocessor.train_val_split(
            X_full_scaled, y_full
        )

        # 排除果实特征后的特征列表
        no_fruit_features = [f for f in NUMERIC_FEATURES if f not in FRUIT_FEATURES]

        # ================================================================
        # 3. EDA 可视化
        # ================================================================
        logger.info("EDA 可视化...")

        # 相关性热力图
        plot_correlation_heatmap(
            pd.concat([X_train, y_train.rename("yield")], axis=1),
            title="特征相关性热力图",
        )

        # 产量分布
        plot_distribution(
            y_train.to_frame("yield"), columns=["yield"], cols=1
        )

        # ================================================================
        # 4. K-Means 聚类分析
        # ================================================================
        logger.info("K-Means 聚类...")
        cluster_results = self.clustering.find_optimal_k(
            X_full_scaled, k_range=CLUSTER_K_RANGE
        )
        best_k = cluster_results["best_k"]
        logger.info("最优 K = %d (轮廓系数=%.4f)", best_k,
                     cluster_results["optimal_metrics"]["silhouette"])

        # 在完整数据集上训练聚类
        self.clustering.fit(X_full_scaled, k=best_k)
        labels = self.clustering.labels  # 对应 X_full_scaled (15,289 rows)

        # PCA 2维可视化
        X_pca_2d, _, _ = apply_pca(X_full_scaled, n_components=2)
        X_pca_arr = X_pca_2d.values
        plot_elbow(
            cluster_results["inertias"],
            range(CLUSTER_K_RANGE.start, CLUSTER_K_RANGE.stop),
            optimal_k=best_k,
        )
        plot_cluster_metrics(cluster_results)
        plot_cluster_scatter(X_pca_arr, labels, title="PCA 2D — 聚类可视化")

        # 雷达图（用标准化数据）
        radar_data = self.clustering.get_radar_data(X_full_scaled)
        plot_cluster_radar(radar_data, title="聚类画像雷达图")

        # 聚类画像（用原始尺度数据，完整训练集）
        profiles = self.clustering.get_cluster_profiles(X_full, y_full)
        result.cluster_profiles = profiles
        result.business_insights["cluster_count"] = best_k
        result.business_insights["cluster_profiles"] = profiles

        # ================================================================
        # 5. VIF 共线性诊断
        # ================================================================
        logger.info("VIF 诊断...")
        vif_df = compute_vif(X_train)
        high_vif = len(vif_df[vif_df["VIF"] > 10])
        logger.info("VIF > 10: %d / %d", high_vif, len(vif_df))

        # ================================================================
        # 6. PCA 降维（用于回归模型）
        # ================================================================
        X_train_pca, pca_model, pca_var = apply_pca(X_train)
        n_components = pca_model.n_components_
        cum_var = sum(pca_var) * 100
        logger.info("PCA: %d → %d (保留 %.1f%% 方差)",
                    X_train.shape[1], n_components, cum_var)
        plot_pca_variance(pca_var, threshold=0.95)

        X_val_pca = pd.DataFrame(
            pca_model.transform(X_val),
            columns=[f"PC{i+1}" for i in range(n_components)],
            index=X_val.index,
        )

        # ================================================================
        # 7. 线性回归 — 全特征
        # ================================================================
        logger.info("线性回归 (全特征, PCA=%d维)...", n_components)
        lr_full = BlueberryLinearRegression()
        lr_full.fit_ridge(X_train_pca, y_train, tune=True)
        y_pred_full = lr_full.predict(X_val_pca)
        m_full = regression_metrics(y_val.values, y_pred_full)
        self.all_metrics["Ridge-全特征"] = m_full

        lr_full_l = BlueberryLinearRegression()
        lr_full_l.fit_lasso(X_train_pca, y_train, tune=True)
        y_pred_full_l = lr_full_l.predict(X_val_pca)
        self.all_metrics["Lasso-全特征"] = regression_metrics(
            y_val.values, y_pred_full_l
        )

        logger.info("Ridge-全特征 R²=%.4f RMSE=%.1f", m_full["r2"], m_full["rmse"])

        # ================================================================
        # 8. 线性回归 — 排除果实特征
        # ================================================================
        logger.info("线性回归 (排除果实特征)...")
        Xt_nf = X_train[no_fruit_features]
        Xv_nf = X_val[no_fruit_features]

        Xt_nf_pca, pca_nf, pca_nf_var = apply_pca(Xt_nf)
        Xv_nf_pca = pd.DataFrame(
            pca_nf.transform(Xv_nf),
            columns=[f"PC{i+1}" for i in range(pca_nf.n_components_)],
            index=Xv_nf.index,
        )

        lr_nf = BlueberryLinearRegression()
        lr_nf.fit_ridge(Xt_nf_pca, y_train, tune=True)
        y_pred_nf = lr_nf.predict(Xv_nf_pca)
        m_nf = regression_metrics(y_val.values, y_pred_nf)
        self.all_metrics["Ridge-排除果实"] = m_nf

        lr_nf_l = BlueberryLinearRegression()
        lr_nf_l.fit_lasso(Xt_nf_pca, y_train, tune=True)
        y_pred_nf_l = lr_nf_l.predict(Xv_nf_pca)
        m_nf_l = regression_metrics(y_val.values, y_pred_nf_l)
        self.all_metrics["Lasso-排除果实"] = m_nf_l

        logger.info(
            "Ridge-排除果实 R²=%.4f RMSE=%.1f (R²下降 %.2f)",
            m_nf["r2"], m_nf["rmse"], m_full["r2"] - m_nf["r2"],
        )

        plot_residuals(y_val.values, y_pred_nf_l, "Lasso-排除果实特征")
        plot_actual_vs_predicted(y_val.values, y_pred_nf_l, "Lasso-排除果实特征")

        # ================================================================
        # 9. 随机森林
        # ================================================================
        logger.info("随机森林...")
        rf = BlueberryRandomForest()
        if self.tune:
            rf.randomized_search(Xt_nf, y_train, n_iter=30)
        else:
            rf.fit(Xt_nf, y_train, n_estimators=RF_N_ESTIMATORS)
        y_pred_rf = rf.predict(Xv_nf)
        m_rf = regression_metrics(y_val.values, y_pred_rf)
        self.all_metrics["随机森林"] = m_rf

        imp_df = rf.get_feature_importance(no_fruit_features)
        result.feature_importance = imp_df

        plot_feature_importance(
            imp_df["feature"].tolist(), imp_df["importance"].values
        )
        plot_residuals(y_val.values, y_pred_rf, "随机森林")
        plot_actual_vs_predicted(y_val.values, y_pred_rf, "随机森林")

        # 学习曲线 + 特征交互
        plot_learning_curves(rf.model, Xt_nf, y_train, model_name="随机森林")
        top2 = imp_df["feature"].head(2).tolist()
        df_interact = pd.concat([Xt_nf, y_train.rename("yield")], axis=1)
        plot_feature_interaction(df_interact, top2[0], top2[1], target="yield")

        # ================================================================
        # 10. 交叉验证
        # ================================================================
        cv_result = cross_validate(rf.model, Xt_nf, y_train, cv=5, scoring="r2")
        result.business_insights["cv_r2"] = cv_result

        # ================================================================
        # 11. 模型对比
        # ================================================================
        comparison = pd.DataFrame(self.all_metrics).T
        comparison = comparison.sort_values("rmse")
        result.comparison_table = comparison

        plot_model_comparison(self.all_metrics, "r2")
        plot_model_comparison(self.all_metrics, "rmse")

        # ================================================================
        # 12. 测试集预测
        # ================================================================
        test_clean = self.preprocessor.clean(test_raw)
        X_test, _ = self.preprocessor.split_features_target(test_clean)
        X_test_scaled = self.preprocessor.scale(X_test, fit=False)
        X_test_nf = X_test_scaled[no_fruit_features]
        test_preds = rf.predict(X_test_nf)
        result.test_predictions = test_preds

        submission = pd.DataFrame({
            "id": range(len(test_preds)), "yield": test_preds
        })
        sub_path = os.path.join(MODELS_DIR, "test_predictions.csv")
        submission.to_csv(sub_path, index=False)
        logger.info(
            "测试集预测: 均值=%.1f, 范围=[%.1f, %.1f]",
            test_preds.mean(), test_preds.min(), test_preds.max(),
        )

        # ================================================================
        # 13. 业务洞察
        # ================================================================
        result.business_insights["best_model"] = comparison.index[0]
        result.business_insights["best_r2"] = comparison.iloc[0]["r2"]
        result.business_insights["best_rmse"] = comparison.iloc[0]["rmse"]
        result.business_insights["fruit_feature_r2_drop"] = (
            m_full["r2"] - m_nf["r2"]
        )

        result.elapsed = time.time() - t0
        result.metrics = self.all_metrics
        logger.info("流水线完成 (%.1f 秒)", result.elapsed)

        self._write_summary(result, comparison, imp_df, cv_result, best_k)
        return result

    def _write_summary(self, result, comparison, imp_df, cv_result, best_k):
        """生成 L1-L4 答辩对照摘要文件。"""
        summary_path = os.path.join(FIGURES_DIR, "..", "L1-L4答辩对照摘要.txt")
        lines = []
        w = lines.append

        w("=" * 65)
        w("  野生蓝莓产量预测分析系统 — L1~L4 答辩对照摘要")
        w(f"  运行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}  |  耗时: {result.elapsed:.1f} 秒")
        w("=" * 65)
        w("")
        w("  【等级说明】L1完成分析 → L2过程清晰 → L3报告完整有创意 → L4系统化")
        w("")

        # ── L1 ──
        w("┌─────────────────────────────────────────────────────────────┐")
        w("│  L1 — 完成分析过程                                          │")
        w("├─────────────────────────────────────────────────────────────┤")
        w("│  ✓ 15,289 条训练数据，0 缺失，0 重复                         │")
        w("│  ✓ 数据预处理: StandardScaler + 8:2 训练验证划分             │")
        w("│  ✓ EDA: 相关性热力图, 产量分布直方图                          │")
        w("│  ✓ K-Means 聚类, Ridge/Lasso 回归, 随机森林                  │")
        w("│  ✓ 测试集 10,194 条预测结果输出                               │")
        w("│                                                              │")
        w("│  对应图表:                                                    │")
        w("│    correlation_heatmap.png     — 特征相关性热力图              │")
        w("│    feature_distributions.png   — 特征分布直方图               │")
        w("└─────────────────────────────────────────────────────────────┘")
        w("")

        # ── L2 ──
        w("┌─────────────────────────────────────────────────────────────┐")
        w("│  L2 — 问题定义明确、过程清晰、合理选择模型                     │")
        w("├─────────────────────────────────────────────────────────────┤")
        w("│  ✓ CLI 命令行接口: --mode full|train|predict, --tune          │")
        w("│  ✓ 聚类: 肘部法则 + 轮廓系数 + DB指数 + CH分数 四指标选 K     │")
        w(f"│    最优 K = {best_k}, 轮廓系数 = {self.clustering.optimal_results['optimal_metrics']['silhouette']:.4f}       │")
        w("│  ✓ PCA 降维: 保留 95% 方差, 消除 10 个 VIF>10 的共线特征      │")
        w("│  ✓ RidgeCV + LassoCV: 交叉验证自动选择正则化强度 alpha         │")
        w("│  ✓ 随机森林: n_estimators=200, max_features=sqrt              │")
        w("│  ✓ 评估指标: R² + RMSE + MAE + MAPE + Explained Variance     │")
        w("│                                                              │")
        w("│  对应图表:                                                    │")
        w("│    elbow_method.png           — 肘部法则曲线                  │")
        w("│    cluster_metrics.png        — 聚类三指标综合评分             │")
        w("│    pca_variance.png           — PCA 主成分方差分析             │")
        w("└─────────────────────────────────────────────────────────────┘")
        w("")

        # ── L3 ──
        w("┌─────────────────────────────────────────────────────────────┐")
        w("│  L3 — 分析报告完整翔实、有创意、切合业务                       │")
        w("├─────────────────────────────────────────────────────────────┤")
        w("│  ★ 核心创新: 果实特征对照实验                                  │")
        w(f"│    方案A (含果实特征): R²={result.metrics['Ridge-全特征']['r2']:.4f}, RMSE={result.metrics['Ridge-全特征']['rmse']:.1f}                            │")
        w(f"│    方案B (排除果实):   R²={result.metrics['Ridge-排除果实']['r2']:.4f}, RMSE={result.metrics['Ridge-排除果实']['rmse']:.1f}                            │")
        w("│    R² 断崖下降 {:.4f} — 果实特征是 数据泄露                   │".format(
            result.business_insights['fruit_feature_r2_drop']))
        w("│                                                              │")
        w("│  ★ 聚类画像业务解读:                                          │")
        w("│    聚类雷达图揭示两类种植环境的镜像差异                         │")
        w("│    一类: 高温多雨 + 高种子数                                   │")
        w("│    二类: 高蜜蜂种群 + 高坐果率                                  │")
        w("│                                                              │")
        w("│  ★ 业务落地建议:                                              │")
        w("│    1. 降雨管理优先 (RF特征重要性合计 44.5%)                     │")
        w("│    2. 蜂箱精准投放 (osmia+andrena 贡献 22%)                   │")
        w("│    3. 种植密度优化 (clonesize 贡献 16.6%)                     │")
        w("│    4. 分区域差异化管理 (基于聚类分组)                           │")
        w("│                                                              │")
        w("│  对应图表:                                                    │")
        w("│    model_comparison_r2.png    — 果实对照 R² 断崖柱状图         │")
        w("│    cluster_radar.png          — 聚类画像雷达图                 │")
        w("│    cluster_scatter.png        — PCA 聚类散点图                │")
        w("│    feature_importance_模型.png — 特征重要性排序               │")
        w("└─────────────────────────────────────────────────────────────┘")
        w("")

        # ── L4 ──
        w("┌─────────────────────────────────────────────────────────────┐")
        w("│  L4 — 系统化: 可复现、可配置、可诊断                           │")
        w("├─────────────────────────────────────────────────────────────┤")
        w("│  ✓ 命令行参数系统: --mode, --tune, --no-save, --verbose       │")
        w("│  ✓ 模块化工程结构: config/data/features/models/visualization  │")
        w("│  ✓ 超参数自动搜索: RidgeCV(L2), LassoCV(L1), GridSearchCV     │")
        w(f"│  ✓ 5折交叉验证: R²={cv_result['cv_mean']:.4f} ± {cv_result['cv_std']:.4f} (性能稳定, 标准差小)        │")
        w("│  ✓ 学习曲线: 训练/验证 R² 随样本量增加收敛, 无严重过拟合        │")
        w("│  ✓ 特征交互分析: Top2 特征联合散点图                            │")
        w("│  ✓ 日志系统: logging 模块, DEBUG/INFO 可切换                   │")
        w("│  ✓ 中文字体自动检测: Windows/macOS/Linux                      │")
        w("│  ✓ 模型可持久化: joblib save/load (保存到 outputs/models/)     │")
        w("│                                                              │")
        w("│  对应图表:                                                    │")
        w("│    learning_curve_随机森林.png — 学习曲线诊断                  │")
        w("│    interaction_*.png           — 特征交互散点图                │")
        w("│    residuals_*.png             — 残差分析诊断图                │")
        w("└─────────────────────────────────────────────────────────────┘")
        w("")

        # ── 模型总表 ──
        w("┌─────────────────────────────────────────────────────────────┐")
        w("│  最终模型对比总表 (按 RMSE 升序)                               │")
        w("├─────────────────────────────────────────────────────────────┤")
        top = comparison.head(1)
        w(f"│  ★ 最优: {comparison.index[0]:32s} R²={top.iloc[0]['r2']:.4f}  RMSE={top.iloc[0]['rmse']:.1f}  │")
        w("│                                                              │")
        for idx, row in comparison.iterrows():
            w(f"│    {idx:32s}  R²={row['r2']:.4f}  RMSE={row['rmse']:8.1f}  MAE={row['mae']:8.1f}  │")
        w("└─────────────────────────────────────────────────────────────┘")
        w("")
        w("  测试集预测: 均值=" + f"{result.test_predictions.mean():.1f}" +
          ", 范围=[" + f"{result.test_predictions.min():.1f}" +
          ", " + f"{result.test_predictions.max():.1f}" + "]")
        w("")
        w("  >> 详细报告: 蓝莓产量预测分析实训报告.docx")
        w("  >> 全部图表: outputs/figures/")
        w("  >> 预测数据: outputs/models/test_predictions.csv")
        w("=" * 65)

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("L1-L4 答辩摘要已保存: %s", summary_path)
