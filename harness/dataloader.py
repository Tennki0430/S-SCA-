"""データ読み込み層。Supabase からのデータ取得を一元管理する。

データが読めないときはここを見る。
"""

from datetime import date

from src.utils.database import (
    fetch_market_data,
    fetch_market_data_around_date,
    fetch_prediction,
    fetch_latest_params,
    fetch_recent_feedbacks,
)

REGRESSORS = ["BDI", "VIX", "Gold", "Oil", "DXY"]


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

    def load_regressor_snapshot(self, target_date: date) -> dict[str, float]:
        """指定日前後3日のBDI/VIX/Gold/Oil/DXY平均価格を返す。"""
        snapshot: dict[str, float] = {}
        for sym in REGRESSORS:
            records = fetch_market_data_around_date(sym, target_date, window_days=3)
            if records:
                prices = [float(r["price"]) for r in records]
                snapshot[sym] = round(sum(prices) / len(prices), 4)
        return snapshot

    def load_prev_feedbacks(self, symbol: str, limit: int = 5) -> list[dict]:
        """直近の誤差履歴を返す（繰り返しパターンの検出用）。"""
        return fetch_recent_feedbacks(symbol, limit)
