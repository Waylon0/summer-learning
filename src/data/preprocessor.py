"""Data preprocessing: cleaning, scaling, splitting."""

import logging

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.config import NUMERIC_FEATURES, RANDOM_STATE, TEST_SIZE, TARGET

logger = logging.getLogger("blueberry")


class DataPreprocessor:
    """Handles data inspection, cleaning, scaling, and train/val splitting."""

    def __init__(self, random_state: int = RANDOM_STATE):
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.feature_names: list[str] | None = None

    def inspect(self, df: pd.DataFrame) -> dict:
        """Return summary statistics of the dataframe.

        Parameters
        ----------
        df : pd.DataFrame
            Input dataframe.

        Returns
        -------
        dict
            Keys: shape, dtypes, missing, duplicated, describe.
        """
        return {
            "shape": df.shape,
            "dtypes": df.dtypes.to_dict(),
            "missing": df.isnull().sum().to_dict(),
            "duplicated": int(df.duplicated().sum()),
            "describe": df.describe(),
        }

    def clean(self, df: pd.DataFrame, drop_id: bool = True) -> pd.DataFrame:
        """Drop duplicates and optionally the 'id' column.

        Parameters
        ----------
        df : pd.DataFrame
            Input dataframe.
        drop_id : bool
            Whether to drop the 'id' column.

        Returns
        -------
        pd.DataFrame
            Cleaned dataframe.
        """
        df = df.copy()
        n_before = len(df)
        df.drop_duplicates(inplace=True)
        n_dup = n_before - len(df)
        if n_dup > 0:
            logger.info("Removed %d duplicate rows", n_dup)
        if drop_id and "id" in df.columns:
            df.drop(columns=["id"], inplace=True)
        return df

    def split_features_target(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.Series | None]:
        """Split dataframe into feature matrix X and target vector y.

        Parameters
        ----------
        df : pd.DataFrame
            Dataframe containing feature columns and optionally the target.

        Returns
        -------
        tuple
            (X, y) where y is None if TARGET column is absent (test data).
        """
        X = df[NUMERIC_FEATURES].copy()
        y = df[TARGET].copy() if TARGET in df.columns else None
        return X, y

    def scale(self, X: pd.DataFrame, fit: bool = True) -> pd.DataFrame:
        """Apply StandardScaler to features.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix.
        fit : bool
            If True, call fit_transform; otherwise transform only.

        Returns
        -------
        pd.DataFrame
            Scaled features with preserved column names and index.
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
        """Split data into training and validation sets.

        Parameters
        ----------
        X : pd.DataFrame
            Feature matrix.
        y : pd.Series
            Target vector.

        Returns
        -------
        tuple
            (X_train, X_val, y_train, y_val).
        """
        return train_test_split(
            X, y, test_size=TEST_SIZE, random_state=self.random_state
        )

    def pipeline(self, df: pd.DataFrame, drop_id: bool = True):
        """Run full preprocessing pipeline.

        Parameters
        ----------
        df : pd.DataFrame
            Raw dataframe.
        drop_id : bool
            Whether to drop the 'id' column.

        Returns
        -------
        tuple
            (X_train, X_val, y_train, y_val) if target present,
            otherwise (X_scaled, None).
        """
        df_clean = self.clean(df, drop_id=drop_id)
        X, y = self.split_features_target(df_clean)
        X_scaled = self.scale(X, fit=True)
        if y is not None:
            X_train, X_val, y_train, y_val = self.train_val_split(X_scaled, y)
            return X_train, X_val, y_train, y_val
        return X_scaled, None
