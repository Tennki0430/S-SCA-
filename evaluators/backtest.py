"""バックテスト評価（スライディングウィンドウ方式）。

90日分の過去データを使い、14日先予測の精度を検証する。
「14日後まで待たないと評価できない」問題を回避し、
提出時点でモデル精度を証明できる。
"""

import logging

import pandas as pd

from src.utils.database import fetch_market_data
from src.utils.config import SYMBOLS
from src.models.prophet_wrapper import predict

logger = logging.getLogger(__name__)

PASS_THRESHOLD_PCT = 10.0
MIN_TRAIN_DAYS = 30
STEP_DAYS = 7
FORECAST_DAYS = 14


class BacktestEvaluator:
    def run_symbol(self, symbol: str) -> dict:
        records = fetch_market_data(symbol, days=90)
        if len(records) < MIN_TRAIN_DAYS + FORECAST_DAYS:
            logger.warning("[%s] データ不足 (%d件)。スキップ。", symbol, len(records))
            return {"symbol": symbol, "status": "insufficient_data", "avg_mape": None, "windows": 0}

        # 日次平均に集約（hourly データが複数入る場合に対応）
        df = pd.DataFrame([
            {"ds": pd.Timestamp(r["timestamp"][:10]), "y": float(r["price"])}
            for r in records
        ])
        df = (
            df.groupby("ds")["y"]
            .mean()
            .reset_index()
            .sort_values("ds")
            .reset_index(drop=True)
        )

        if len(df) < MIN_TRAIN_DAYS + FORECAST_DAYS:
            logger.warning("[%s] 日次集約後のデータ不足 (%d日)。スキップ。", symbol, len(df))
            return {"symbol": symbol, "status": "insufficient_data", "avg_mape": None, "windows": 0}

        windows = []
        i = MIN_TRAIN_DAYS
        while i + FORECAST_DAYS < len(df):
            train_df = df.iloc[:i][["ds", "y"]].copy()
            target_idx = i + FORECAST_DAYS
            actual = float(df.iloc[target_idx]["y"])
            anchor_date = df.iloc[i]["ds"].date()
            target_date = df.iloc[target_idx]["ds"].date()

            try:
                predicted, _ = predict(train_df, forecast_days=FORECAST_DAYS)
                mape = abs(predicted - actual) / actual * 100
                windows.append({
                    "anchor_date": str(anchor_date),
                    "target_date": str(target_date),
                    "predicted": round(predicted, 4),
                    "actual": round(actual, 4),
                    "mape": round(mape, 2),
                })
                logger.info(
                    "[%s] %s→%s: pred=%.4f actual=%.4f MAPE=%.1f%%",
                    symbol, anchor_date, target_date, predicted, actual, mape,
                )
            except Exception as e:
                logger.warning("[%s] window anchor=%s 失敗: %s", symbol, anchor_date, e)

            i += STEP_DAYS

        if not windows:
            return {"symbol": symbol, "status": "no_results", "avg_mape": None, "windows": 0}

        avg_mape = sum(w["mape"] for w in windows) / len(windows)
        passed = avg_mape < PASS_THRESHOLD_PCT
        return {
            "symbol": symbol,
            "status": "ok",
            "avg_mape": round(avg_mape, 2),
            "windows": len(windows),
            "passed": passed,
            "details": windows,
        }

    def run_all(self) -> list[dict]:
        results = []
        for symbol in SYMBOLS:
            logger.info("=== バックテスト: %s ===", symbol)
            result = self.run_symbol(symbol)
            results.append(result)
        return results
