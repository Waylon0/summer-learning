import pandas as pd
from src.config import TRAIN_PATH, TEST_PATH


def load_train() -> pd.DataFrame:
    df = pd.read_csv(TRAIN_PATH)
    df.columns = df.columns.str.lower().str.strip()
    return df


def load_test() -> pd.DataFrame:
    df = pd.read_csv(TEST_PATH)
    df.columns = df.columns.str.lower().str.strip()
    return df


def load_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_train(), load_test()
