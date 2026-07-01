"""全局配置常量与日志系统设置。"""

import logging
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(ROOT_DIR, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed")
OUTPUTS_DIR = os.path.join(ROOT_DIR, "outputs")
FIGURES_DIR = os.path.join(OUTPUTS_DIR, "figures")
MODELS_DIR = os.path.join(OUTPUTS_DIR, "models")

TRAIN_PATH = os.path.join(RAW_DATA_DIR, "train.csv")
TEST_PATH = os.path.join(RAW_DATA_DIR, "test.csv")
PREDICTION_PATH = os.path.join(OUTPUTS_DIR, "predictions.csv")

# 特征分组
BEE_FEATURES = ["honeybee", "bumbles", "andrena", "osmia"]          # 蜂群密度
UPPER_TEMP_FEATURES = ["maxofuppertrange", "minofuppertrange", "averageofuppertrange"]   # 最高温带
LOWER_TEMP_FEATURES = ["maxoflowertrange", "minoflowertrange", "averageoflowertrange"]   # 最低温带
RAIN_FEATURES = ["rainingdays", "averagerainingdays"]                # 降雨
FRUIT_FEATURES = ["fruitset", "fruitmass", "seeds"]                  # 果实指标（中间变量）
TARGET = "yield"

# 不含果实指标的环境特征集（13 个特征）
ENV_FEATURES = (
    ["clonesize"]
    + BEE_FEATURES
    + UPPER_TEMP_FEATURES
    + LOWER_TEMP_FEATURES
    + RAIN_FEATURES
)

# 全部特征（16 个，含果实指标）
NUMERIC_FEATURES = ENV_FEATURES + FRUIT_FEATURES

# 建模参数
RANDOM_STATE = 42
TEST_SIZE = 0.2
CV_FOLDS = 5
PCA_VARIANCE_THRESHOLD = 0.95

CLUSTER_K_RANGE = range(2, 11)
RF_N_ESTIMATORS = 200
XGB_N_ESTIMATORS = 300

# 确保输出目录存在
os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """配置并返回项目日志记录器。

    Parameters
    ----------
    level : int
        日志级别，默认 INFO。

    Returns
    -------
    logging.Logger
        配置好的日志记录器实例。
    """
    logger = logging.getLogger("blueberry")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger
