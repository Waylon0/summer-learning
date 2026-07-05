"""传统机器学习模型集合：覆盖 8 大类算法（全部基于 sklearn，零新增依赖）。

模型列表：
  - ElasticNet        (L1+L2 正则化线性回归)
  - SVR               (支持向量回归，RBF 核)
  - KNN               (K 近邻回归)
  - DecisionTree      (单棵决策树，基线)
  - ExtraTrees        (极端随机树，Bagging 变体)
  - GradientBoosting  (梯度提升树，sklearn 原生 GBDT)
  - AdaBoost          (自适应增强)
  - MLP               (多层感知机/神经网络)
"""

import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    AdaBoostRegressor,
    ExtraTreesRegressor,
    GradientBoostingRegressor,
)
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor

from src.config import CV_FOLDS, RANDOM_STATE

logger = logging.getLogger("blueberry")


def _safe_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """安全计算 MAPE。"""
    denom = np.where(np.abs(y_true) < 1e-8, 1.0, y_true)
    return float(np.mean(np.abs((y_true - y_pred) / denom)) * 100)


class BaseSklearnWrapper:
    """sklearn 模型通用包装器。"""

    def __init__(self, model, model_name: str):
        self.model = model
        self.model_name = model_name
        self.best_params: dict | None = None

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series):
        self.model.fit(X_train, y_train)
        logger.info("%s 训练完成", self.model_name)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X)

    def evaluate(self, y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
        return {
            "r2": float(r2_score(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": _safe_mape(y_true, y_pred),
        }

    def get_feature_importance(self, feature_names: list[str]) -> pd.DataFrame | None:
        """获取特征重要性（若模型支持）。"""
        if hasattr(self.model, "feature_importances_"):
            imp = pd.DataFrame({
                "feature": feature_names,
                "importance": self.model.feature_importances_,
            })
            return imp.sort_values("importance", ascending=False)
        elif hasattr(self.model, "coef_") and self.model.coef_ is not None:
            coef = self.model.coef_
            if coef.ndim > 1:
                coef = coef.ravel()
            imp = pd.DataFrame({
                "feature": feature_names,
                "importance": np.abs(coef),
            })
            return imp.sort_values("importance", ascending=False)
        return None


def create_elasticnet(alpha: float = 0.01, l1_ratio: float = 0.5) -> BaseSklearnWrapper:
    """ElasticNet: L1 + L2 正则化线性回归。

    结合了 Lasso（L1，特征选择）和 Ridge（L2，稳定系数）的优点。
    原理：min ||y-Xw||² + alpha*(l1_ratio*|w|₁ + (1-l1_ratio)*|w|²₂)
    """
    model = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, random_state=RANDOM_STATE, max_iter=5000)
    return BaseSklearnWrapper(model, "ElasticNet")


def create_svr(C: float = 1.0, gamma: str = "scale") -> BaseSklearnWrapper:
    """SVR: 支持向量回归（RBF 核）。

    原理：寻找一个 ε-管道，使得大部分样本落在管道内，同时最小化管道宽度。
    用于非线性回归，通过核函数映射到高维空间。
    """
    model = SVR(C=C, gamma=gamma, kernel="rbf")
    return BaseSklearnWrapper(model, "SVR (RBF)")


def create_knn(n_neighbors: int = 5, weights: str = "distance") -> BaseSklearnWrapper:
    """KNN: K 近邻回归。

    原理：对每个待预测样本，找到训练集中最近的 K 个邻居，用邻居目标值的
    加权平均作为预测。非参数方法，无需训练。
    """
    model = KNeighborsRegressor(n_neighbors=n_neighbors, weights=weights, n_jobs=-1)
    return BaseSklearnWrapper(model, "KNN")


def create_decision_tree(max_depth: int = 10) -> BaseSklearnWrapper:
    """DecisionTree: 单棵决策树回归基线。

    原理：递归地将特征空间划分为区域，每个区域赋予常数预测值。
    易于过拟合，通常作为树模型的性能下界。
    """
    model = DecisionTreeRegressor(max_depth=max_depth, random_state=RANDOM_STATE)
    return BaseSklearnWrapper(model, "决策树")


def create_extra_trees(n_estimators: int = 200) -> BaseSklearnWrapper:
    """ExtraTrees: 极端随机树（Random Forest 变体）。

    原理：与 RF 类似，但在每个节点的划分阈值也是随机选择的。
    比 RF 更随机，方差更低，通常训练更快。
    """
    model = ExtraTreesRegressor(
        n_estimators=n_estimators, random_state=RANDOM_STATE, n_jobs=-1,
    )
    return BaseSklearnWrapper(model, "ExtraTrees")


def create_gbdt(n_estimators: int = 200, learning_rate: float = 0.1,
                max_depth: int = 5) -> BaseSklearnWrapper:
    """GradientBoosting: sklearn 原生梯度提升树（GBDT）。

    原理：顺序构建多个弱学习器（小决策树），每棵树拟合前一棵树的残差。
    通过梯度下降方式最小化损失函数。
    XGBoost/LightGBM 是其工程优化版本。
    """
    model = GradientBoostingRegressor(
        n_estimators=n_estimators, learning_rate=learning_rate,
        max_depth=max_depth, random_state=RANDOM_STATE,
    )
    return BaseSklearnWrapper(model, "GBDT (sklearn)")


def create_adaboost(n_estimators: int = 200, learning_rate: float = 1.0) -> BaseSklearnWrapper:
    """AdaBoost: 自适应增强回归。

    原理：迭代地增加误分类（大残差）样本的权重，使后续弱学习器更关注
    之前难以拟合的样本。与 GBDT 不同，AdaBoost 通过样本权重而非残差来调整。
    """
    model = AdaBoostRegressor(
        n_estimators=n_estimators, learning_rate=learning_rate,
        random_state=RANDOM_STATE,
    )
    return BaseSklearnWrapper(model, "AdaBoost")


def create_mlp(hidden_layer_sizes: tuple = (100, 50, 25),
               max_iter: int = 500) -> BaseSklearnWrapper:
    """MLP: 多层感知机（前馈神经网络）。

    原理：通过多层全连接神经元和激活函数（ReLU），学习特征的复杂非线性组合。
    需要大量数据，对数据标准化敏感（本项目已做标准化）。
    """
    model = MLPRegressor(
        hidden_layer_sizes=hidden_layer_sizes, random_state=RANDOM_STATE,
        max_iter=max_iter, early_stopping=True, validation_fraction=0.1,
        n_iter_no_change=20,
    )
    return BaseSklearnWrapper(model, "MLP（神经网络）")


# ---- 批量创建函数 ----

def create_all_traditional_models() -> list[BaseSklearnWrapper]:
    """创建所有 sklearn 原生模型的列表。"""
    return [
        create_elasticnet(),
        create_svr(),
        create_knn(),
        create_decision_tree(),
        create_extra_trees(),
        create_gbdt(),
        create_adaboost(),
        create_mlp(),
    ]


MODEL_DESCRIPTIONS = {
    "ElasticNet": "ElasticNet — L1+L2 正则化线性回归，结合 Lasso 和 Ridge 优势",
    "SVR (RBF)": "SVR — 支持向量回归（RBF 核），寻找 ε-管道内最优拟合",
    "KNN": "KNN — K 近邻回归，用最近邻样本的加权平均作为预测",
    "决策树": "决策树 — 单棵决策树，递归划分特征空间作为模型基线",
    "ExtraTrees": "ExtraTrees — 极端随机树，比 RF 更随机、方差更低的 Bagging 变体",
    "GBDT (sklearn)": "GBDT — 梯度提升树（sklearn 原生），通过拟合残差迭代提升",
    "AdaBoost": "AdaBoost — 自适应增强，通过加权样本关注难拟合区域",
    "MLP（神经网络）": "MLP — 多层感知机/前馈神经网络，学习深层非线性特征组合",
}
