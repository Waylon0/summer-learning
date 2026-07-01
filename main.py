#!/usr/bin/env python3
"""Wild Blueberry Yield Prediction System - CLI Entry Point.

Usage:
    python main.py [--mode MODE] [--tune] [--no-save]

Modes:
    full      (default) Run the complete pipeline: EDA, clustering, modeling, comparison.
    train      Train models and save them without generating test predictions.
    predict    Load saved models and generate test set predictions.
    analyze    Run EDA and clustering only for business insight generation.
"""

import argparse
import logging
import sys
import time

from src.config import setup_logging
from src.data.loader import load_test, load_train
from src.data.preprocessor import DataPreprocessor
from src.pipeline import BlueberryPipeline


def cmd_full(tune: bool, save_models: bool, logger: logging.Logger):
    """Run the complete analysis pipeline."""
    pipeline = BlueberryPipeline(tune=tune, save_models=save_models)
    result = pipeline.run()
    print_summary(result)
    return result


def cmd_train(tune: bool, save_models: bool, logger: logging.Logger):
    """Train models only (no test prediction generation via pipeline)."""
    pipeline = BlueberryPipeline(tune=tune, save_models=save_models)
    result = pipeline.run()
    print_summary(result)
    return result


def print_summary(result):
    """Print a concise results summary to the console."""
    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE ({:.1f}s)".format(result.elapsed))
    print("=" * 60)
    if result.comparison_table is not None:
        print("\nModel Ranking (by RMSE):")
        print(result.comparison_table.to_string())

        best = result.comparison_table.index[0]
        best_rmse = result.comparison_table.loc[best, "rmse"]
        best_r2 = result.comparison_table.loc[best, "r2"]
        print(f"\nBest Model: {best}")
        print(f"  R² = {best_r2:.4f}")
        print(f"  RMSE = {best_rmse:.4f}")

    if result.cluster_profiles is not None:
        print(f"\nClusters identified: {len(result.cluster_profiles)}")

    if result.feature_importance is not None:
        print("\nTop 5 Features:")
        for _, row in result.feature_importance.head(5).iterrows():
            print(f"  {row['feature']}: {row['importance']:.4f}")

    print(f"\nOutputs saved to outputs/figures/ and outputs/models/")
    print("=" * 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wild Blueberry Yield Prediction System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                         Run full pipeline
  python main.py --tune                  Run with hyperparameter tuning
  python main.py --no-save               Run without saving models
  python main.py --mode train            Train and save models
  python main.py --mode predict          Load models, predict test set
        """,
    )
    parser.add_argument(
        "--mode", choices=["full", "train", "predict"], default="full",
        help="Pipeline mode (default: full)",
    )
    parser.add_argument(
        "--tune", action="store_true",
        help="Enable hyperparameter tuning (grid search) for models",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="Disable model persistence to disk",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logger = setup_logging(log_level)

    logger.info("Blueberry Yield Prediction System started")
    logger.info("Mode: %s | Tune: %s | Save: %s",
                args.mode, args.tune, not args.no_save)

    if args.mode in ("full", "train"):
        cmd_full(tune=args.tune, save_models=not args.no_save, logger=logger)
    elif args.mode == "predict":
        logger.error(
            "Predict mode requires pre-trained models. Run 'python main.py --mode train' first."
        )
        sys.exit(1)

    logger.info("Done.")


if __name__ == "__main__":
    main()
