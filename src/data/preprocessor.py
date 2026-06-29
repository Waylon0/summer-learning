import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from src.config import NUMERIC_FEATURES, TARGET, TEST_SIZE, RANDOM_STATE
from sklearn.model_selection import train_test_split


class DataPreprocessor:
    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.feature_names = None

    def inspect(self, df: pd.DataFrame) -> dict:
        return {
            "shape": df.shape,
            "dtypes": df.dtypes.to_dict(),
            "missing": df.isnull().sum().to_dict(),
            "duplicated": int(df.duplicated().sum()),
            "describe": df.describe(),
        }

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.drop_duplicates(inplace=True)
        if "id" in df.columns:
            df.drop(columns=["id"], inplace=True)
        return df

    def split_features_target(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.Series]:
        X = df[NUMERIC_FEATURES].copy()
        y = df[TARGET].copy() if TARGET in df.columns else None
        return X, y

    def scale(self, X: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        self.feature_names = X.columns.tolist()
        if fit:
            scaled = self.scaler.fit_transform(X)
        else:
            scaled = self.scaler.transform(X)
        return pd.DataFrame(scaled, columns=self.feature_names, index=X.index)

    def train_val_split(
        self, X: pd.DataFrame, y: pd.Series
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        return train_test_split(
            X, y, test_size=TEST_SIZE, random_state=self.random_state
        )

    def pipeline(self, df: pd.DataFrame):
        df_clean = self.clean(df)
        X, y = self.split_features_target(df_clean)
        X_scaled = self.scale(X, fit=True)
        if y is not None:
            X_train, X_val, y_train, y_val = self.train_val_split(X_scaled, y)
            return X_train, X_val, y_train, y_val
        return X_scaled, None
