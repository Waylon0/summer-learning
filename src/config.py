"""Global configuration constants and logging setup."""

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

BEE_FEATURES = ["honeybee", "bumbles", "andrena", "osmia"]
UPPER_TEMP_FEATURES = ["maxofuppertrange", "minofuppertrange", "averageofuppertrange"]
LOWER_TEMP_FEATURES = ["maxoflowertrange", "minoflowertrange", "averageoflowertrange"]
RAIN_FEATURES = ["rainingdays", "averagerainingdays"]
FRUIT_FEATURES = ["fruitset", "fruitmass", "seeds"]
TARGET = "yield"

NUMERIC_FEATURES = (
    ["clonesize"]
    + BEE_FEATURES
    + UPPER_TEMP_FEATURES
    + LOWER_TEMP_FEATURES
    + RAIN_FEATURES
    + FRUIT_FEATURES
)

RANDOM_STATE = 42
TEST_SIZE = 0.2
CV_FOLDS = 5
PCA_VARIANCE_THRESHOLD = 0.95

CLUSTER_K_RANGE = range(2, 11)
RF_N_ESTIMATORS = 200
XGB_N_ESTIMATORS = 300

os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
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
