"""Accuracy Monitor: 14日前の予測と実際の価格を照合して誤差率を feedback_log に記録する。"""

import logging
from datetime import date, timedelta

from src.utils.config import SYMBOLS
from src.utils.database import fetch_prediction, fetch_market_data, insert_feedback

logger = logging.getLogger(__name__)


def _get_actual_price(symbol: str) -> float | None:
    """market_data から当日の最新価格を1件取得する。"""
    records = fetch_market_data(symbol, days=2)
    if not records:
        return None
    return float(records[-1]["price"])


def _calc_mape(actual: float, predicted: float) -> float:
    return abs(actual - predicted) / actual * 100


def run() -> None:
    logger.info("=== Accuracy Monitor 開始 ===")

    # 今日が「14日前に予測した target_date」に相当する
    target_date = date.today()

    for symbol in SYMBOLS:
        try:
            pred = fetch_prediction(symbol, target_date)
            if pred is None:
                logger.info("[%s] target_date=%s の予測レコードなし（運用14日未満）。スキップ。", symbol, target_date)
                continue

            actual = _get_actual_price(symbol)
            if actual is None:
                logger.warning("[%s] 実績価格を取得できませんでした。スキップ。", symbol)
                continue

            predicted = float(pred["predicted_price"])
            error_rate = _calc_mape(actual, predicted)

            record = insert_feedback(
                symbol=symbol,
                error_rate=error_rate,
            )
            logger.info(
                "[%s] 照合完了: 予測 $%.2f / 実績 $%.2f / 誤差 %.2f%% (id=%s)",
                symbol, predicted, actual, error_rate, record["id"],
            )

        except Exception as e:
            logger.error("[%s] 照合失敗: %s", symbol, e)

    logger.info("=== Accuracy Monitor 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
