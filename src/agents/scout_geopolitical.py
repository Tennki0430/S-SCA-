"""Scout Agent（地政学リスク）: VIX・金・原油・ドル指数・天然ガス・中国ETF・ブレント原油を yfinance で取得して market_data に保存する。"""

import logging

import yfinance as yf

from src.utils.database import insert_market_data
from src.utils.retry import retry

logger = logging.getLogger(__name__)

GEO_SYMBOLS: dict[str, str] = {
    "VIX":      "^VIX",       # CBOE 恐怖指数（地政学リスク時に急騰）
    "Gold":     "GC=F",       # 金先物（有事の金、リスク上昇で高騰）
    "Oil":      "CL=F",       # WTI 原油先物（中東情勢に直結）
    "DXY":      "DX-Y.NYB",  # ドル指数（地政学リスク時にドル高）
    "NatGas":   "NG=F",       # 天然ガス先物（ナフサの競合原料、銅の製錬エネルギーコスト）
    "ChinaETF": "FXI",        # iShares 中国ETF（銅消費の50%を占める中国需要の代理指標）
    "Brent":    "BZ=F",       # ブレント原油先物（アジア・欧州向けナフサ価格に直結）
}


@retry(max_attempts=3, backoff=2.0, exceptions=(Exception,))
def _fetch_price(ticker: str) -> float:
    data = yf.download(ticker, period="2d", interval="1d", progress=False)
    if data.empty:
        raise ValueError(f"データが取得できませんでした: {ticker}")
    return float(data["Close"].iloc[-1].iloc[0])


def run() -> None:
    logger.info("=== Scout Agent (Geopolitical) 開始 ===")
    for symbol, ticker in GEO_SYMBOLS.items():
        try:
            price = _fetch_price(ticker)
            record = insert_market_data(
                symbol=symbol,
                price=price,
                source="yfinance",
            )
            logger.info("[%s] 保存完了: %.4f (id=%s)", symbol, price, record["id"])
        except Exception as e:
            logger.error("[%s] 取得失敗: %s", symbol, e)
    logger.info("=== Scout Agent (Geopolitical) 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
