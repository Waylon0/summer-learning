"""统一流水线编排器：蓝莓产量预测系统。

当可选依赖（xgboost）未安装时自动降级运行。
"""

import logging
import os
import time
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd

from src.config import (
    CLUSTER_K_RANGE,
    CV_FOLDS,
    FIGURES_DIR,
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
    plot_feature_importance,
    plot_feature_interaction,
    plot_model_comparison,
    plot_pca_variance,
    plot_residuals,
)

logger = logging.getLogger("blueberry")

# 检测可选依赖
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
    test_predictions: pd.DataFrame | None = None
    comparison_table: pd.DataFrame | None = None
    elapsed: float = 0.0


class BlueberryPipeline:
    """端到端流水线：数据加载 -> EDA -> 聚类 -> 建模 -> 导出。

    若 xgboost 已安装则使用，否则自动降级为随机森林 + 岭回归。
    """

    def __init__(self, tune: bool = False, save_models: bool = True):
        """初始化流水线。

        Parameters
        ----------
        tune : bool
            是否启用超参数调优。
        save_models : bool
            是否将训练好的模型持久化到磁盘。
        """
        self.tune = tune
        self.save_models = save_models
        self.preprocessor = DataPreprocessor()
        self.result = PipelineResult()
        self._data: dict = {}
        self._has_xgboost = XGB_AVAILABLE
        if not self._has_xgboost:
            logger.info(
                "xgboost 未安装；将跳过 XGBoost 和 Stacking Ensemble 步骤。"
                "安装命令：pip install xgboost"
            )

    def run(self) -> PipelineResult:
        """执行完整的分析流水线。

        Returns
        -------
        PipelineResult
            包含所有模型、指标和输出的结果对象。
        """
        t0 = time.time()

        self._step_load()
        self._step_eda()
        self._step_clustering()
        self._step_pca()
        self._step_linear()
        self._step_rf()
        if self._has_xgboost:
            self._step_xgboost()
        self._step_ensemble()
        self._step_compare()
        self._step_business_insights()

        self.result.elapsed = time.time() - t0
        logger.info("流水线完成，耗时 %.1f 秒", self.result.elapsed)
        return self.result

    def _step_load(self):
        """步骤 1：数据加载与预处理。"""
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
            "X_train": X_train,
            "X_val": X_val,
            "y_train": y_train,
            "y_val": y_val,
        })

        # 预处理测试集（保留 id 列用于提交）
        test_clean = self.preprocessor.clean(test, drop_id=False)
        test_ids = test_clean["id"].values
        test_X, _ = self.preprocessor.split_features_target(test_clean)
        test_X_scaled = self.preprocessor.scale(test_X, fit=False)
        self._data["test_ids"] = test_ids
        self._data["test_X_scaled"] = test_X_scaled

    def _step_eda(self):
        """步骤 2：探索性数据分析与相关性可视化。"""
        logger.info("=== 步骤 2：EDA 与相关性分析 ===")
        df_full = pd.concat(
            [self._data["df_clean"][NUMERIC_FEATURES],
             self._data["df_clean"][TARGET].rename(TARGET)],
            axis=1,
        )
        plot_correlation_heatmap(df_full)

        # 产量相关度最高的两个特征交互图
        corr_with_yield = df_full.corr()[TARGET].drop(TARGET).abs().sort_values(ascending=False)
        top_feat = corr_with_yield.index[0]
        second_feat = corr_with_yield.index[1]
        plot_feature_interaction(df_full, top_feat, second_feat)

        report_path = os.path.join(FIGURES_DIR, "correlation_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("与产量相关性 Top 5 特征：\n")
            for feat, val in corr_with_yield.head(5).items():
                f.write(f"  {feat}: {val:.4f}\n")

    def _step_clustering(self):
        """步骤 3：K-Means 聚类与业务画像。"""
        logger.info("=== 步骤 3：K-Means 聚类分析 ===")
        X_full = self.preprocessor.split_features_target(self._data["df_clean"])[0]
        X_full_scaled = pd.DataFrame(
            self.preprocessor.scaler.transform(X_full),
            columns=X_full.columns,
            index=X_full.index,
        )

        cluster = BlueberryClustering()
        results = cluster.find_optimal_k(X_full_scaled, CLUSTER_K_RANGE)
        best_k = results["best_k"]
        logger.info(
            "最优 K=%d（轮廓系数=%.4f）",
            best_k, results["optimal_metrics"]["silhouette"],
        )

        cluster.fit(X_full_scaled, k=best_k)

        # 聚类雷达图（使用原始未缩放的 X 以便业务解读）
        radar_data = cluster.get_radar_data(X_full)
        plot_cluster_radar(radar_data)

        plot_elbow(results["inertias"], results["k_range"], best_k)
        plot_cluster_metrics(results)

        X_pca_2d, _, _ = apply_pca(X_full_scaled, n_components=2)
        plot_cluster_scatter(X_pca_2d.values, cluster.get_predictions())

        # 业务解读：含有产量统计的聚类画像
        y_full = self._data["df_clean"][TARGET]
        profiles = cluster.get_cluster_profiles(X_full, y_full)
        self.result.cluster_profiles = profiles
        logger.info("聚类画像：\n%s", profiles.to_string())

        report_path = os.path.join(FIGURES_DIR, "cluster_business_report.txt")
        self._write_cluster_report(profiles, best_k, report_path)

    def _write_cluster_report(self, profiles: pd.DataFrame, k: int, path: str):
        """生成聚类业务解读报告。

        Parameters
        ----------
        profiles : pd.DataFrame
            聚类画像数据。
        k : int
            聚类数。
        path : str
            输出文件路径。
        """
        lines = [
            "=" * 60,
            f"  野生蓝莓产量 - 聚类业务报告 (K={k})",
            "=" * 60,
            "",
            "聚类将种植条件划分为若干独特类型。",
            "以下是各聚类的业务解读：",
            "",
        ]
        for cid, row in profiles.iterrows():
            cid_int = int(cid)
            count = int(row["count"])
            pct = row["pct"]
            ymean = row.get("yield_mean", "N/A")

            if ymean != "N/A":
                if cid == profiles.index[0]:
                    level = "高产优质型"
                elif cid == profiles.index[-1]:
                    level = "低产风险型"
                else:
                    level = "中产标准型"
            else:
                level = "未知"

            lines.append(f"[聚类 {cid_int}] {level}")
            lines.append(f"  样本量: {count}（占总量 {pct}%）")
            lines.append(f"  平均产量: {ymean}")
            lines.append(f"  关键特征均值：")
            for col in profiles.columns:
                if col.endswith("_mean") and col != "yield_mean":
                    feat_name = col.replace("_mean", "")
                    lines.append(f"    {feat_name}: {row[col]}")
            lines.append("")

        lines.extend([
            "-" * 60,
            "业务优化建议：",
            "",
            "1. 高产优质型聚类：代表最优种植条件组合。",
            "   建议将此类聚类的克隆株大小、蜜蜂密度和温度范围",
            "   推广到其他种植区域，以实现产量最大化。",
            "",
            "2. 低产风险型聚类：代表不理想的种植条件。",
            "   优先改进措施：增加授粉蜂密度、优化克隆株大小、",
            "   或选择温度条件更温和的种植地点。",
            "",
            "3. 中产标准型聚类：具有定向改进潜力。",
            "   识别与高产型聚类在哪些特征维度上存在差距，",
            "   并针对性地投入改进资源。",
            "",
            "4. 营销策略：基于产量预测分类进行差异化营销。",
            "   高产园区可走高端销售渠道；低产园区需技术支持",
            "   和授粉管理方面的投资扶持。",
            "-" * 60,
        ])

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        logger.info("聚类业务报告已保存至 %s", path)

    def _step_pca(self):
        """步骤 4：主成分分析降维与共线性诊断。"""
        logger.info("=== 步骤 4：PCA 降维 ===")
        vif_df = compute_vif(self._data["X_train"])
        logger.info("VIF（方差膨胀因子）Top 5：\n%s", vif_df.head(5).to_string())

        X_train_pca, pca_model, explained = apply_pca(
            self._data["X_train"], variance_threshold=PCA_VARIANCE_THRESHOLD,
        )
        X_val_pca = pd.DataFrame(
            pca_model.transform(self._data["X_val"]),
            columns=[f"PC{i + 1}" for i in range(X_train_pca.shape[1])],
            index=self._data["X_val"].index,
        )

        cumulative = np.cumsum(explained)
        plot_pca_variance(explained, cumulative, PCA_VARIANCE_THRESHOLD)

        logger.info(
            "PCA: %d 个特征 -> %d 个主成分（保留了 %.1f%% 方差）",
            self._data["X_train"].shape[1],
            X_train_pca.shape[1],
            cumulative[-1] * 100,
        )

        self._data["X_train_pca"] = X_train_pca
        self._data["X_val_pca"] = X_val_pca
        self._data["pca_model"] = pca_model
        self._data["pca_explained"] = explained

    def _step_linear(self):
        """步骤 5：岭回归（Ridge）建模。"""
        logger.info("=== 步骤 5：岭回归建模 ===")
        Xt = self._data["X_train_pca"]
        Xv = self._data["X_val_pca"]
        yt = self._data["y_train"]
        yv = self._data["y_val"]

        lr = BlueberryLinearRegression()
        lr.fit_ridge(Xt, yt, alpha=1.0)
        y_pred = lr.predict(Xv)
        metrics = lr.evaluate(yv, y_pred)
        logger.info("岭回归: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["岭回归 (Ridge)"] = metrics

        cv_res = cross_validate(lr.model, Xt, yt, cv=CV_FOLDS)
        self.result.cv_results["岭回归 (Ridge)"] = cv_res

        self.result.models["ridge"] = lr

        plot_residuals(yv.values, y_pred, "岭回归")
        plot_actual_vs_predicted(yv.values, y_pred, "岭回归")

    def _step_rf(self):
        """步骤 6：随机森林建模。"""
        logger.info("=== 步骤 6：随机森林建模 ===")
        Xt = self._data["X_train"]
        Xv = self._data["X_val"]
        yt = self._data["y_train"]
        yv = self._data["y_val"]

        rf = BlueberryRandomForest()
        rf.fit(Xt, yt, n_estimators=RF_N_ESTIMATORS)
        y_pred = rf.predict(Xv)
        metrics = rf.evaluate(yv, y_pred)
        logger.info("随机森林: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["随机森林 (RF)"] = metrics

        cv_res = cross_validate(rf.model, Xt, yt, cv=CV_FOLDS)
        self.result.cv_results["随机森林 (RF)"] = cv_res

        self.result.models["random_forest"] = rf

        importance = rf.get_feature_importance(list(Xt.columns))
        self.result.feature_importance = importance.head(10)
        plot_feature_importance(importance["feature"].tolist(), importance["importance"].values, "随机森林")
        plot_residuals(yv.values, y_pred, "随机森林")
        plot_actual_vs_predicted(yv.values, y_pred, "随机森林")

    def _step_xgboost(self):
        """步骤 7：XGBoost 建模。"""
        logger.info("=== 步骤 7：XGBoost 建模 ===")
        Xt = self._data["X_train"]
        Xv = self._data["X_val"]
        yt = self._data["y_train"]
        yv = self._data["y_val"]

        xgb_model = BlueberryXGBoost()
        xgb_model.fit(Xt, yt, Xv, yv, n_estimators=XGB_N_ESTIMATORS)
        y_pred = xgb_model.predict(Xv)
        metrics = xgb_model.evaluate(yv, y_pred)
        logger.info("XGBoost: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["XGBoost"] = metrics

        cv_res = cross_validate(xgb_model.model, Xt, yt, cv=CV_FOLDS)
        self.result.cv_results["XGBoost"] = cv_res

        self.result.models["xgboost"] = xgb_model

        importance = xgb_model.get_feature_importance(list(Xt.columns))
        plot_feature_importance(importance["feature"].tolist(), importance["importance"].values, "XGBoost")
        plot_residuals(yv.values, y_pred, "XGBoost")
        plot_actual_vs_predicted(yv.values, y_pred, "XGBoost")

    def _step_ensemble(self):
        """步骤 8：Stacking 集成学习。"""
        logger.info("=== 步骤 8：Stacking 集成学习 ===")
        Xt = self._data["X_train"]
        Xv = self._data["X_val"]
        yt = self._data["y_train"]
        yv = self._data["y_val"]

        # 用可用模型构建基学习器列表
        estimators = [
            ("rf", self.result.models["random_forest"].model),
        ]
        if self._has_xgboost and "xgboost" in self.result.models:
            estimators.append(("xgb", self.result.models["xgboost"].model))
        elif "ridge" in self.result.models:
            estimators.append(("ridge", self.result.models["ridge"].model))

        if len(estimators) < 2:
            logger.warning("已训练的模型不足 2 个，跳过集成学习。")
            return

        ensemble = BlueberryEnsemble()
        ensemble.fit(Xt, yt, estimators=estimators)
        y_pred = ensemble.predict(Xv)
        metrics = ensemble.evaluate(yv, y_pred)
        logger.info("Stacking 集成: R²=%.4f RMSE=%.4f", metrics["r2"], metrics["rmse"])
        self.result.metrics["Stacking 集成"] = metrics

        cv_res = cross_validate(ensemble.model, Xt, yt, cv=CV_FOLDS)
        self.result.cv_results["Stacking 集成"] = cv_res

        self.result.models["ensemble"] = ensemble

        plot_residuals(yv.values, y_pred, "Stacking 集成")
        plot_actual_vs_predicted(yv.values, y_pred, "Stacking 集成")

    def _step_compare(self):
        """步骤 9：模型效果对比。"""
        logger.info("=== 步骤 9：模型对比 ===")
        comparison = summarize_models(self.result.metrics)
        self.result.comparison_table = comparison
        logger.info("模型排名（按 RMSE）：\n%s", comparison.to_string())

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
        """步骤 10：业务建议与测试集预测。"""
        logger.info("=== 步骤 10：业务建议与测试集预测 ===")
        best_name = self.result.comparison_table.index[0]
        best_model = self._get_best_model_for_prediction(best_name)

        test_X = self._data["test_X_scaled"]
        test_ids = self._data["test_ids"]
        y_pred_test = best_model.predict(test_X)

        pred_df = pd.DataFrame({
            "id": test_ids,
            "predicted_yield": y_pred_test,
        })
        pred_df.to_csv(PREDICTION_PATH, index=False)
        logger.info("测试集预测结果已保存至 %s（%d 行）", PREDICTION_PATH, len(pred_df))

        report = self._generate_summary_report()
        report_path = os.path.join(FIGURES_DIR, "analysis_summary.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info("分析总结报告已保存至 %s", report_path)

    def _get_best_model_for_prediction(self, name: str):
        """将对比表中的模型名映射到实际模型对象。

        Parameters
        ----------
        name : str
            模型名称。

        Returns
        -------
        object
            可用于预测的模型对象。
        """
        mapping = {
            "岭回归 (Ridge)": self.result.models.get("ridge"),
            "随机森林 (RF)": self.result.models.get("random_forest"),
            "XGBoost": self.result.models.get("xgboost"),
            "Stacking 集成": self.result.models.get("ensemble"),
        }
        model = mapping.get(name)
        if model is None:
            model = (
                self.result.models.get("random_forest")
                or self.result.models.get("ridge")
            )
        return model

    def _generate_summary_report(self) -> str:
        """生成分析总结报告。

        Returns
        -------
        str
            格式化的报告文本。
        """
        used_models = list(self.result.metrics.keys())
        model_list = "、".join(used_models)
        lines = [
            "=" * 60,
            "  野生蓝莓产量预测 - 分析总结报告",
            "=" * 60,
            "",
            "一、问题定义",
            "   基于温度、降雨等环境因子，以及克隆株大小和授粉蜂密度，",
            "   预测野生蓝莓产量。为数据驱动的农业决策提供支撑：",
            "   包括最优种植地点选择、授粉管理优化和产量预测投资规划。",
            "",
            "二、数据概况",
            f"   训练样本数: {len(self._data['y_train']) + len(self._data['y_val'])}",
            f"   特征数: 16 个数值特征（克隆株大小、4 种蜂密度、6 个温度、2 个降雨、3 个果实指标）",
            f"   目标变量: yield（蓝莓产量，连续值）",
            f"   测试样本数: {len(self._data['test_ids'])}",
            "",
            "三、核心发现",
        ]

        if self.result.feature_importance is not None:
            lines.append("   Top 5 最重要特征：")
            for _, row in self.result.feature_importance.head(5).iterrows():
                lines.append(f"     - {row['feature']}: {row['importance']:.4f}")

        lines.extend([
            "",
            f"四、模型表现对比（按 RMSE 排序）  [{model_list}]",
        ])
        comp = self.result.comparison_table
        for name, row in comp.iterrows():
            lines.append(f"     {name}: R²={row['r2']:.4f}  RMSE={row['rmse']:.4f}  MAE={row['mae']:.4f}  MAPE={row['mape']:.2f}%")

        lines.extend([
            "",
            "五、交叉验证结果",
        ])
        for name, cv in self.result.cv_results.items():
            lines.append(f"     {name}: CV {CV_FOLDS}折 R² = {cv['cv_mean']:.4f} ± {cv['cv_std']:.4f}")

        lines.extend([
            "",
            "六、聚类分析",
            f"     K-Means 聚类识别出 {len(self.result.cluster_profiles)} 种独特的种植条件类型。",
            "     详见 cluster_business_report.txt 的业务解读。",
            "",
            "七、业务优化建议",
            "     - 授粉蜂密度是产量主导因素，优先加大授粉管理投入。",
            "     - 花期温度显著影响产量，应选择温度条件适宜（冷暖适中）的种植地点。",
            "     - 克隆株大小优化：高产聚类具有特定的克隆面积范围，可参考推广。",
            "     - 数据驱动的产量预测可有效降低蓝莓种植投资风险。",
            "",
            "八、创新点与改进",
            f"     - 多模型对比：{model_list}。",
            "     - PCA 降维解决特征共线性问题（VIF > 10000 的温度特征被有效压缩）。",
            "     - K-Means 聚类与业务画像结合，提供可落地的营销建议。",
            "     - 全模型自动交叉验证，确保评估结果稳健可靠。",
            "     - 模型持久化与命令行接口，支持生产级部署。",
            "     - 可选依赖机制，未安装 xgboost 时自动降级运行。",
            "",
            "=" * 60,
            "  由 BlueberryPipeline 自动生成",
            "=" * 60,
        ])
        return "\n".join(lines)
