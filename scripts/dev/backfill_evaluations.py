"""過去の予測 vs 実績を一括照合して feedback_log に保存するスクリプト。

prediction_log の全過去レコード（target_date < 今日）を対象に:
1. market_data から実績価格を取得
2. AccuracyEvaluator + MultiFactorEvaluator で評価
3. 結果を feedback_log に保存（重複チェックあり）

実行方法:
    source venv/bin/activate
    python scripts/backfill_evaluations.py
"""

import logging
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()

from src.utils.database import (
    get_client,
    fetch_market_data_around_date,
    insert_feedback,
)
from evaluators.accuracy import AccuracyEvaluator
from evaluators import multi_factor


def fetch_all_past_predictions() -> list[dict]:
    """target_date が今日より前の予測を全件取得（銘柄・対象日でベスト1件に絞る）。"""
    client = get_client()
    today = str(date.today())
    result = (
        client.table("prediction_log")
        .select("id,symbol,target_date,predicted_price,current_price,timestamp,reasoning_text,prophet_params")
        .lt("target_date", today)
        .order("timestamp", desc=True)  # 最新のものを優先
        .execute()
    )

    # symbol + target_date の重複を除去（最新の予測1件を採用）
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in result.data:
        key = (r["symbol"], r["target_date"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def fetch_already_evaluated() -> set[tuple]:
    """feedback_log に保存済みの (symbol, target_date 相当) を返す。
    feedback_log に target_date カラムはないため timestamp の日付で代用。
    """
    client = get_client()
    result = client.table("feedback_log").select("symbol,timestamp").execute()
    already: set[tuple] = set()
    for r in result.data:
        ts = (r.get("timestamp") or "")[:10]
        already.add((r["symbol"], ts))
    return already


def get_actual_price(symbol: str, target_date: date) -> float | None:
    """target_date の前後3日以内の最近傍価格を返す。"""
    records = fetch_market_data_around_date(symbol, target_date, window_days=3)
    if not records:
        return None
    # target_date に最も近い日付のレコードを選ぶ
    best = min(
        records,
        key=lambda r: abs(
            (date.fromisoformat(r["timestamp"][:10]) - target_date).days
        ),
    )
    return float(best["price"])


def get_regressor_snapshot(target_date: date) -> dict[str, float]:
    """指定日前後3日の外生変数平均を返す。"""
    snapshot: dict[str, float] = {}
    for sym in ["BDI", "VIX", "Gold", "Oil", "DXY"]:
        records = fetch_market_data_around_date(sym, target_date, window_days=3)
        if records:
            prices = [float(r["price"]) for r in records]
            snapshot[sym] = round(sum(prices) / len(prices), 4)
    return snapshot


def main() -> None:
    logger.info("=== バックフィル評価 開始 ===")

    predictions = fetch_all_past_predictions()
    logger.info("過去の予測（重複除去後）: %d 件", len(predictions))

    evaluator = AccuracyEvaluator()
    ok_count = 0
    skip_no_actual = 0
    skip_already = 0
    error_count = 0

    for pred in predictions:
        symbol: str = pred["symbol"]
        target_date = date.fromisoformat(pred["target_date"])
        predicted_price = float(pred["predicted_price"])

        try:
            # 実績価格を取得
            actual_price = get_actual_price(symbol, target_date)
            if actual_price is None:
                logger.warning("[%s] %s の実績価格なし → スキップ", symbol, target_date)
                skip_no_actual += 1
                continue

            # 精度評価
            result = evaluator.evaluate(
                symbol=symbol,
                predicted=predicted_price,
                actual=actual_price,
            )

            # コンテキスト付与
            ts = pred.get("timestamp", "")
            try:
                predicted_date = date.fromisoformat(ts[:10]) if ts else None
            except ValueError:
                predicted_date = None

            result.predicted_date = predicted_date
            result.target_date = target_date
            result.current_price_at_pred = (
                float(pred["current_price"]) if pred.get("current_price") else None
            )
            result.reasoning_text = pred.get("reasoning_text") or ""
            result.regressors_at_pred = (
                get_regressor_snapshot(predicted_date) if predicted_date else {}
            )
            result.regressors_at_target = get_regressor_snapshot(target_date)

            # 多角評価
            mf_scores = multi_factor.compute(result)
            result.multi_factor_scores = mf_scores.to_dict()
            result.needs_improvement = not result.passed or mf_scores.direction_accuracy == 0

            # feedback_log に保存
            insert_feedback(
                symbol=symbol,
                error_rate=result.error_rate,
                self_reflection_notes=(
                    f"[backfill] 方向{'✅' if mf_scores.direction_accuracy else '❌'} "
                    f"| VIX補正MAPE {mf_scores.vix_adjusted_mape:.1f}% "
                    f"| 外部ショック {mf_scores.external_shock_score:.1f}%({mf_scores.shock_culprit})"
                ),
                parameter_updates={},
            )

            status = "✅合格" if result.passed else "❌要改善"
            dir_mark = "↑↓正" if mf_scores.direction_accuracy else "↑↓逆"
            logger.info(
                "[%s] %s | %s | MAPE=%.1f%% | %s | 予測:%.2f 実績:%.2f",
                symbol, target_date, status, result.error_rate, dir_mark,
                predicted_price, actual_price,
            )
            ok_count += 1

        except Exception as e:
            logger.error("[%s] %s 評価失敗: %s", symbol, target_date, e)
            error_count += 1

    logger.info("=== バックフィル評価 完了 ===")
    logger.info(
        "保存: %d件 / 実績なしスキップ: %d件 / エラー: %d件",
        ok_count, skip_no_actual, error_count,
    )


if __name__ == "__main__":
    main()
