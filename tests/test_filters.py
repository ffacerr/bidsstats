import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bids import filter_non_positive_profit, filter_pairs_by_driver_ppm_limit


def test_filter_non_positive_profit_removes_non_positive_rows():
    df = pd.DataFrame(
        {
            "user_dispatch_id": [1, 2, 3, 4],
            "profit": [100.0, 0.0, -10.0, 25.5],
        }
    )

    filtered = filter_non_positive_profit(df)

    assert filtered["user_dispatch_id"].tolist() == [1, 4]
    assert (filtered["profit"] > 0).all()


def test_filter_non_positive_profit_drops_nan_values():
    df = pd.DataFrame(
        {
            "user_dispatch_id": [1, 2, 3],
            "profit": [float("nan"), 50.0, -5.0],
        }
    )

    filtered = filter_non_positive_profit(df)

    assert filtered["user_dispatch_id"].tolist() == [2]


def test_pair_ppm_filter_keeps_pairs_below_limit_even_if_driver_overall_high():
    agg_pair = pd.DataFrame(
        {
            "dispatcher_name": ["D1", "D2"],
            "driver_name": ["John", "John"],
            "avg_driver_ppm": [1.5, 3.1],
            "bids": [5, 7],
        }
    )

    filtered_pairs = filter_pairs_by_driver_ppm_limit(agg_pair, max_driver_ppm=2.0)

    assert filtered_pairs[["dispatcher_name", "driver_name"]].values.tolist() == [["D1", "John"]]
    assert filtered_pairs["avg_driver_ppm"].iloc[0] < 2.0
