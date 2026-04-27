"""データ読み込み層。Supabase からのデータ取得を一元管理する。

データが読めないときはここを見る。
"""

from datetime import date

from src.utils.database import fetch_market_data, fetch_prediction, fetch_latest_params


class DataLoader:
    def load_market_data(self, symbol: str, days: int = 90) -> list[dict]:
        return fetch_market_data(symbol, days)

    def load_prediction(self, symbol: str, target_date: date) -> dict | None:
        return fetch_prediction(symbol, target_date)

    def load_latest_params(self, symbol: str) -> dict:
        return fetch_latest_params(symbol)

    def load_actual_price(self, symbol: str) -> float | None:
        """market_data から当日の最新価格を取得する。"""
        records = fetch_market_data(symbol, days=2)
        if not records:
            return None
        return float(records[-1]["price"])
