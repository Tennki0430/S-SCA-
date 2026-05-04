"""バックテストでfeedback_logを生成するスクリプト。

過去の価格データを使って「その日にOracleが予測していたら」を再現し、
14日後の実績と比較してMAPEを計算してfeedback_logに保存する。

使い方:
    python scripts/seed_feedback.py
"""

import sys
import logging
from datetime import datetime, timedelta, timezone, date

import pandas as pd

sys.path.insert(0, ".")

from src.utils.database import get_client, insert_feedback
from src.utils.config import SYMBOLS
from src.models.prophet_wrapper import predict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FORECAST_DAYS = 14
BACKTEST_INTERVAL_DAYS = 7   # 何日おきにバックテストするか
MIN_TRAIN_DAYS = 14          # 予測に最低必要な日数


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


def _already_exists(symbol: str, pred_date: date) -> bool:
    """同日のfeedback_logが既に存在するか確認。"""
    client = get_client()
    since = datetime.combine(pred_date, datetime.min.time()).replace(tzinfo=timezone.utc).isoformat()
    until = datetime.combine(pred_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc).isoformat()
    result = (
        client.table("feedback_log")
        .select("id")
        .eq("symbol", symbol)
        .gte("timestamp", since)
        .lt("timestamp", until)
        .execute()
    )
    return len(result.data) > 0


def backtest_symbol(symbol: str, all_daily: pd.DataFrame, regressors: dict) -> int:
    """1銘柄のバックテストを実行してfeedback_logに保存し、保存件数を返す。"""
    if all_daily.empty or len(all_daily) < MIN_TRAIN_DAYS + FORECAST_DAYS:
        logger.warning("[%s] データ不足でスキップ", symbol)
        return 0

    dates = all_daily["ds"].tolist()
    # 最古のバックテスト開始日（MIN_TRAIN_DAYS日分のデータが揃った翌日）
    start_idx = MIN_TRAIN_DAYS
    # 最新のバックテスト日（FORECAST_DAYS日前まで、実績と比較できるように）
    end_idx = len(dates) - FORECAST_DAYS - 1

    count = 0
    idx = start_idx
    while idx <= end_idx:
        pred_date = dates[idx].date()

        if _already_exists(symbol, pred_date):
            logger.info("[%s] %s は既存。スキップ。", symbol, pred_date)
            idx += BACKTEST_INTERVAL_DAYS
            continue

        # 予測日までのデータでProphet実行
        train_df = all_daily[all_daily["ds"] <= dates[idx]].copy()
        use_regressors = len(train_df) >= 30

        try:
            predicted_price, _ = predict(
                df=train_df,
                forecast_days=FORECAST_DAYS,
                regressors=regressors if use_regressors else None,
            )
        except Exception as e:
            logger.warning("[%s] %s 予測失敗: %s", symbol, pred_date, e)
            idx += BACKTEST_INTERVAL_DAYS
            continue

        # 14日後の実績価格を取得
        target_date = dates[idx] + timedelta(days=FORECAST_DAYS)
        actual_row = all_daily[all_daily["ds"] == target_date]
        if actual_row.empty:
            idx += BACKTEST_INTERVAL_DAYS
            continue
        actual_price = float(actual_row["y"].iloc[0])

        if actual_price == 0:
            idx += BACKTEST_INTERVAL_DAYS
            continue

        mape = abs(predicted_price - actual_price) / actual_price * 100
        change_pct = (predicted_price - actual_price) / actual_price * 100

        note = (
            f"バックテスト: {pred_date} 時点での予測 → "
            f"予測 ${predicted_price:.2f} / 実績 ${actual_price:.2f} "
            f"({change_pct:+.1f}%) MAPE={mape:.1f}%"
        )

        # feedback_logのtimestampを予測日に設定
        ts = datetime.combine(pred_date, datetime.min.time()).replace(
            hour=12, tzinfo=timezone.utc
        )
        client = get_client()
        client.table("feedback_log").insert({
            "symbol": symbol,
            "error_rate": round(mape, 2),
            "self_reflection_notes": note,
            "parameter_updates": {},
            "timestamp": ts.isoformat(),
        }).execute()

        logger.info("[%s] %s → MAPE=%.1f%%", symbol, pred_date, mape)
        count += 1
        idx += BACKTEST_INTERVAL_DAYS

    return count


def run() -> None:
    logger.info("=== バックテスト開始 ===")
    regressors = _fetch_regressors()
    logger.info("外生変数: %s", list(regressors.keys()))

    total = 0
    for symbol in SYMBOLS:
        logger.info("[%s] バックテスト中...", symbol)
        all_daily = _fetch_all_daily(symbol)
        logger.info("[%s] 日次データ %d 日分", symbol, len(all_daily))
        n = backtest_symbol(symbol, all_daily, regressors)
        logger.info("[%s] %d 件を保存", symbol, n)
        total += n

    logger.info("=== バックテスト完了（合計 %d 件） ===", total)


if __name__ == "__main__":
    run()
