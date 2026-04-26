"""Scout Agent（物流）: BDRY ETF（BDI先物連動）を yfinance で取得して market_data に保存する。

Investing.com は GitHub Actions の IP をブロックするため、
yfinance 経由で BDRY（Breakwave Dry Bulk Shipping ETF）を BDI 代替指標として使用する。
BDRY はバルチック海運指数先物に連動しており、物流コストの代理変数として有効。
"""

import logging

import yfinance as yf

from src.utils.database import insert_market_data
from src.utils.retry import retry

logger = logging.getLogger(__name__)

BDRY_TICKER = "BDRY"


@retry(max_attempts=3, backoff=2.0, exceptions=(Exception,))
def _fetch_bdry() -> float:
    """yfinance で BDRY ETF の直近終値を取得する。"""
    data = yf.download(BDRY_TICKER, period="2d", interval="1d", progress=False)
    if data.empty:
        raise ValueError(f"BDRY データが取得できませんでした: {BDRY_TICKER}")
    return float(data["Close"].iloc[-1].iloc[0])


def run() -> None:
    logger.info("=== Scout Agent (Logistics) 開始 ===")
    try:
        bdry = _fetch_bdry()
        record = insert_market_data(
            symbol="BDI",
            price=bdry,
            logistics_index=bdry,
            source="yfinance/BDRY",
        )
        logger.info("BDRY（BDI代替）保存完了: $%.4f (id=%s)", bdry, record["id"])
    except Exception as e:
        logger.error("BDRY 取得失敗: %s", e)
    logger.info("=== Scout Agent (Logistics) 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
