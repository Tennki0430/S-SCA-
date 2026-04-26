"""database.py のユニットテスト。Supabase クライアントをモックして検証する。"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date


@pytest.fixture
def mock_client():
    with patch("src.utils.database.get_client") as m:
        client = MagicMock()
        m.return_value = client

        # チェーン呼び出しの共通モック
        table = MagicMock()
        client.table.return_value = table
        table.insert.return_value = table
        table.select.return_value = table
        table.eq.return_value = table
        table.order.return_value = table
        table.limit.return_value = table

        yield client, table


def test_insert_market_data_returns_record(mock_client):
    from src.utils.database import insert_market_data

    client, table = mock_client
    table.execute.return_value = MagicMock(data=[{"id": 1, "symbol": "Wheat", "price": 500.0}])

    result = insert_market_data(symbol="Wheat", price=500.0, source="yfinance")

    assert result["symbol"] == "Wheat"
    assert result["price"] == 500.0


def test_insert_prediction_uses_isoformat(mock_client):
    from src.utils.database import insert_prediction

    client, table = mock_client
    table.execute.return_value = MagicMock(data=[{"id": 1}])

    target = date(2025, 6, 1)
    insert_prediction(symbol="Corn", target_date=target, predicted_price=450.0)

    inserted = table.insert.call_args[0][0]
    assert inserted["target_date"] == "2025-06-01"


def test_fetch_prediction_returns_none_when_not_found(mock_client):
    from src.utils.database import fetch_prediction

    client, table = mock_client
    table.execute.return_value = MagicMock(data=[])

    result = fetch_prediction(symbol="Copper", target_date=date(2025, 6, 1))

    assert result is None


def test_fetch_latest_params_returns_empty_dict_when_no_records(mock_client):
    from src.utils.database import fetch_latest_params

    client, table = mock_client
    table.execute.return_value = MagicMock(data=[])

    result = fetch_latest_params(symbol="Wheat")

    assert result == {}
