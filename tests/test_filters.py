import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bids import filter_non_positive_profit


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
