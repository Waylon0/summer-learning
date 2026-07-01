"""数据预处理：清洗、标准化、训练/验证集划分。"""

import logging

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.config import NUMERIC_FEATURES, RANDOM_STATE, TEST_SIZE, TARGET

logger = logging.getLogger("blueberry")


class DataPreprocessor:
    """数据预处理器：数据探查、清洗、标准化、划分。"""

    def __init__(self, random_state: int = RANDOM_STATE):
        """初始化预处理器。

        Parameters
        ----------
        random_state : int
            随机种子，确保结果可复现。
        """
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.feature_names: list[str] | None = None

    def inspect(self, df: pd.DataFrame) -> dict:
        """返回数据集的汇总统计信息。

        Parameters
        ----------
        df : pd.DataFrame
            待探查的数据框。

        Returns
        -------
        dict
            包含 shape、dtypes、missing、duplicated、describe 等键。
        """
        return {
            "shape": df.shape,
            "dtypes": df.dtypes.to_dict(),
            "missing": df.isnull().sum().to_dict(),
            "duplicated": int(df.duplicated().sum()),
            "describe": df.describe(),
        }

    def clean(self, df: pd.DataFrame, drop_id: bool = True) -> pd.DataFrame:
        """删除重复行，并可选择删除 id 列。

        Parameters
        ----------
        df : pd.DataFrame
            待清洗的数据框。
        drop_id : bool
            是否删除 id 列，默认 True。

        Returns
        -------
        pd.DataFrame
            清洗后的数据框。
        """
        df = df.copy()
        n_before = len(df)
        df.drop_duplicates(inplace=True)
        n_dup = n_before - len(df)
        if n_dup > 0:
            logger.info("已删除 %d 行重复数据", n_dup)
        if drop_id and "id" in df.columns:
            df.drop(columns=["id"], inplace=True)
        return df

    def split_features_target(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.Series | None]:
        """拆分为特征矩阵 X 和目标向量 y。

        Parameters
        ----------
        df : pd.DataFrame
            包含特征列和（可选的）目标列的数据框。

        Returns
        -------
        tuple
            (X, y)。若目标列不存在（如测试集），则 y 为 None。
        """
        X = df[NUMERIC_FEATURES].copy()
        y = df[TARGET].copy() if TARGET in df.columns else None
        return X, y

    def scale(self, X: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        """使用 StandardScaler 进行标准化。

        Parameters
        ----------
        X : pd.DataFrame
            特征矩阵。
        fit : bool
            若为 True 则调用 fit_transform，否则仅调用 transform。

        Returns
        -------
        pd.DataFrame
            标准化后的特征，保留原始列名和索引。
        """
        self.feature_names = list(X.columns)
        if fit:
            scaled = self.scaler.fit_transform(X)
        else:
            scaled = self.scaler.transform(X)
        return pd.DataFrame(scaled, columns=self.feature_names, index=X.index)

    def train_val_split(
        self, X: pd.DataFrame, y: pd.Series
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """划分为训练集和验证集。

        Parameters
        ----------
        X : pd.DataFrame
            特征矩阵。
        y : pd.Series
            目标向量。

        Returns
        -------
        tuple
            (X_train, X_val, y_train, y_val)。
        """
        return train_test_split(
            X, y, test_size=TEST_SIZE, random_state=self.random_state
        )

    def pipeline(self, df: pd.DataFrame, drop_id: bool = True):
        """执行完整预处理流水线。

        Parameters
        ----------
        df : pd.DataFrame
            原始数据框。
        drop_id : bool
            是否删除 id 列。

        Returns
        -------
        tuple
            若含目标列则返回 (X_train, X_val, y_train, y_val)，
            否则返回 (X_scaled, None)。
        """
        df_clean = self.clean(df, drop_id=drop_id)
        X, y = self.split_features_target(df_clean)
        X_scaled = self.scale(X, fit=True)
        if y is not None:
            X_train, X_val, y_train, y_val = self.train_val_split(X_scaled, y)
            return X_train, X_val, y_train, y_val
        return X_scaled, None
