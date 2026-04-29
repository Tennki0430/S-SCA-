"""Oracle Agent: Prophet で 14 日後の価格を予測して prediction_log に保存する。

外生変数として物流指標（BDI）・地政学リスク指標（VIX・Gold・Oil・DXY）・
エネルギー/需要指標（NatGas・ChinaETF・Brent）を使用する。
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

MIN_DAYS = 14          # 最低14日分の日次データが必要
MIN_DAYS_REGRESSORS = 30  # 外生変数は30日分以上揃ってから使用

# Prophet に外生変数として注入する指標シンボル
REGRESSOR_SYMBOLS = ["BDI", "VIX", "Gold", "Oil", "DXY", "NatGas", "ChinaETF", "Brent"]


def _build_price_df(records: list[dict]) -> pd.DataFrame:
    """時間単位のレコードを日次（日平均）に集約して返す。"""
    df = pd.DataFrame(records)[["timestamp", "price"]]
    df["ds"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True).dt.tz_convert(None).dt.normalize()
    daily = df.groupby("ds")["price"].mean().reset_index()
    daily = daily.rename(columns={"price": "y"})
    return daily.sort_values("ds").reset_index(drop=True)


def _build_series(records: list[dict]) -> pd.Series:
    """時間単位のレコードを日次平均 Series に変換する。"""
    if not records:
        return pd.Series(dtype=float)
    df = pd.DataFrame(records)[["timestamp", "price"]].dropna()
    df["ds"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True).dt.tz_convert(None).dt.normalize()
    return df.groupby("ds")["price"].mean()


def run() -> None:
    logger.info("=== Oracle Agent 開始 ===")

    for symbol in SYMBOLS:
        try:
            # LLM Judge が提案した修正パラメータを取得
            param_overrides = fetch_latest_params(symbol)

            # window_days: LLM が「もっと短期のデータで学習すべき」と判断した場合に変更される
            window_days = int(param_overrides.pop("window_days", 90))
            window_days = max(30, min(180, window_days))

            # excluded_regressors: LLM が「この外生変数はノイズ」と判断した場合に除外
            excluded = param_overrides.pop("excluded_regressors", [])
            if isinstance(excluded, str):
                excluded = [s.strip() for s in excluded.split(",") if s.strip()]

            if excluded:
                logger.info("[%s] 除外する外生変数: %s", symbol, excluded)
            if window_days != 90:
                logger.info("[%s] 学習窓: %d 日（LLM Judge による変更）", symbol, window_days)

            # 外生変数をまとめて取得（除外リストを適用）
            regressors: dict[str, pd.Series] = {}
            for sym in REGRESSOR_SYMBOLS:
                if sym in excluded:
                    continue
                records = fetch_market_data(sym, days=window_days)
                series = _build_series(records)
                if not series.empty:
                    regressors[sym] = series

            logger.info("[%s] 利用可能な外生変数: %s", symbol, list(regressors.keys()))

            records = fetch_market_data(symbol, days=window_days)
            df = _build_price_df(records)
            if len(df) < MIN_DAYS:
                logger.warning("[%s] 日次データ不足（%d 日）。スキップします。", symbol, len(df))
                continue

            current_price = float(df["y"].iloc[-1])

            # 外生変数は十分なデータが揃ってから使う（少ないと数値不安定）
            use_regressors = len(df) >= MIN_DAYS_REGRESSORS
            predicted_price, used_params = predict(
                df=df,
                forecast_days=FORECAST_DAYS,
                regressors=regressors if use_regressors else None,
                param_overrides=param_overrides,
            )
            if not use_regressors:
                logger.info("[%s] 日次データ %d 日のため外生変数なしで予測", symbol, len(df))

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
