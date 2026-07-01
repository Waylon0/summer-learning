"""Tests for data preprocessing module."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.data.loader import load_all, load_test, load_train
from src.data.preprocessor import DataPreprocessor
from src.config import NUMERIC_FEATURES, TARGET


def test_load_train():
    df = load_train()
    assert df is not None
    assert len(df) > 0
    assert TARGET in df.columns
    assert "id" in df.columns or "Id" in df.columns or "ID" in df.columns


def test_load_test():
    df = load_test()
    assert df is not None
    assert len(df) > 0
    assert TARGET not in df.columns


def test_load_all():
    train, test = load_all()
    assert len(train) > len(test)


def test_preprocessor_inspect():
    preprocessor = DataPreprocessor()
    df = load_train()
    info = preprocessor.inspect(df)
    assert "shape" in info
    assert "missing" in info
    assert "describe" in info


def test_preprocessor_clean():
    preprocessor = DataPreprocessor()
    df = load_train()
    cleaned = preprocessor.clean(df)
    assert "id" not in cleaned.columns
    assert len(cleaned) <= len(df)


def test_preprocessor_clean_keep_id():
    preprocessor = DataPreprocessor()
    df = load_train()
    cleaned = preprocessor.clean(df, drop_id=False)
    assert "id" in cleaned.columns


def test_split_features_target():
    preprocessor = DataPreprocessor()
    df = load_train()
    cleaned = preprocessor.clean(df)
    X, y = preprocessor.split_features_target(cleaned)
    assert X.shape[1] == len(NUMERIC_FEATURES)
    assert y is not None
    assert len(X) == len(y)


def test_split_features_target_no_yield():
    preprocessor = DataPreprocessor()
    df = load_test()
    cleaned = preprocessor.clean(df)
    X, y = preprocessor.split_features_target(cleaned)
    assert y is None


def test_scale():
    preprocessor = DataPreprocessor()
    df = load_train()
    cleaned = preprocessor.clean(df)
    X, _ = preprocessor.split_features_target(cleaned)
    X_scaled = preprocessor.scale(X, fit=True)
    assert X_scaled.shape == X.shape
    means = X_scaled.mean()
    assert abs(means.mean()) < 0.1


def test_train_val_split():
    preprocessor = DataPreprocessor()
    df = load_train()
    cleaned = preprocessor.clean(df)
    X, y = preprocessor.split_features_target(cleaned)
    X_scaled = preprocessor.scale(X, fit=True)
    X_train, X_val, y_train, y_val = preprocessor.train_val_split(X_scaled, y)
    assert len(X_train) > len(X_val)
    assert len(y_train) > len(y_val)
    assert len(X_train) + len(X_val) == len(X)


def test_pipeline():
    preprocessor = DataPreprocessor()
    df = load_train()
    X_train, X_val, y_train, y_val = preprocessor.pipeline(df)
    assert X_train is not None
    assert X_val is not None
    assert y_train is not None
    assert y_val is not None
    assert len(X_train) + len(X_val) == len(df)
