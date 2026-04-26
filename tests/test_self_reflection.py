"""self_reflection.py のユニットテスト。Claude API と DB をモックして検証する。"""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_deps():
    with patch("src.agents.self_reflection._fetch_latest_error") as mock_error, \
         patch("src.agents.self_reflection.fetch_latest_params") as mock_params, \
         patch("src.agents.self_reflection._ask_claude") as mock_claude, \
         patch("src.agents.self_reflection.insert_feedback") as mock_insert:

        mock_error.return_value = 12.5          # 閾値（5%）超え
        mock_params.return_value = {}
        mock_claude.return_value = {"changepoint_prior_scale": 0.1}
        mock_insert.return_value = {"id": 1}
        yield mock_error, mock_params, mock_claude, mock_insert


def test_run_inserts_updates_when_error_exceeds_threshold(mock_deps):
    from src.agents.self_reflection import run
    from src.utils.config import SYMBOLS

    run()

    assert mock_deps[3].call_count == len(SYMBOLS)


def test_run_skips_when_error_below_threshold(mock_deps):
    mock_error, _, _, mock_insert = mock_deps
    mock_error.return_value = 3.0  # 閾値（5%）未満

    from src.agents.self_reflection import run
    run()

    mock_insert.assert_not_called()


def test_run_skips_when_no_error_data(mock_deps):
    mock_error, _, _, mock_insert = mock_deps
    mock_error.return_value = None  # データなし

    from src.agents.self_reflection import run
    run()

    mock_insert.assert_not_called()


def test_run_skips_when_claude_returns_empty(mock_deps):
    mock_error, _, mock_claude, mock_insert = mock_deps
    mock_claude.return_value = {}  # Claude が更新パラメータなしと判断

    from src.agents.self_reflection import run
    run()

    mock_insert.assert_not_called()
