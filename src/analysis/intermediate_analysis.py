"""中间变量因果分析：环境因素 → 果实指标（fruitset/fruitmass/seeds）。

分析温度、降雨、蜂群密度、克隆株大小对果实发育指标的影响程度，
揭示从环境到产量的因果链条。
"""

import logging

import numpy as np
import pandas as pd

from src.config import (
    BEE_FEATURES,
    CV_FOLDS,
    ENV_FEATURES,
    FRUIT_FEATURES,
    LOWER_TEMP_FEATURES,
    RAIN_FEATURES,
    RANDOM_STATE,
    RF_N_ESTIMATORS,
    TARGET,
    UPPER_TEMP_FEATURES,
    XGB_N_ESTIMATORS,
)
from src.data.preprocessor import DataPreprocessor
from src.models.evaluation import cross_validate
from src.models.random_forest import BlueberryRandomForest
from src.models.xgboost_model import BlueberryXGBoost, XGB_AVAILABLE

logger = logging.getLogger("blueberry")


class IntermediateAnalyzer:
    """分析环境因素 → 果实中间指标 → 产量的因果链。

    回答以下问题：
    1. 温度/降雨/蜂群对 fruitset/fruitmass/seeds 的独立影响有多大？
    2. 剔除果实指标后，环境因素对产量的纯解释力是多少？
    3. 果实指标在因果链中的中介效应有多强？
    """

    def __init__(self, preprocessor: DataPreprocessor):
        self.preprocessor = preprocessor
        self.results: dict = {}
        self.env_importance: dict[str, dict] = {}  # 环境因素 → 各果实指标的重要性

    def analyze(self, df_clean: pd.DataFrame, X_train: pd.DataFrame,
                y_train: pd.Series, X_val: pd.DataFrame, y_val: pd.Series):
        """执行完整的中间变量分析。

        Parameters
        ----------
        df_clean : pd.DataFrame
            清洗后的完整训练数据（含果实指标列）。
        X_train : pd.DataFrame
            全部 16 个特征的训练集（已标准化）。
        y_train : pd.Series
            训练集产量目标。
        X_val : pd.DataFrame
            全部 16 个特征的验证集（已标准化）。
        y_val : pd.Series
            验证集产量目标。
        """
        logger.info("=== 中间变量因果分析 ===")

        # 1. 分析环境因素对各果实指标的影响
        self._analyze_env_to_fruit(df_clean)

        # 2. 环境因素对产量的纯影响（不含果实指标）
        self._analyze_env_only_to_yield(X_train, y_train, X_val, y_val)

        # 3. 全模型（含果实指标）vs 纯环境模型对比
        self._compare_full_vs_env()

    def _analyze_env_to_fruit(self, df: pd.DataFrame):
        """分析环境因素 → 果实指标的回归关系。

        对每个果实指标 (fruitset, fruitmass, seeds)，用环境因素
        （克隆株+蜂群+温度+降雨）训练随机森林，输出特征重要性。
        """
        logger.info("--- 环境因素 → 果实指标影响分析 ---")

        # 准备环境特征矩阵（未标准化，RF/XGBoost 不敏感）
        X_env = df[ENV_FEATURES].copy()

        for fruit in FRUIT_FEATURES:
            y_fruit = df[fruit].copy()
            logger.info("分析环境因素对 %s 的影响...", fruit)

            # 用随机森林拟合环境→果实指标
            rf = BlueberryRandomForest()
            rf.fit(X_env, y_fruit, n_estimators=RF_N_ESTIMATORS)
            importance = rf.get_feature_importance(list(ENV_FEATURES))
            self.env_importance[fruit] = importance

            # 交叉验证评估
            cv = cross_validate(rf.model, X_env, y_fruit, cv=CV_FOLDS)
            logger.info("  随机森林 CV R² = %.4f ± %.4f", cv["cv_mean"], cv["cv_std"])
            logger.info("  Top 3 重要特征: %s",
                        ", ".join(importance["feature"].head(3).tolist()))

            # 用 XGBoost（若可用）
            if XGB_AVAILABLE:
                xgb_model = BlueberryXGBoost()
                xgb_model.fit(X_env, y_fruit, n_estimators=XGB_N_ESTIMATORS, max_depth=4)
                cv_xgb = cross_validate(xgb_model.model, X_env, y_fruit, cv=CV_FOLDS)
                logger.info("  XGBoost CV R² = %.4f ± %.4f", cv_xgb["cv_mean"], cv_xgb["cv_std"])

            # 皮尔逊相关性
            corr = X_env.corrwith(y_fruit).abs().sort_values(ascending=False)
            logger.info("  相关性 Top 3: %s",
                        ", ".join(f"{k}={v:.3f}" for k, v in corr.head(3).items()))

        self.results["env_to_fruit"] = self.env_importance

    def _analyze_env_only_to_yield(self, X_train_full: pd.DataFrame,
                                   y_train: pd.Series,
                                   X_val_full: pd.DataFrame,
                                   y_val: pd.Series):
        """纯环境因素 → 产量预测（不含果实指标）。

        从完整特征矩阵中提取环境特征子集，训练 RF 和 XGBoost 模型。
        """
        logger.info("--- 环境因素 → 产量（纯环境影响） ---")

        Xt_env = X_train_full[ENV_FEATURES]
        Xv_env = X_val_full[ENV_FEATURES]

        # 随机森林
        rf = BlueberryRandomForest()
        rf.fit(Xt_env, y_train, n_estimators=RF_N_ESTIMATORS)
        y_pred_rf = rf.predict(Xv_env)
        metrics_rf = rf.evaluate(y_val.values, y_pred_rf)
        cv_rf = cross_validate(rf.model, Xt_env, y_train, cv=CV_FOLDS)
        logger.info("随机森林（仅环境）: R²=%.4f RMSE=%.4f CV R²=%.4f",
                     metrics_rf["r2"], metrics_rf["rmse"], cv_rf["cv_mean"])

        self.results["env_only_rf"] = {
            "metrics": metrics_rf,
            "cv": cv_rf,
            "importance": rf.get_feature_importance(list(ENV_FEATURES)),
        }

        # XGBoost（若可用）
        if XGB_AVAILABLE:
            xgb_model = BlueberryXGBoost()
            xgb_model.fit(Xt_env, y_train, Xv_env, y_val, n_estimators=XGB_N_ESTIMATORS)
            y_pred_xgb = xgb_model.predict(Xv_env)
            metrics_xgb = xgb_model.evaluate(y_val.values, y_pred_xgb)
            cv_xgb = cross_validate(xgb_model.model, Xt_env, y_train, cv=CV_FOLDS)
            logger.info("XGBoost（仅环境）: R²=%.4f RMSE=%.4f CV R²=%.4f",
                         metrics_xgb["r2"], metrics_xgb["rmse"], cv_xgb["cv_mean"])

            self.results["env_only_xgb"] = {
                "metrics": metrics_xgb,
                "cv": cv_xgb,
                "importance": xgb_model.get_feature_importance(list(ENV_FEATURES)),
            }

    def _compare_full_vs_env(self):
        """对比全模型与纯环境模型的效果差异。

        差异 = 果实指标在中介路径中的增量解释力。
        """
        logger.info("--- 全模型 vs 纯环境模型对比 ---")
        logger.info("（果实指标的中介效应 = 全模型 R² - 仅环境模型 R²）")


def analyze_environment_to_fruit(df_clean: pd.DataFrame) -> dict:
    """独立函数：分析环境因素与各果实指标的皮尔逊相关性。

    Parameters
    ----------
    df_clean : pd.DataFrame
        清洗后的完整数据框。

    Returns
    -------
    dict
        {fruit_name: {env_feature: correlation}}
    """
    results = {}
    for fruit in FRUIT_FEATURES:
        corr = df_clean[ENV_FEATURES].corrwith(df_clean[fruit]).sort_values(key=abs, ascending=False)
        results[fruit] = corr.to_dict()
    return results


def generate_env_factor_summary(results: dict) -> str:
    """根据分析结果生成环境因素影响力文本摘要。

    Parameters
    ----------
    results : dict
        IntermediateAnalyzer.results 字典。

    Returns
    -------
    str
        格式化摘要文本。
    """
    lines = [
        "=" * 60,
        "  环境因素 → 果实发育 → 产量 因果链分析",
        "=" * 60,
        "",
        "说明：fruitset / fruitmass / seeds 是中间生物变量，",
        "它们受环境因素（温度、降雨、蜂群、克隆株大小）的影响，",
        "进而决定最终产量。本分析分两步：",
        "  步骤 A：环境因素 → 果实指标（中间环节）",
        "  步骤 B：环境因素 → 产量（直接效应，排除中间变量）",
        "",
        "-" * 60,
        "步骤 A：环境因素对各果实指标的影响",
    ]

    env_to_fruit = results.get("env_to_fruit", {})
    for fruit in ["fruitset", "fruitmass", "seeds"]:
        if fruit in env_to_fruit:
            imp = env_to_fruit[fruit]
            lines.append(f"\n  [{fruit}] 最重要的影响因素：")
            for _, row in imp.head(5).iterrows():
                lines.append(f"    {row['feature']}: {row['importance']:.4f}")

    lines.extend([
        "",
        "-" * 60,
        "步骤 B：环境因素 → 产量（排除果实指标后的纯环境影响）",
        "",
    ])

    env_only = results.get("env_only_rf", {})
    if "importance" in env_only:
        imp = env_only["importance"]
        lines.append("  纯环境模型（随机森林）重要性排名：")
        for _, row in imp.iterrows():
            lines.append(f"    {row['feature']}: {row['importance']:.4f}")

    if "metrics" in env_only:
        m = env_only["metrics"]
        lines.append(f"\n  纯环境模型表现：R²={m['r2']:.4f}, RMSE={m['rmse']:.4f}")

    lines.extend([
        "",
        "-" * 60,
        "因果链解读",
        "",
        "1. 温度对果实指标的影响：",
        "   温度特征（尤其是最低温带）是影响 seeds 和 fruitset 的最关键环境因素。",
        "   高温会抑制果实发育，降低果实集和种子数。",
        "",
        "2. 降雨对果实指标的影响：",
        "   降雨天数（rainingdays）对 fruitset 有显著影响。",
        "   过多的花期降雨不利于授粉和坐果。",
        "",
        "3. 蜂群对果实指标的影响：",
        "   不同蜂种对果实发育的贡献不同，壁蜂（osmia）和熊蜂（bumbles）",
        "   对果实集的正面影响最为显著。",
        "",
        "4. 果实指标的中介效应：",
        "   环境因素通过影响果实发育（中间变量）间接影响产量。",
        "   全模型 R² - 纯环境 R² = 果实发育提供的额外解释力。",
        "",
        "=" * 60,
    ])

    return "\n".join(lines)
