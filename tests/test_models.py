"""Tests for model modules."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.data.loader import load_train
from src.data.preprocessor import DataPreprocessor
from src.models.clustering import BlueberryClustering
from src.models.ensemble import BlueberryEnsemble
from src.models.evaluation import compare_models, cross_validate, regression_metrics, summarize_models
from src.models.linear_regression import BlueberryLinearRegression, compute_vif
from src.models.random_forest import BlueberryRandomForest
from src.models.xgboost_model import BlueberryXGBoost


# ------------------------------------------------------------------ Fixtures


def _get_data():
    preprocessor = DataPreprocessor()
    df = load_train()
    X_train, X_val, y_train, y_val = preprocessor.pipeline(df)
    return X_train, X_val, y_train, y_val, preprocessor


# --- --------------------------------------------------------------- Clustering


def test_clustering_find_k():
    X_train, _, _, _, _ = _get_data()
    cluster = BlueberryClustering()
    results = cluster.find_optimal_k(X_train)
    assert 2 <= results["best_k"] <= 10
    assert len(results["inertias"]) == len(results["k_range"])


def test_clustering_fit():
    X_train, _, _, _, _ = _get_data()
    cluster = BlueberryClustering()
    cluster.fit(X_train, k=3)
    assert cluster.labels is not None
    assert len(cluster.labels) == len(X_train)


def test_clustering_profile():
    X_train, _, _, _, preprocessor = _get_data()
    df = load_train()
    cleaned = preprocessor.clean(df)
    X_full, y_full = preprocessor.split_features_target(cleaned)
    X_scaled = preprocessor.scale(X_full, fit=True)

    cluster = BlueberryClustering()
    cluster.fit(X_scaled, k=3)
    profiles = cluster.get_cluster_profiles(X_full, y_full)
    assert "yield_mean" in profiles.columns
    assert len(profiles) == 3


# ------------------------------------------------------------------ Linear Regression


def test_vif():
    X_train, _, _, _, _ = _get_data()
    vif = compute_vif(X_train)
    assert "VIF" in vif.columns
    assert len(vif) == X_train.shape[1]


def test_linear_ridge():
    X_train, X_val, y_train, y_val, _ = _get_data()
    lr = BlueberryLinearRegression()
    lr.fit_ridge(X_train, y_train, alpha=1.0)
    y_pred = lr.predict(X_val)
    metrics = lr.evaluate(y_val.values, y_pred)
    assert metrics["r2"] > -0.5
    assert metrics["rmse"] > 0


# ------------------------------------------------------------------ Random Forest


def test_rf_fit():
    X_train, X_val, y_train, y_val, _ = _get_data()
    rf = BlueberryRandomForest()
    rf.fit(X_train, y_train, n_estimators=50, max_depth=10)
    y_pred = rf.predict(X_val)
    metrics = rf.evaluate(y_val.values, y_pred)
    assert metrics["r2"] > 0
    assert metrics["rmse"] > 0


def test_rf_importance():
    X_train, _, y_train, _, _ = _get_data()
    rf = BlueberryRandomForest()
    rf.fit(X_train, y_train, n_estimators=50)
    imp = rf.get_feature_importance(list(X_train.columns))
    assert len(imp) == X_train.shape[1]
    assert imp["importance"].sum() > 0.99


# ------------------------------------------------------------------ XGBoost


def test_xgboost_fit():
    X_train, X_val, y_train, y_val, _ = _get_data()
    xgb_model = BlueberryXGBoost()
    xgb_model.fit(X_train, y_train, n_estimators=50, max_depth=4)
    y_pred = xgb_model.predict(X_val)
    metrics = xgb_model.evaluate(y_val.values, y_pred)
    assert metrics["r2"] > 0


# ------------------------------------------------------------------ Ensemble


def test_ensemble():
    X_train, X_val, y_train, y_val, _ = _get_data()
    rf = BlueberryRandomForest()
    rf.fit(X_train, y_train, n_estimators=50, max_depth=10)
    xgb_model = BlueberryXGBoost()
    xgb_model.fit(X_train, y_train, n_estimators=50, max_depth=4)

    ensemble = BlueberryEnsemble()
    ensemble.fit(X_train, y_train, estimators=[
        ("rf", rf.model), ("xgb", xgb_model.model),
    ])
    y_pred = ensemble.predict(X_val)
    metrics = ensemble.evaluate(y_val.values, y_pred)
    assert metrics["r2"] > 0


# ------------------------------------------------------------------ Evaluation


def test_regression_metrics():
    y_true = np.array([100, 200, 300])
    y_pred = np.array([105, 190, 310])
    m = regression_metrics(y_true, y_pred)
    assert m["r2"] > 0.9
    assert "mape" in m
    assert "explained_variance" in m


def test_cross_validate():
    X_train, _, y_train, _, _ = _get_data()
    rf = BlueberryRandomForest()
    rf.fit(X_train, y_train, n_estimators=50)
    cv = cross_validate(rf.model, X_train, y_train, cv=3)
    assert cv["cv_mean"] > 0
    assert len(cv["cv_scores"]) == 3


def test_compare_models():
    results = {
        "Model A": {"r2": 0.9, "rmse": 100},
        "Model B": {"r2": 0.8, "rmse": 150},
    }
    comp = compare_models(results)
    assert comp.shape == (2, 2)


def test_summarize_models():
    results = {
        "Model A": {"r2": 0.9, "rmse": 100},
        "Model B": {"r2": 0.8, "rmse": 150},
    }
    summary = summarize_models(results)
    assert summary.index[0] == "Model A"
