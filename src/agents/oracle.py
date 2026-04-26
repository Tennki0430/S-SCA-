"""Oracle Agent: Prophet で 14 日後の価格を予測して prediction_log に保存する。

外生変数として物流指標（BDI）と地政学リスク指標（VIX・Gold・Oil・DXY）を使用する。
データが揃っている指標のみ自動で Prophet に注入する。
"""

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

MIN_ROWS = 30

# Prophet に外生変数として注入する指標シンボル
REGRESSOR_SYMBOLS = ["BDI", "VIX", "Gold", "Oil", "DXY"]


def _build_price_df(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)[["timestamp", "price"]]
    df = df.rename(columns={"timestamp": "ds", "price": "y"})
    df["ds"] = pd.to_datetime(df["ds"]).dt.tz_localize(None)
    return df.sort_values("ds").reset_index(drop=True)


def _build_series(records: list[dict]) -> pd.Series:
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records)[["timestamp", "price"]].dropna()
    df["ds"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
    return df.set_index("ds")["price"]


def run() -> None:
    logger.info("=== Oracle Agent 開始 ===")

    # 外生変数をまとめて取得（データがある指標だけ regressors に追加）
    regressors: dict[str, pd.Series] = {}
    for sym in REGRESSOR_SYMBOLS:
        records = fetch_market_data(sym, days=90)
        series = _build_series(records)
        if not series.empty:
            regressors[sym] = series

    logger.info("利用可能な外生変数: %s", list(regressors.keys()))

    for symbol in SYMBOLS:
        try:
            records = fetch_market_data(symbol, days=90)
            if len(records) < MIN_ROWS:
                logger.warning("[%s] データ不足（%d 件）。スキップします。", symbol, len(records))
                continue

            df = _build_price_df(records)
            current_price = float(df["y"].iloc[-1])
            param_overrides = fetch_latest_params(symbol)

            predicted_price, used_params = predict(
                df=df,
                forecast_days=FORECAST_DAYS,
                regressors=regressors if regressors else None,
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
