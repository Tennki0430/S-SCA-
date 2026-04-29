"""バックテストでprediction_logを生成するスクリプト。

過去の価格データを使って「その日にOracleが予測していたら」を再現し、
14日後のtarget_dateと予測価格をprediction_logに保存する。

使い方:
    python scripts/seed_predictions.py
"""

import sys
import logging
from datetime import datetime, timedelta, timezone, date

import pandas as pd

sys.path.insert(0, ".")

from src.utils.database import get_client, fetch_prediction
from src.utils.config import SYMBOLS
from src.models.prophet_wrapper import predict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FORECAST_DAYS = 14
BACKTEST_INTERVAL_DAYS = 7
MIN_TRAIN_DAYS = 30


def _fetch_all_daily(symbol: str) -> pd.DataFrame:
    """symbolの全日次データをSupabaseから取得して日次集計して返す。"""
    client = get_client()
    result = (
        client.table("market_data")
        .select("timestamp,price")
        .eq("symbol", symbol)
        .order("timestamp", desc=False)
        .execute()
    )
    if not result.data:
        return pd.DataFrame()
    df = pd.DataFrame(result.data)
    df["ds"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True).dt.tz_convert(None).dt.normalize()
    daily = df.groupby("ds")["price"].mean().reset_index()
    daily = daily.rename(columns={"price": "y"})
    return daily.sort_values("ds").reset_index(drop=True)


def _fetch_regressors() -> dict:
    """外生変数の日次データを取得して返す。"""
    client = get_client()
    regressors = {}
    for sym in ["BDI", "VIX", "Gold", "Oil", "DXY"]:
        result = (
            client.table("market_data")
            .select("timestamp,price")
            .eq("symbol", sym)
            .order("timestamp", desc=False)
            .execute()
        )
        if not result.data:
            continue
        df = pd.DataFrame(result.data)
        df["ds"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True).dt.tz_convert(None).dt.normalize()
        series = df.groupby("ds")["price"].mean()
        if not series.empty:
            regressors[sym] = series
    return regressors


def seed_symbol(symbol: str, all_daily: pd.DataFrame, regressors: dict) -> int:
    """1銘柄のバックテスト予測をprediction_logに保存し、保存件数を返す。"""
    if all_daily.empty or len(all_daily) < MIN_TRAIN_DAYS + FORECAST_DAYS:
        logger.warning("[%s] データ不足でスキップ", symbol)
        return 0

    dates = all_daily["ds"].tolist()
    start_idx = MIN_TRAIN_DAYS
    end_idx = len(dates) - FORECAST_DAYS - 1

    count = 0
    idx = start_idx
    while idx <= end_idx:
        pred_date = dates[idx].date()
        target_date = pred_date + timedelta(days=FORECAST_DAYS)

        # 重複チェック（symbol + target_date で一意）
        existing = fetch_prediction(symbol, target_date)
        if existing is not None:
            logger.info("[%s] target_date=%s は既存。スキップ。", symbol, target_date)
            idx += BACKTEST_INTERVAL_DAYS
            continue

        train_df = all_daily[all_daily["ds"] <= dates[idx]].copy()
        current_price = float(train_df["y"].iloc[-1])
        use_regressors = len(train_df) >= 30

        try:
            predicted_price, used_params = predict(
                df=train_df,
                forecast_days=FORECAST_DAYS,
                regressors=regressors if use_regressors else None,
            )
        except Exception as e:
            logger.warning("[%s] %s 予測失敗: %s", symbol, pred_date, e)
            idx += BACKTEST_INTERVAL_DAYS
            continue

        change_pct = (predicted_price - current_price) / current_price * 100
        reasoning = (
            f"バックテスト: {pred_date} 時点での予測 → "
            f"現在 ${current_price:.2f} / 14日後予測 ${predicted_price:.2f} ({change_pct:+.1f}%)"
        )

        ts = datetime.combine(pred_date, datetime.min.time()).replace(
            hour=12, tzinfo=timezone.utc
        )
        client = get_client()
        client.table("prediction_log").insert({
            "symbol": symbol,
            "target_date": target_date.isoformat(),
            "predicted_price": round(predicted_price, 4),
            "current_price": round(current_price, 4),
            "reasoning_text": reasoning,
            "prophet_params": used_params,
            "timestamp": ts.isoformat(),
        }).execute()

        logger.info("[%s] %s → 予測 $%.2f (%+.1f%%)", symbol, pred_date, predicted_price, change_pct)
        count += 1
        idx += BACKTEST_INTERVAL_DAYS

    return count


def run() -> None:
    logger.info("=== 予測バックテスト開始 ===")
    regressors = _fetch_regressors()
    logger.info("外生変数: %s", list(regressors.keys()))

    total = 0
    for symbol in SYMBOLS:
        logger.info("[%s] バックテスト中...", symbol)
        all_daily = _fetch_all_daily(symbol)
        logger.info("[%s] 日次データ %d 日分", symbol, len(all_daily))
        n = seed_symbol(symbol, all_daily, regressors)
        logger.info("[%s] %d 件を保存", symbol, n)
        total += n

    logger.info("=== 予測バックテスト完了（合計 %d 件） ===", total)


if __name__ == "__main__":
    run()
