"""Scout News Agent: 各銘柄の最新ニュースを yfinance から取得し news_log に保存する。

ニュースは LLM Judge の誤差原因分析（A フェーズ）で使用される。
"""

import logging

import yfinance as yf
from deep_translator import GoogleTranslator

from src.utils.config import SYMBOLS
from src.utils.database import insert_news
from src.utils.retry import retry

logger = logging.getLogger(__name__)

MAX_HEADLINES = 5  # 1銘柄あたりの最大保存件数
_translator = GoogleTranslator(source="en", target="ja")


def _translate(text: str) -> str:
    try:
        return _translator.translate(text) or text
    except Exception as e:
        logger.warning("翻訳失敗（英語のまま保存）: %s", e)
        return text


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
                content = item.get("content", item)  # yfinance 1.3.0: item["content"]
                headline_en = content.get("title", "").strip()
                if not headline_en:
                    continue
                headline = _translate(headline_en)
                provider = content.get("provider", {})
                source = provider.get("displayName", content.get("publisher", ""))
                pub_date = content.get("pubDate") or content.get("displayTime")
                published_at = pub_date if pub_date else None
                insert_news(
                    symbol=symbol,
                    headline=headline,
                    source=source,
                    published_at=published_at,
                )
                count += 1
            logger.info("[%s] %d 件のニュースを保存（日本語）", symbol, count)
        except Exception as e:
            logger.error("[%s] ニュース取得失敗: %s", symbol, e)
    logger.info("=== Scout News 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
