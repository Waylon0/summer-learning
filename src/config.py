import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(ROOT_DIR, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed")
OUTPUTS_DIR = os.path.join(ROOT_DIR, "outputs")
FIGURES_DIR = os.path.join(OUTPUTS_DIR, "figures")
MODELS_DIR = os.path.join(OUTPUTS_DIR, "models")

TRAIN_PATH = os.path.join(RAW_DATA_DIR, "train.csv")
TEST_PATH = os.path.join(RAW_DATA_DIR, "test.csv")

BEE_FEATURES = ["honeybee", "bumbles", "andrena", "osmia"]
UPPER_TEMP_FEATURES = ["MaxOfUpperTRange", "MinOfUpperTRange", "AverageOfUpperTRange"]
LOWER_TEMP_FEATURES = ["MaxOfLowerTRange", "MinOfLowerTRange", "AverageOfLowerTRange"]
RAIN_FEATURES = ["RainingDays", "AverageRainingDays"]
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
