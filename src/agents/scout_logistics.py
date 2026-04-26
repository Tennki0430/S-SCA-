"""Scout Agent（物流）: BDI（バルチック海運指数）を取得して market_data に保存する。"""

import logging
import requests
from bs4 import BeautifulSoup

from src.utils.database import insert_market_data
from src.utils.retry import retry

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

BDI_URL = "https://www.investing.com/indices/baltic-dry-overview"


@retry(max_attempts=3, backoff=2.0, exceptions=(Exception,))
def _fetch_bdi() -> float:
    """Investing.com から BDI の直近値をスクレイピングして返す。"""
    resp = requests.get(BDI_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # 直近値が入る要素を探す（サイト構造変更時はセレクタを要確認）
    el = soup.select_one("[data-test='instrument-price-last']")
    if el is None:
        # フォールバック: class 名による検索
        el = soup.find("span", class_="text-2xl")
    if el is None:
        raise ValueError("BDI の値を HTML から取得できませんでした。セレクタを確認してください。")

    raw = el.get_text(strip=True).replace(",", "")
    return float(raw)


def run() -> None:
    logger.info("=== Scout Agent (Logistics) 開始 ===")
    try:
        bdi = _fetch_bdi()
        # BDI は symbol="BDI"、logistics_index カラムにも同値を入れる
        record = insert_market_data(
            symbol="BDI",
            price=bdi,
            logistics_index=bdi,
            source="investing.com",
        )
        logger.info("BDI 保存完了: %.1f (id=%s)", bdi, record["id"])
    except Exception as e:
        logger.error("BDI 取得失敗: %s", e)
    logger.info("=== Scout Agent (Logistics) 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
