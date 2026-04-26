"""Scout Agent（価格）: Yahoo Finance から先物価格を取得して market_data に保存する。"""

import logging
from datetime import datetime

import yfinance as yf

from src.utils.config import SYMBOLS
from src.utils.database import insert_market_data
from src.utils.retry import retry

logger = logging.getLogger(__name__)


@retry(max_attempts=3, backoff=2.0, exceptions=(Exception,))
def _fetch_price(ticker: str) -> float:
    """yfinance で直近の終値を1件取得する。"""
    data = yf.download(ticker, period="2d", interval="1d", progress=False)
    if data.empty:
        raise ValueError(f"価格データが取得できませんでした: {ticker}")
    return float(data["Close"].iloc[-1].iloc[0])


def run() -> None:
    logger.info("=== Scout Agent (Price) 開始 ===")
    for symbol, ticker in SYMBOLS.items():
        try:
            price = _fetch_price(ticker)
            record = insert_market_data(
                symbol=symbol,
                price=price,
                source="yfinance",
            )
            logger.info("[%s] 価格保存完了: $%.4f (id=%s)", symbol, price, record["id"])
        except Exception as e:
            logger.error("[%s] 価格取得失敗: %s", symbol, e)
    logger.info("=== Scout Agent (Price) 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
