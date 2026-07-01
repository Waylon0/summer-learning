"""Data loading utilities."""

import pandas as pd

from src.config import TRAIN_PATH, TEST_PATH


def load_train() -> pd.DataFrame:
    """Load training dataset with lowercased column names.

    Returns
    -------
    pd.DataFrame
        Training data (15289 rows x 18 columns including 'yield' and 'id').
    """
    df = pd.read_csv(TRAIN_PATH)
    df.columns = df.columns.str.lower().str.strip()
    return df


def load_test() -> pd.DataFrame:
    """Load test dataset with lowercased column names.

    Returns
    -------
    pd.DataFrame
        Test data (10194 rows x 17 columns, without 'yield').
    """
    df = pd.read_csv(TEST_PATH)
    df.columns = df.columns.str.lower().str.strip()
    return df


def load_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load both training and test datasets.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        (train_df, test_df).
    """
    return load_train(), load_test()
