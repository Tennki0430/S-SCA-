"""oracle.py のユニットテスト。Prophet と DB 呼び出しをモックして検証する。"""

import pytest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock
import pandas as pd


@pytest.fixture
def sample_price_records():
    dates = pd.date_range("2024-01-01", periods=60, freq="D")
    return [
        {"timestamp": str(d), "price": 500.0 + i * 0.5}
        for i, d in enumerate(dates)
    ]


@pytest.fixture
def sample_bdi_records():
    dates = pd.date_range("2024-01-01", periods=60, freq="D")
    return [
        {"timestamp": str(d), "logistics_index": 1500.0 + i}
        for i, d in enumerate(dates)
    ]


@pytest.fixture
def mock_db(sample_price_records, sample_bdi_records):
    with patch("src.agents.oracle.fetch_market_data") as mock_fetch, \
         patch("src.agents.oracle.fetch_latest_params") as mock_params, \
         patch("src.agents.oracle.insert_prediction") as mock_insert:

        def fetch_side_effect(symbol, days=90):
            if symbol == "BDI":
                return sample_bdi_records
            return sample_price_records

        mock_fetch.side_effect = fetch_side_effect
        mock_params.return_value = {}
        mock_insert.return_value = {"id": 1}
        yield mock_fetch, mock_params, mock_insert


def test_run_calls_insert_for_each_symbol(mock_db):
    with patch("src.agents.oracle.predict") as mock_predict:
        mock_predict.return_value = (550.0, {"changepoint_prior_scale": 0.05})

        from src.agents.oracle import run
        from src.utils.config import SYMBOLS

        run()

        assert mock_db[2].call_count == len(SYMBOLS)


def test_run_skips_symbol_with_insufficient_data():
    with patch("src.agents.oracle.fetch_market_data") as mock_fetch, \
         patch("src.agents.oracle.fetch_latest_params", return_value={}), \
         patch("src.agents.oracle.insert_prediction") as mock_insert:

        # データが MIN_ROWS（30件）未満
        mock_fetch.return_value = [{"timestamp": "2024-01-01", "price": 500.0}] * 10

        from src.agents.oracle import run
        run()

        mock_insert.assert_not_called()


def test_run_continues_on_failure(mock_db):
    with patch("src.agents.oracle.predict", side_effect=ValueError("模擬エラー")):
        from src.agents.oracle import run
        # 例外が外に漏れないこと
        run()
