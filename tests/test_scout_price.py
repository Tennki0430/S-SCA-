"""scout_price のユニットテスト。yfinance 呼び出しをモックして外部通信なしに検証する。"""

import pytest
from unittest.mock import patch, MagicMock
import pandas as pd


@pytest.fixture
def mock_yf_download():
    """yfinance.download の戻り値をモックする。"""
    df = pd.DataFrame({"Close": [100.0, 105.5]})
    with patch("src.agents.scout_price.yf.download", return_value=df) as m:
        yield m


@pytest.fixture
def mock_insert():
    with patch("src.agents.scout_price.insert_market_data") as m:
        m.return_value = {"id": 1, "symbol": "Wheat", "price": 105.5}
        yield m


def test_run_inserts_all_symbols(mock_yf_download, mock_insert):
    from src.agents.scout_price import run
    from src.utils.config import SYMBOLS

    run()

    assert mock_insert.call_count == len(SYMBOLS)


def test_run_uses_last_close_price(mock_yf_download, mock_insert):
    from src.agents.scout_price import run

    run()

    first_call_kwargs = mock_insert.call_args_list[0]
    assert first_call_kwargs.kwargs["price"] == pytest.approx(105.5)


def test_run_continues_on_single_failure(mock_insert):
    """1銘柄の取得に失敗しても残りの銘柄は処理を続ける。"""
    from src.agents.scout_price import run
    from src.utils.config import SYMBOLS

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("模擬的な取得エラー")
        df = pd.DataFrame({"Close": [200.0, 210.0]})
        return df

    with patch("src.agents.scout_price.yf.download", side_effect=side_effect):
        run()  # 例外が外に漏れないこと

    # 失敗した1件を除いた残りが insert される
    assert mock_insert.call_count == len(SYMBOLS) - 1
