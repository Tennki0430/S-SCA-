"""Oracle Agent: Prophet で 14 日後の価格を予測して prediction_log に保存する。"""

import logging
from datetime import date, timedelta

import pandas as pd

from src.utils.config import SYMBOLS, FORECAST_DAYS
from src.utils.database import (
    fetch_market_data,
    fetch_latest_params,
    insert_prediction,
)
from src.models.prophet_wrapper import predict

logger = logging.getLogger(__name__)

MIN_ROWS = 30  # Prophet が最低限必要なデータ行数


def _build_price_df(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)[["timestamp", "price"]]
    df = df.rename(columns={"timestamp": "ds", "price": "y"})
    df["ds"] = pd.to_datetime(df["ds"]).dt.tz_localize(None)
    return df.sort_values("ds").reset_index(drop=True)


def _build_logistics_series(records: list[dict]) -> pd.Series:
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records)[["timestamp", "logistics_index"]].dropna()
    df["ds"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    return df.set_index("ds")["logistics_index"]


def run() -> None:
    logger.info("=== Oracle Agent 開始 ===")

    # BDI（物流指標）を一度だけ取得して全銘柄で共用する
    bdi_records = fetch_market_data("BDI", days=90)
    logistics_series = _build_logistics_series(bdi_records)

    for symbol in SYMBOLS:
        try:
            records = fetch_market_data(symbol, days=90)
            if len(records) < MIN_ROWS:
                logger.warning("[%s] データ不足（%d 件）。スキップします。", symbol, len(records))
                continue

            df = _build_price_df(records)
            current_price = float(df["y"].iloc[-1])

            # Self-Reflection で更新された最新パラメータを取得
            param_overrides = fetch_latest_params(symbol)

            predicted_price, used_params = predict(
                df=df,
                forecast_days=FORECAST_DAYS,
                logistics_series=logistics_series if not logistics_series.empty else None,
                param_overrides=param_overrides,
            )

            target_date = date.today() + timedelta(days=FORECAST_DAYS)
            record = insert_prediction(
                symbol=symbol,
                target_date=target_date,
                predicted_price=predicted_price,
                current_price=current_price,
                prophet_params=used_params,
            )

            change_pct = (predicted_price - current_price) / current_price * 100
            logger.info(
                "[%s] 予測完了: 現在 $%.2f → 14日後 $%.2f (%+.1f%%) (id=%s)",
                symbol, current_price, predicted_price, change_pct, record["id"],
            )

        except Exception as e:
            logger.error("[%s] 予測失敗: %s", symbol, e)

    logger.info("=== Oracle Agent 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
