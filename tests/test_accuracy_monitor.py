"""accuracy_monitor.py のユニットテスト。"""

import pytest
from datetime import date
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_deps():
    with patch("src.agents.accuracy_monitor.fetch_prediction") as mock_pred, \
         patch("src.agents.accuracy_monitor._get_actual_price") as mock_actual, \
         patch("src.agents.accuracy_monitor.insert_feedback") as mock_insert:

        mock_pred.return_value = {
            "predicted_price": 500.0,
            "current_price": 480.0,
        }
        mock_actual.return_value = 510.0
        mock_insert.return_value = {"id": 1}
        yield mock_pred, mock_actual, mock_insert


def test_run_inserts_feedback_for_each_symbol(mock_deps):
    from src.agents.accuracy_monitor import run
    from src.utils.config import SYMBOLS

    run()

    assert mock_deps[2].call_count == len(SYMBOLS)


def test_run_skips_when_no_prediction(mock_deps):
    mock_pred, mock_actual, mock_insert = mock_deps
    mock_pred.return_value = None  # 予測レコードなし

    from src.agents.accuracy_monitor import run
    run()

    mock_insert.assert_not_called()


def test_run_skips_when_no_actual_price(mock_deps):
    mock_pred, mock_actual, mock_insert = mock_deps
    mock_actual.return_value = None  # 実績価格なし

    from src.agents.accuracy_monitor import run
    run()

    mock_insert.assert_not_called()


def test_mape_calculation():
    from src.agents.accuracy_monitor import _calc_mape

    result = _calc_mape(actual=500.0, predicted=450.0)
    assert result == pytest.approx(10.0)
