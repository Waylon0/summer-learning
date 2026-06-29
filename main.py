"""Wild Blueberry Yield Prediction Analysis - Main Entry Point."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.loader import load_train
from src.data.preprocessor import DataPreprocessor
from src.models.linear_regression import BlueberryLinearRegression, compute_vif
from src.models.random_forest import BlueberryRandomForest
from src.models.clustering import BlueberryClustering
from src.models.evaluation import compare_models
from src.features.engineering import apply_pca
from src.visualization.plots import (
    plot_correlation_heatmap,
    plot_elbow,
    plot_cluster_scatter,
    plot_residuals,
    plot_feature_importance,
    plot_actual_vs_predicted,
    plot_model_comparison,
)
import pandas as pd


def run_pipeline():
    print("=" * 60)
    print("  Wild Blueberry Yield Prediction Analysis")
    print("=" * 60)

    train = load_train()
    print(f"\n[1/6] Data loaded: {train.shape}")

    preprocessor = DataPreprocessor()
    df_clean = preprocessor.clean(train)
    X, y = preprocessor.split_features_target(df_clean)
    X_scaled = preprocessor.scale(X, fit=True)
    X_train, X_val, y_train, y_val = preprocessor.train_val_split(X_scaled, y)
    print(f"[2/6] Data preprocessed: train={X_train.shape}, val={X_val.shape}")

    df_full = pd.concat([X, y.rename("yield")], axis=1)
    plot_correlation_heatmap(df_full)

    cluster = BlueberryClustering()
    results = cluster.find_optimal_k(X_scaled, range(2, 11))
    print(f"[3/6] Clustering: optimal K={results['best_k']} (silhouette={results['optimal_metrics']['silhouette']:.4f})")
    cluster.fit(X_scaled, k=results["best_k"])
    plot_elbow(results["inertias"], results["k_range"], results["best_k"])
    X_pca, _, _ = apply_pca(X_scaled, n_components=2)
    plot_cluster_scatter(X_pca.values, cluster.get_predictions())

    X_train_pca, pca_model, _ = apply_pca(X_train, variance_threshold=0.95)
    X_val_pca = pd.DataFrame(
        pca_model.transform(X_val),
        columns=[f"PC{i+1}" for i in range(X_train_pca.shape[1])],
        index=X_val.index,
    )
    print(f"[4/6] PCA: {X_train.shape[1]} features -> {X_train_pca.shape[1]} components")

    lr = BlueberryLinearRegression()
    lr.fit_ridge(X_train_pca, y_train, alpha=1.0)
    y_pred_lr = lr.predict(X_val_pca)
    lr_metrics = lr.evaluate(y_val, y_pred_lr)
    print(f"[5/6] Linear Regression: R²={lr_metrics['r2']:.4f}, RMSE={lr_metrics['rmse']:.4f}")

    rf = BlueberryRandomForest()
    rf.fit(X_train, y_train, n_estimators=200, max_depth=None)
    y_pred_rf = rf.predict(X_val)
    rf_metrics = rf.evaluate(y_val, y_pred_rf)
    print(f"[6/6] Random Forest:    R²={rf_metrics['r2']:.4f}, RMSE={rf_metrics['rmse']:.4f}")

    all_results = {
        "Linear Regression (Ridge)": lr_metrics,
        "Random Forest": rf_metrics,
    }
    comparison = compare_models(all_results)
    print(f"\n{'='*60}")
    print("Model Comparison:")
    print(comparison.to_string())
    print(f"{'='*60}")

    best = min(all_results, key=lambda k: all_results[k]["rmse"])
    print(f"\nBest model: {best}")

    plot_residuals(y_val.values, y_pred_lr)
    plot_actual_vs_predicted(y_val.values, y_pred_lr, "Linear Regression")
    plot_residuals(y_val.values, y_pred_rf)
    plot_actual_vs_predicted(y_val.values, y_pred_rf, "Random Forest")
    importance_df = rf.get_feature_importance(X_train.columns.tolist())
    plot_feature_importance(importance_df["feature"].tolist(), importance_df["importance"].values)
    plot_model_comparison(all_results, "r2")
    plot_model_comparison(all_results, "rmse")


if __name__ == "__main__":
    run_pipeline()
