"""数据加载工具模块。"""

import pandas as pd

from src.config import TRAIN_PATH, TEST_PATH


def load_train() -> pd.DataFrame:
    """加载训练数据集，列名自动转为小写。

    Returns
    -------
    pd.DataFrame
        训练数据（15289 行 x 18 列，含 yield 和 id 列）。
    """
    df = pd.read_csv(TRAIN_PATH)
    df.columns = df.columns.str.lower().str.strip()
    return df


def load_test() -> pd.DataFrame:
    """加载测试数据集，列名自动转为小写。

    Returns
    -------
    pd.DataFrame
        测试数据（10194 行 x 17 列，不含 yield 列）。
    """
    df = pd.read_csv(TEST_PATH)
    df.columns = df.columns.str.lower().str.strip()
    return df


def load_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    """同时加载训练集和测试集。

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (训练集, 测试集)。
    """
    return load_train(), load_test()
