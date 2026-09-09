"""本次扩容实验的固定设置；股票清单不是历史指数成分股。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
START = "2015-01-01"
END = "2026-01-01"  # Yahoo 的 end 不包含这一天
SYMBOLS = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META",
    "JPM", "BAC", "GS", "V", "JNJ", "PFE", "MRK", "UNH",
    "XOM", "CVX", "COP", "CAT", "HON", "DE",
    "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD", "NEE", "DUK", "SO",
)
BENCHMARK = "SPY"
VALID_START = "2023-01-01"
TEST_START = "2025-01-01"
ENTRY_LAG = 1
HORIZON = 5
RAW_DIR = ROOT / "data" / "raw" / "panel_2015_2025"
PANEL_PATH = ROOT / "data" / "processed" / "panel_2015_2025.csv"
EXPERIMENT_DIR = ROOT / "data" / "experiments" / "panel_lgbm_v1"

HISTORY_PARAMS = dict(
    start=START, end=END, interval="1d", auto_adjust=False,
    back_adjust=False, actions=True, repair=False, keepna=True,
    prepost=False, rounding=False,
)
RIDGE_ALPHA = 1.0
LGBM_PARAMS = dict(
    objective="regression", n_estimators=1000, learning_rate=0.03,
    num_leaves=31, max_depth=-1, min_child_samples=200,
    reg_lambda=10.0, colsample_bytree=0.9, subsample=1.0,
    random_state=42, n_jobs=4, deterministic=True, force_col_wise=True,
    importance_type="gain", verbosity=-1,
)
EARLY_STOPPING_ROUNDS = 50
