#!/usr/bin/env python3
"""野生蓝莓产量预测系统 - 命令行入口。

用法：
    python main.py [--mode MODE] [--tune] [--no-save]

模式：
    full      默认，运行完整流水线：EDA、聚类、建模、对比。
    train     训练并保存模型。
    predict   加载已保存模型，生成测试集预测。
    analyze   仅运行 EDA 和聚类分析，生成业务洞察。
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
    """运行完整分析流水线。"""
    pipeline = BlueberryPipeline(tune=tune, save_models=save_models)
    result = pipeline.run()
    print_summary(result)
    return result


def cmd_train(tune: bool, save_models: bool, logger: logging.Logger):
    """训练并保存模型。"""
    pipeline = BlueberryPipeline(tune=tune, save_models=save_models)
    result = pipeline.run()
    print_summary(result)
    return result


def print_summary(result):
    """在终端输出简洁的结果摘要。"""
    print("\n" + "=" * 60)
    print("  流水线执行完毕 ({:.1f}秒)".format(result.elapsed))
    print("=" * 60)
    if result.comparison_table is not None:
        print("\n模型排名（按 RMSE 升序）：")
        print(result.comparison_table.to_string())

        best = result.comparison_table.index[0]
        best_rmse = result.comparison_table.loc[best, "rmse"]
        best_r2 = result.comparison_table.loc[best, "r2"]
        print(f"\n最佳模型: {best}")
        print(f"  R² = {best_r2:.4f}")
        print(f"  RMSE = {best_rmse:.4f}")

    if result.cluster_profiles is not None:
        print(f"\n识别到的聚类数: {len(result.cluster_profiles)}")

    if result.feature_importance is not None:
        print("\nTop 5 重要特征：")
        for _, row in result.feature_importance.head(5).iterrows():
            print(f"  {row['feature']}: {row['importance']:.4f}")

    print(f"\n输出文件保存在 outputs/figures/ 和 outputs/models/ 目录下")
    print("=" * 60)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="野生蓝莓产量预测系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                         运行完整流水线
  python main.py --tune                  启用超参数调优
  python main.py --no-save               不保存模型文件
  python main.py --mode train            训练并保存模型
  python main.py --mode predict          加载模型并预测测试集
        """,
    )
    parser.add_argument(
        "--mode", choices=["full", "train", "predict"], default="full",
        help="流水线模式（默认: full）",
    )
    parser.add_argument(
        "--tune", action="store_true",
        help="启用网格搜索超参数调优",
    )
    parser.add_argument(
        "--no-save", action="store_true",
        help="禁用模型持久化到磁盘",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="启用 DEBUG 级别日志输出",
    )
    return parser


def main():
    """主入口函数。"""
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logger = setup_logging(log_level)

    logger.info("蓝莓产量预测系统启动")
    logger.info("模式: %s | 调优: %s | 保存模型: %s",
                args.mode, args.tune, not args.no_save)

    if args.mode in ("full", "train"):
        cmd_full(tune=args.tune, save_models=not args.no_save, logger=logger)
    elif args.mode == "predict":
        logger.error(
            "预测模式需要预先训练的模型。请先运行: python main.py --mode train"
        )
        sys.exit(1)

    logger.info("运行完毕。")


if __name__ == "__main__":
    main()
