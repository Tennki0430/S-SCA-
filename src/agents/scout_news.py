"""Scout News Agent: 各銘柄の最新ニュースを yfinance から取得し news_log に保存する。

ニュースは LLM Judge の誤差原因分析（A フェーズ）で使用される。
"""

import logging
from datetime import datetime, timezone

import yfinance as yf

from src.utils.config import SYMBOLS
from src.utils.database import insert_news
from src.utils.retry import retry

logger = logging.getLogger(__name__)

MAX_HEADLINES = 5  # 1銘柄あたりの最大保存件数


@retry(max_attempts=2, backoff=2.0)
def _fetch_news(ticker: str) -> list[dict]:
    return yf.Ticker(ticker).news or []


def run() -> None:
    logger.info("=== Scout News 開始 ===")
    for symbol, ticker in SYMBOLS.items():
        try:
            items = _fetch_news(ticker)
            count = 0
            for item in items[:MAX_HEADLINES]:
                headline = item.get("title", "").strip()
                if not headline:
                    continue
                source = item.get("publisher", "")
                pub_ts = item.get("providerPublishTime")
                published_at = (
                    datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat()
                    if pub_ts else None
                )
                insert_news(
                    symbol=symbol,
                    headline=headline,
                    source=source,
                    published_at=published_at,
                )
                count += 1
            logger.info("[%s] %d 件のニュースを保存", symbol, count)
        except Exception as e:
            logger.error("[%s] ニュース取得失敗: %s", symbol, e)
    logger.info("=== Scout News 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
