"""過去データ投入スクリプト。

yfinance から過去90日分の日次データを取得して market_data テーブルに投入する。
既存データと重複しないよう、すでにレコードがある日付はスキップする。

使い方:
    python scripts/seed_history.py
"""

import sys
import logging
from datetime import datetime, timedelta, timezone, date

import pandas as pd
import yfinance as yf

# プロジェクトルートを sys.path に追加
sys.path.insert(0, ".")

from src.utils.database import get_client, insert_market_data
from src.utils.config import SYMBOLS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HISTORY_DAYS = 90

# 価格銘柄 + 外生変数（BDI/VIX/Gold/Oil/DXY）
ALL_SYMBOLS: dict[str, str] = {
    **SYMBOLS,
    "BDI": "BDRY",
    "VIX": "^VIX",
    "Gold": "GC=F",
    "Oil": "CL=F",
    "DXY": "DX-Y.NYB",
}


def _existing_dates(symbol: str) -> set[date]:
    """Supabase に保存済みの日付セットを返す。"""
    client = get_client()
    since = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS + 1)).isoformat()
    result = (
        client.table("market_data")
        .select("timestamp")
        .eq("symbol", symbol)
        .gte("timestamp", since)
        .execute()
    )
    return {
        datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).date()
        for r in result.data
    }


def _fetch_history(ticker: str) -> pd.DataFrame:
    """yfinance から過去 HISTORY_DAYS 日分の日次終値を取得する。"""
    df = yf.download(
        ticker,
        period=f"{HISTORY_DAYS}d",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        return pd.DataFrame()
    # multi-level カラム対応: ("Close", "ZW=F") → Series に squeeze
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    close.name = "price"
    result = close.reset_index()
    result.columns = ["date", "price"]
    return result


def seed_symbol(symbol: str, ticker: str) -> int:
    """1銘柄分の過去データを投入し、挿入件数を返す。"""
    existing = _existing_dates(symbol)
    history = _fetch_history(ticker)
    if history.empty:
        logger.warning("[%s] yfinance からデータ取得できず", symbol)
        return 0

    count = 0
    for _, row in history.iterrows():
        row_date = pd.Timestamp(row["date"]).date()
        if row_date in existing:
            continue
        price = float(row["price"])
        if pd.isna(price):
            continue
        # 日次データは正午UTC として保存
        ts = datetime.combine(row_date, datetime.min.time()).replace(
            hour=12, tzinfo=timezone.utc
        )
        client = get_client()
        client.table("market_data").insert({
            "symbol": symbol,
            "price": price,
            "source": "yfinance_seed",
            "timestamp": ts.isoformat(),
        }).execute()
        count += 1

    return count


def run() -> None:
    logger.info("=== 過去データ投入 開始（%d日分） ===", HISTORY_DAYS)
    total = 0
    for symbol, ticker in ALL_SYMBOLS.items():
        try:
            n = seed_symbol(symbol, ticker)
            logger.info("[%s] %d 件を挿入", symbol, n)
            total += n
        except Exception as e:
            logger.error("[%s] 失敗: %s", symbol, e)
    logger.info("=== 過去データ投入 完了（合計 %d 件） ===", total)


if __name__ == "__main__":
    run()
