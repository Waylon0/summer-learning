"""统一流水线编排器：蓝莓产量预测系统。

包含两类分析：
  - 全模型：16 特征（含果实指标）→ 产量
  - 纯环境模型：13 特征（不含果实指标）→ 产量
  - 因果链分析：环境因素 → 果实指标（中间变量）→ 产量
"""

import logging
import os
import time
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd

from src.analysis.intermediate_analysis import (
    IntermediateAnalyzer,
    analyze_environment_to_fruit,
    generate_env_factor_summary,
)
from src.config import (
    CLUSTER_K_RANGE,
    CV_FOLDS,
    ENV_FEATURES,
    FIGURES_DIR,
    FRUIT_FEATURES,
    MODELS_DIR,
    NUMERIC_FEATURES,
    PCA_VARIANCE_THRESHOLD,
    PREDICTION_PATH,
    RF_N_ESTIMATORS,
    TARGET,
    XGB_N_ESTIMATORS,
)
from src.data.loader import load_test, load_train
from src.data.preprocessor import DataPreprocessor
from src.features.engineering import apply_pca
from src.models.clustering import BlueberryClustering
from src.models.ensemble import BlueberryEnsemble
from src.models.evaluation import cross_validate, summarize_models
from src.models.linear_regression import BlueberryLinearRegression, compute_vif
from src.models.random_forest import BlueberryRandomForest
from src.visualization.plots import (
    plot_actual_vs_predicted,
    plot_cluster_metrics,
    plot_cluster_radar,
    plot_cluster_scatter,
    plot_correlation_heatmap,
    plot_elbow,
    plot_env_factor_grouped_importance,
    plot_env_fruit_importance,
    plot_env_only_feature_importance,
    plot_env_vs_full_comparison,
    plot_feature_importance,
    plot_feature_interaction,
    plot_model_comparison,
    plot_pca_variance,
    plot_residuals,
)

logger = logging.getLogger("blueberry")

try:
    from src.models.xgboost_model import BlueberryXGBoost, XGB_AVAILABLE  # noqa: F401
except ImportError:
    XGB_AVAILABLE = False


@dataclass
class PipelineResult:
    """流水线输出结果容器。"""

    models: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    cv_results: dict = field(default_factory=dict)
    cluster_profiles: pd.DataFrame | None = None
    feature_importance: pd.DataFrame | None = None
    # 新增：纯环境模型结果
    env_only_metrics: dict = field(default_factory=dict)
    env_only_importance: pd.DataFrame | None = None
    env_to_fruit_importance: dict = field(default_factory=dict)
    intermediate_analysis: dict = field(default_factory=dict)
    test_predictions: pd.DataFrame | None = None
    comparison_table: pd.DataFrame | None = None
    elapsed: float = 0.0


class BlueberryPipeline:
    """端到端流水线：包含因果链分析和全模型/纯环境模型双路对比。"""

    def __init__(self, tune: bool = False, save_models: bool = True):
        self.tune = tune
        self.save_models = save_models
        self.preprocessor = DataPreprocessor()
        self.result = PipelineResult()
        self._data: dict = {}
        self._has_xgboost = XGB_AVAILABLE
        if not self._has_xgboost:
            logger.info("xgboost 未安装；将跳过 XGBoost 步骤。")

    def run(self) -> PipelineResult:
        t0 = time.time()

        self._step_load()
        self._step_eda()
        self._step_clustering()
        self._step_pca()
        self._step_linear()              # 全模型 Ridge（PCA）
        self._step_rf()                  # 全模型 RF
        if self._has_xgboost:
            self._step_xgboost()         # 全模型 XGBoost
        self._step_ensemble()            # Stacking 集成
        self._step_env_only_models()     # ★ 纯环境模型
        self._step_causal_analysis()     # ★ 因果链分析
        self._step_compare()
        self._step_business_insights()

        self.result.elapsed = time.time() - t0
        logger.info("流水线完成，耗时 %.1f 秒", self.result.elapsed)
        return self.result

    # ================================================================
    # 步骤 1-8：与之前相同（数据加载、EDA、聚类、PCA、建模）
    # ================================================================

    def _step_load(self):
        logger.info("=== 步骤 1：数据加载与预处理 ===")
        train = load_train()
        test = load_test()
        logger.info("训练集: %s, 测试集: %s", train.shape, test.shape)

        info = self.preprocessor.inspect(train)
        logger.info("缺失值合计: %s", sum(info["missing"].values()))
        logger.info("重复行数: %d", info["duplicated"])

        df_clean = self.preprocessor.clean(train)
        self._data["df_clean"] = df_clean

        X_train, X_val, y_train, y_val = self.preprocessor.pipeline(train)
        self._data.update({
            "X_train": X_train, "X_val": X_val,
            "y_train": y_train, "y_val": y_val,
        })

        test_clean = self.preprocessor.clean(test, drop_id=False)
        test_ids = test_clean["id"].values
        test_X, _ = self.preprocessor.split_features_target(test_clean)
        test_X_scaled = self.preprocessor.scale(test_X, fit=False)
        self._data["test_ids"] = test_ids
        self._data["test_X_scaled"] = test_X_scaled

    def _step_eda(self):
        logger.info("=== 步骤 2：EDA 与相关性分析 ===")
        df_full = pd.concat(
            [self._data["df_clean"][NUMERIC_FEATURES],
             self._data["df_clean"][TARGET].rename(TARGET)], axis=1,
        )
        plot_correlation_heatmap(df_full)

        corr_with_yield = df_full.corr()[TARGET].drop(TARGET).abs().sort_values(ascending=False)
        top_feat = corr_with_yield.index[0]
        second_feat = corr_with_yield.index[1]
        plot_feature_interaction(df_full, top_feat, second_feat)

        with open(os.path.join(FIGURES_DIR, "correlation_report.txt"), "w", encoding="utf-8") as f:
            f.write("与产量相关性排名（含果实指标）：\n")
            for feat, val in corr_with_yield.items():
                f.write(f"  {feat}: {val:.4f}\n")

    def _step_clustering(self):
        logger.info("=== 步骤 3：K-Means 聚类分析 ===")
        X_full = self.preprocessor.split_features_target(self._data["df_clean"])[0]
        X_full_scaled = pd.DataFrame(
            self.preprocessor.scaler.transform(X_full),
            columns=X_full.columns, index=X_full.index,
        )

        cluster = BlueberryClustering()
        results = cluster.find_optimal_k(X_full_scaled, CLUSTER_K_RANGE)
        best_k = results["best_k"]
        logger.info("最优 K=%d（轮廓系数=%.4f）", best_k, results["optimal_metrics"]["silhouette"])
        cluster.fit(X_full_scaled, k=best_k)

        radar_data = cluster.get_radar_data(X_full)
        plot_cluster_radar(radar_data)
        plot_elbow(results["inertias"], results["k_range"], best_k)
        plot_cluster_metrics(results)

        X_pca_2d, _, _ = apply_pca(X_full_scaled, n_components=2)
        plot_cluster_scatter(X_pca_2d.values, cluster.get_predictions())

        y_full = self._data["df_clean"][TARGET]
        profiles = cluster.get_cluster_profiles(X_full, y_full)
        self.result.cluster_profiles = profiles
        logger.info("聚类画像：\n%s", profiles.to_string())

        self._write_cluster_report(profiles, best_k,
                                   os.path.join(FIGURES_DIR, "cluster_business_report.txt"))

    def _write_cluster_report(self, profiles: pd.DataFrame, k: int, path: str):
        lines = ["=" * 60, f"  野生蓝莓产量 - 聚类业务报告 (K={k})", "=" * 60, "",
                 "聚类将种植条件划分为若干独特类型。", "以下是各聚类的业务解读：", ""]
        for cid, row in profiles.iterrows():
            cid_int = int(cid)
            count, pct = int(row["count"]), row["pct"]
            ymean = row.get("yield_mean", "N/A")
            if ymean != "N/A":
                level = "高产优质型" if cid == profiles.index[0] else (
                    "低产风险型" if cid == profiles.index[-1] else "中产标准型")
            else:
                level = "未知"
            lines.append(f"[聚类 {cid_int}] {level}")
            lines.append(f"  样本量: {count}（占总量 {pct}%）")
            lines.append(f"  平均产量: {ymean}")
            lines.append(f"  关键特征均值：")
            for col in profiles.columns:
                if col.endswith("_mean") and col != "yield_mean":
                    lines.append(f"    {col.replace('_mean', '')}: {row[col]}")
            lines.append("")
        lines.extend([
            "-" * 60, "业务优化建议：", "",
            "1. 高产优质型：代表最优种植条件组合，建议推广其参数。",
            "2. 低产风险型：优先改进授粉密度、克隆面积，或选择更温和气候。",
            "3. 基于聚类分群进行差异化营销。",
            "-" * 60,
        ])
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("聚类业务报告已保存至 %s", path)

    def _step_pca(self):
        logger.info("=== 步骤 4：PCA 降维 ===")
        vif_df = compute_vif(self._data["X_train"])
        logger.info("VIF Top 5：\n%s", vif_df.head(5).to_string())

        X_train_pca, pca_model, explained = apply_pca(
            self._data["X_train"], variance_threshold=PCA_VARIANCE_THRESHOLD)
        X_val_pca = pd.DataFrame(
            pca_model.transform(self._data["X_val"]),
            columns=[f"PC{i + 1}" for i in range(X_train_pca.shape[1])],
            index=self._data["X_val"].index,
        )
        cumulative = np.cumsum(explained)
        plot_pca_variance(explained, cumulative, PCA_VARIANCE_THRESHOLD)
        logger.info("PCA: %d → %d 主成分（保留 %.1f%% 方差）",
                     self._data["X_train"].shape[1], X_train_pca.shape[1],
                     cumulative[-1] * 100)
        self._data.update({
            "X_train_pca": X_train_pca, "X_val_pca": X_val_pca,
            "pca_model": pca_model, "pca_explained": explained,
        })

    def _step_linear(self):
        logger.info("=== 步骤 5：岭回归（全模型，PCA 后） ===")
        Xt, Xv = self._data["X_train_pca"], self._data["X_val_pca"]
        yt, yv = self._data["y_train"], self._data["y_val"]
        lr = BlueberryLinearRegression()
        lr.fit_ridge(Xt, yt, alpha=1.0)
        y_pred = lr.predict(Xv)
        metrics = lr.evaluate(yv, y_pred)
        logger.info("岭回归: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["岭回归 (Ridge)"] = metrics
        self.result.cv_results["岭回归 (Ridge)"] = cross_validate(lr.model, Xt, yt, cv=CV_FOLDS)
        self.result.models["ridge"] = lr
        plot_residuals(yv.values, y_pred, "岭回归")
        plot_actual_vs_predicted(yv.values, y_pred, "岭回归")

    def _step_rf(self):
        logger.info("=== 步骤 6：随机森林（全模型） ===")
        Xt, Xv = self._data["X_train"], self._data["X_val"]
        yt, yv = self._data["y_train"], self._data["y_val"]
        rf = BlueberryRandomForest()
        rf.fit(Xt, yt, n_estimators=RF_N_ESTIMATORS)
        y_pred = rf.predict(Xv)
        metrics = rf.evaluate(yv, y_pred)
        logger.info("随机森林: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["随机森林 (RF)"] = metrics
        self.result.cv_results["随机森林 (RF)"] = cross_validate(rf.model, Xt, yt, cv=CV_FOLDS)
        self.result.models["random_forest"] = rf
        importance = rf.get_feature_importance(list(Xt.columns))
        self.result.feature_importance = importance.head(10)
        plot_feature_importance(importance["feature"].tolist(), importance["importance"].values, "随机森林")
        plot_residuals(yv.values, y_pred, "随机森林")
        plot_actual_vs_predicted(yv.values, y_pred, "随机森林")

    def _step_xgboost(self):
        logger.info("=== 步骤 7：XGBoost（全模型） ===")
        Xt, Xv = self._data["X_train"], self._data["X_val"]
        yt, yv = self._data["y_train"], self._data["y_val"]
        xgb_model = BlueberryXGBoost()
        xgb_model.fit(Xt, yt, Xv, yv, n_estimators=XGB_N_ESTIMATORS)
        y_pred = xgb_model.predict(Xv)
        metrics = xgb_model.evaluate(yv, y_pred)
        logger.info("XGBoost: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["XGBoost"] = metrics
        self.result.cv_results["XGBoost"] = cross_validate(xgb_model.model, Xt, yt, cv=CV_FOLDS)
        self.result.models["xgboost"] = xgb_model
        importance = xgb_model.get_feature_importance(list(Xt.columns))
        plot_feature_importance(importance["feature"].tolist(), importance["importance"].values, "XGBoost")
        plot_residuals(yv.values, y_pred, "XGBoost")
        plot_actual_vs_predicted(yv.values, y_pred, "XGBoost")

    def _step_ensemble(self):
        logger.info("=== 步骤 8：Stacking 集成学习 ===")
        Xt, Xv = self._data["X_train"], self._data["X_val"]
        yt, yv = self._data["y_train"], self._data["y_val"]
        estimators = [("rf", self.result.models["random_forest"].model)]
        if self._has_xgboost and "xgboost" in self.result.models:
            estimators.append(("xgb", self.result.models["xgboost"].model))
        elif "ridge" in self.result.models:
            estimators.append(("ridge", self.result.models["ridge"].model))
        if len(estimators) < 2:
            logger.warning("已训练模型不足 2 个，跳过集成。")
            return
        ensemble = BlueberryEnsemble()
        ensemble.fit(Xt, yt, estimators=estimators)
        y_pred = ensemble.predict(Xv)
        metrics = ensemble.evaluate(yv, y_pred)
        logger.info("Stacking 集成: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["Stacking 集成"] = metrics
        self.result.cv_results["Stacking 集成"] = cross_validate(ensemble.model, Xt, yt, cv=CV_FOLDS)
        self.result.models["ensemble"] = ensemble
        plot_residuals(yv.values, y_pred, "Stacking 集成")
        plot_actual_vs_predicted(yv.values, y_pred, "Stacking 集成")

    # ================================================================
    # ★ 步骤 9：纯环境模型（不含果实指标）
    # ================================================================

    def _step_env_only_models(self):
        """纯环境因素 → 产量建模。

        从标准化后的完整特征中提取 ENV_FEATURES（13 个）子集，
        训练随机森林和 XGBoost，还原环境因素的真实影响权重。
        """
        logger.info("=== 步骤 9：纯环境模型（排除果实指标） ===")
        Xt = self._data["X_train"][ENV_FEATURES]
        Xv = self._data["X_val"][ENV_FEATURES]
        yt, yv = self._data["y_train"], self._data["y_val"]

        # 随机森林（纯环境）
        rf_env = BlueberryRandomForest()
        rf_env.fit(Xt, yt, n_estimators=RF_N_ESTIMATORS)
        y_pred = rf_env.predict(Xv)
        metrics = rf_env.evaluate(yv, y_pred)
        cv_res = cross_validate(rf_env.model, Xt, yt, cv=CV_FOLDS)
        logger.info("纯环境 RF: R²=%.4f RMSE=%.4f CV=%.4f",
                     metrics["r2"], metrics["rmse"], cv_res["cv_mean"])

        self.result.env_only_metrics["随机森林（仅环境）"] = metrics
        imp = rf_env.get_feature_importance(list(ENV_FEATURES))
        self.result.env_only_importance = imp
        plot_env_only_feature_importance(imp, "随机森林（仅环境）")
        plot_env_factor_grouped_importance(imp)
        plot_residuals(yv.values, y_pred, "纯环境 RF")
        plot_actual_vs_predicted(yv.values, y_pred, "纯环境 RF")

        # 全模型 RF vs 纯环境 RF 对比
        full_rf_r2 = self.result.metrics.get("随机森林 (RF)", {}).get("r2", 0)
        full_rf_cv = self.result.cv_results.get("随机森林 (RF)", {})
        plot_env_vs_full_comparison(metrics,
                                    {"r2": full_rf_r2},
                                    cv_res, full_rf_cv)

        # XGBoost（纯环境，若可用）
        if self._has_xgboost:
            xgb_env = BlueberryXGBoost()
            xgb_env.fit(Xt, yt, n_estimators=XGB_N_ESTIMATORS)
            y_pred_xgb = xgb_env.predict(Xv)
            metrics_xgb = xgb_env.evaluate(yv, y_pred_xgb)
            self.result.env_only_metrics["XGBoost（仅环境）"] = metrics_xgb
            logger.info("纯环境 XGBoost: R²=%.4f RMSE=%.4f",
                         metrics_xgb["r2"], metrics_xgb["rmse"])
            xgb_imp = xgb_env.get_feature_importance(list(ENV_FEATURES))
            plot_env_only_feature_importance(xgb_imp, "XGBoost（仅环境）")

    # ================================================================
    # ★ 步骤 10：环境因素 → 果实指标 因果链分析
    # ================================================================

    def _step_causal_analysis(self):
        """因果链分析：环境因素 → 果实指标 → 产量。

        1. 用随机森林分析环境因素对 fruitset/fruitmass/seeds 的影响
        2. 对比全模型与纯环境模型，量化果实指标的中介效应
        """
        logger.info("=== 步骤 10：因果链分析（环境→果实指标→产量） ===")
        df_clean = self._data["df_clean"]
        Xt = self._data["X_train"]
        yt = self._data["y_train"]
        Xv = self._data["X_val"]
        yv = self._data["y_val"]

        analyzer = IntermediateAnalyzer(self.preprocessor)
        analyzer.analyze(df_clean, Xt, yt, Xv, yv)
        self.result.intermediate_analysis = analyzer.results
        self.result.env_to_fruit_importance = analyzer.env_importance

        # 可视化：环境因素对各果实指标的影响
        if analyzer.env_importance:
            plot_env_fruit_importance(analyzer.env_importance)

        # 生成因果链摘要
        summary = generate_env_factor_summary(analyzer.results)
        report_path = os.path.join(FIGURES_DIR, "causal_chain_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(summary)
        logger.info("因果链分析报告已保存至 %s", report_path)

        # 皮尔逊相关：环境→果实
        env_fruit_corr = analyze_environment_to_fruit(df_clean)
        corr_path = os.path.join(FIGURES_DIR, "env_to_fruit_correlation.txt")
        with open(corr_path, "w", encoding="utf-8") as f:
            f.write("环境因素与果实指标的皮尔逊相关系数：\n\n")
            for fruit, corrs in env_fruit_corr.items():
                f.write(f"[{fruit}]\n")
                for feat, val in sorted(corrs.items(), key=lambda x: abs(x[1]), reverse=True):
                    f.write(f"  {feat}: {val:.4f}\n")
                f.write("\n")

        # 记录纯环境因素→产量的重要性（用于摘要报告）
        if self.result.env_only_importance is None:
            self.result.env_only_importance = (
                self.result.intermediate_analysis.get("env_only_rf", {}).get("importance")
            )

    # ================================================================
    # 步骤：模型对比 & 业务报告
    # ================================================================

    def _step_compare(self):
        logger.info("=== 模型对比 ===")
        comparison = summarize_models(self.result.metrics)
        self.result.comparison_table = comparison
        logger.info("模型排名：\n%s", comparison.to_string())

        plot_model_comparison(self.result.metrics, "r2")
        plot_model_comparison(self.result.metrics, "rmse")
        plot_model_comparison(self.result.metrics, "mae")

        best_name = comparison.index[0]
        logger.info("最佳模型: %s (RMSE=%.4f)", best_name, comparison.loc[best_name, "rmse"])

        if self.save_models:
            for name, model_obj in self.result.models.items():
                path = os.path.join(MODELS_DIR, f"{name}.pkl")
                joblib.dump(model_obj, path)
                logger.info("模型已保存: %s", path)

    def _step_business_insights(self):
        logger.info("=== 业务建议与测试集预测 ===")
        best_name = self.result.comparison_table.index[0]
        best_model = self._get_best_model(best_name)

        test_X = self._data["test_X_scaled"]
        test_ids = self._data["test_ids"]
        y_pred_test = best_model.predict(test_X)
        pd.DataFrame({"id": test_ids, "predicted_yield": y_pred_test}).to_csv(
            PREDICTION_PATH, index=False)
        logger.info("测试集预测已保存至 %s（%d 行）", PREDICTION_PATH, len(y_pred_test))

        report = self._generate_summary_report()
        report_path = os.path.join(FIGURES_DIR, "analysis_summary.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info("分析总结已保存至 %s", report_path)

    def _get_best_model(self, name: str):
        mapping = {
            "岭回归 (Ridge)": self.result.models.get("ridge"),
            "随机森林 (RF)": self.result.models.get("random_forest"),
            "XGBoost": self.result.models.get("xgboost"),
            "Stacking 集成": self.result.models.get("ensemble"),
        }
        model = mapping.get(name)
        return model or self.result.models.get("random_forest") or self.result.models.get("ridge")

    def _generate_summary_report(self) -> str:
        used = list(self.result.metrics.keys())
        model_list = "、".join(used)

        # 纯环境模型影响力（按大类合并）
        env_groups = {}
        if self.result.env_only_importance is not None:
            imp = self.result.env_only_importance.set_index("feature")["importance"]
            from src.config import BEE_FEATURES, UPPER_TEMP_FEATURES, LOWER_TEMP_FEATURES, RAIN_FEATURES
            env_groups = {
                "温度因素": imp.reindex(UPPER_TEMP_FEATURES + LOWER_TEMP_FEATURES).sum(),
                "蜂群密度": imp.reindex(BEE_FEATURES).sum(),
                "降雨": imp.reindex(RAIN_FEATURES).sum(),
                "克隆株大小": imp.get("clonesize", 0),
            }
            env_total = sum(env_groups.values()) or 1.0
            env_groups = {k: v / env_total * 100 for k, v in env_groups.items()}

        env_metrics = self.result.env_only_metrics.get(
            "随机森林（仅环境）",
            self.result.env_only_metrics.get("XGBoost（仅环境）", {}),
        )
        full_rf_metrics = self.result.metrics.get("随机森林 (RF)", {})

        lines = [
            "=" * 60,
            "  野生蓝莓产量预测 - 深度分析总结报告",
            "=" * 60,
            "",
            "一、分析框架",
            "  本报告包含两条分析路径：",
            "  路径 A（纯环境）：13 个环境特征 → 产量（排除 fruitset/fruitmass/seeds）",
            "  路径 B（全模型）：16 个特征 → 产量（含果实中间指标）",
            "  因果链：   环境因素 → 果实发育指标（中间变量）→ 产量",
            "",
            "二、数据概况",
            f"  训练样本: {len(self._data['y_train']) + len(self._data['y_val'])}",
            f"  环境特征(13): 克隆株大小、4 种蜂密度、6 个温度、2 个降雨",
            f"  果实指标(3): fruitset, fruitmass, seeds（中间生物变量）",
            f"  目标: yield",
            "",
            "三、全模型表现（含果实指标）",
        ]
        for name, row in self.result.comparison_table.iterrows():
            lines.append(f"  {name}: R²={row['r2']:.4f}  RMSE={row['rmse']:.4f}")

        lines.extend([
            "",
            "四、纯环境模型表现（不含果实指标，反映环境因素的纯影响力）",
        ])
        if env_metrics:
            lines.append(f"  随机森林: R²={env_metrics.get('r2', 0):.4f}  RMSE={env_metrics.get('rmse', 0):.2f}")
        if "XGBoost（仅环境）" in self.result.env_only_metrics:
            xgb_m = self.result.env_only_metrics["XGBoost（仅环境）"]
            lines.append(f"  XGBoost:   R²={xgb_m.get('r2', 0):.4f}  RMSE={xgb_m.get('rmse', 0):.2f}")

        lines.extend([
            "",
            "五、纯环境因素影响力占比（排除果实指标后）",
        ])
        for group, pct in sorted(env_groups.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {group}: {pct:.1f}%")

        if self.result.env_only_importance is not None:
            lines.append("\n  纯环境因素重要性排名：")
            for _, row in self.result.env_only_importance.iterrows():
                lines.append(f"    {row['feature']}: {row['importance']:.4f}")

        lines.extend([
            "",
            "六、因果链分析（环境 → 果实指标）",
        ])
        if self.result.env_to_fruit_importance:
            for fruit in FRUIT_FEATURES:
                if fruit in self.result.env_to_fruit_importance:
                    imp_df = self.result.env_to_fruit_importance[fruit]
                    top3 = imp_df.head(3)
                    lines.append(f"  [{fruit}] Top 3 环境影响因素：")
                    for _, row in top3.iterrows():
                        lines.append(f"    {row['feature']}: {row['importance']:.4f}")

        full_r2 = full_rf_metrics.get('r2', 0)
        env_r2 = env_metrics.get('r2', 0)
        env_r2_safe = max(env_r2, 0.001)
        mediation_pct = env_r2 / max(full_r2, 0.001) * 100

        lines.extend([
            "",
            "七、关键发现解读",
            "",
            "  1. 果实指标的中介效应：",
            f"     全模型 R²({full_r2:.4f}) - 纯环境 R²({env_r2:.4f})",
            f"     = 果实发育提供的额外解释力 ≈ {full_r2 - env_r2:.4f}",
            f"     环境影响的 {mediation_pct:.0f}% 通过果实发育传导到最终产量。",
            "",
            "  2. 最重要的环境因素：",
        ])
        if env_groups:
            top_key = max(env_groups, key=env_groups.get)
            lines.append(f"     {top_key}（{env_groups[top_key]:.1f}%）是除果实指标外最核心的产量决定因素。")

        lines.extend([
            "",
            "  3. 温度的双重作用：",
            "     温度直接影响产量（纯环境模型中贡献显著），同时通过影响",
            "     seeds（种子数）和 fruitset（果实集）间接影响产量。",
            "     高温抑制果实发育，是产量降低的关键环境胁迫因子。",
            "",
            "  4. 降雨的负面效应：",
            "     相关系数 r ≈ -0.48，过多的花期降雨不利于授粉和坐果。",
            "     在纯环境模型中，降雨仍是 Top 5 重要特征。",
            "",
            "  5. 蜂群品种差异化影响：",
            "     壁蜂（osmia）和熊蜂（bumbles）对果实发育有正面贡献；",
            "     蜜蜂（honeybee）密度过高反而不利。",
            "     建议优化蜂种配比，增加壁蜂投放。",
            "",
            "八、业务建议",
            "  - 温度管理：选择气候温和区域种植，花期关注温度预报。",
            "  - 降雨防控：多雨地区建设防雨设施，优化排水系统。",
            "  - 授粉优化：增加壁蜂和熊蜂比例，控制蜜蜂密度。",
            "  - 克隆面积：适中的克隆株面积（非越大越好）。",
            "  - 产量预估：利用环境特征在花期初期即可预测产量。",
            "",
            "=" * 60,
            "  由 BlueberryPipeline 自动生成",
            "=" * 60,
        ])
        return "\n".join(lines)
