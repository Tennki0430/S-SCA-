"""バックフィルデータに対して LLM Judge を実行し、パラメータ改善案を生成するスクリプト。

通常は GitHub Actions で毎時自動実行されるが、
バックフィルデータ（199件）に対して今すぐ改善サイクルを回したい場合に使う。

対象：誤差率が高い、または方向を頻繁に誤っている銘柄の直近レコード。

実行方法:
    source venv/bin/activate
    python scripts/run_improvement_cycle.py
"""

import logging
import sys
import os
from datetime import date

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
    fetch_latest_params,
    insert_feedback,
)
from evaluators.accuracy import AccuracyEvaluator
from evaluators import multi_factor
from evaluators.base import EvaluationResult
from evaluators.llm_judge import LLMJudge


# 改善対象とする条件（MAPEがこれ以上 OR 方向誤りが多い銘柄）
MAPE_THRESHOLD = 5.0


def _get_regressor_snapshot(target_date: date) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    for sym in ["BDI", "VIX", "Gold", "Oil", "DXY"]:
        records = fetch_market_data_around_date(sym, target_date, window_days=3)
        if records:
            prices = [float(r["price"]) for r in records]
            snapshot[sym] = round(sum(prices) / len(prices), 4)
    return snapshot


def fetch_worst_predictions(symbol: str, limit: int = 3) -> list[dict]:
    """誤差が大きい過去予測を取得（LLM Judge の入力用）。"""
    client = get_client()
    today = str(date.today())
    result = (
        client.table("prediction_log")
        .select("id,symbol,target_date,predicted_price,current_price,timestamp,reasoning_text")
        .eq("symbol", symbol)
        .lt("target_date", today)
        .order("timestamp", desc=True)
        .limit(50)
        .execute()
    )

    evaluator = AccuracyEvaluator()
    scored: list[tuple[float, dict]] = []
    for pred in result.data:
        actual_records = fetch_market_data_around_date(
            symbol,
            date.fromisoformat(pred["target_date"]),
            window_days=3,
        )
        if not actual_records:
            continue
        actual = float(
            min(actual_records,
                key=lambda r: abs((date.fromisoformat(r["timestamp"][:10]) -
                                   date.fromisoformat(pred["target_date"])).days))
            ["price"]
        )
        ev = evaluator.evaluate(symbol, float(pred["predicted_price"]), actual)
        scored.append((ev.error_rate, {**pred, "_actual": actual}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def main() -> None:
    logger.info("=== 改善サイクル（LLM Judge バックフィル実行）開始 ===")

    # 改善対象銘柄を統計から決定
    client = get_client()
    fb = client.table("feedback_log").select("symbol,error_rate").execute()

    from collections import defaultdict
    symbol_errs: dict[str, list[float]] = defaultdict(list)
    for r in fb.data:
        if r["error_rate"]:
            symbol_errs[r["symbol"]].append(float(r["error_rate"]))

    target_symbols = [
        sym for sym, errs in symbol_errs.items()
        if len(errs) > 0 and sum(errs) / len(errs) >= MAPE_THRESHOLD
    ]
    logger.info("改善対象銘柄（平均MAPE≥%.1f%%）: %s", MAPE_THRESHOLD, target_symbols)

    judge = LLMJudge()
    evaluator = AccuracyEvaluator()

    for symbol in target_symbols:
        logger.info("[%s] 直近ワースト予測を取得...", symbol)
        worst_preds = fetch_worst_predictions(symbol, limit=1)  # 最悪の1件を代表として使う

        if not worst_preds:
            logger.warning("[%s] 対象予測なし", symbol)
            continue

        pred = worst_preds[0]
        actual = pred["_actual"]
        target_date = date.fromisoformat(pred["target_date"])
        predicted_price = float(pred["predicted_price"])

        # EvaluationResult を構成
        result = evaluator.evaluate(symbol, predicted_price, actual)

        ts = pred.get("timestamp", "")
        try:
            predicted_date = date.fromisoformat(ts[:10]) if ts else None
        except ValueError:
            predicted_date = None

        result.predicted_date = predicted_date
        result.target_date = target_date
        result.current_price_at_pred = float(pred["current_price"]) if pred.get("current_price") else None
        result.reasoning_text = pred.get("reasoning_text") or ""
        result.regressors_at_pred = _get_regressor_snapshot(predicted_date) if predicted_date else {}
        result.regressors_at_target = _get_regressor_snapshot(target_date)
        result.prev_feedbacks = [
            r for r in
            client.table("feedback_log")
            .select("timestamp,error_rate,self_reflection_notes,parameter_updates")
            .eq("symbol", symbol)
            .not_.is_("error_rate", "null")
            .order("timestamp", desc=True)
            .limit(5)
            .execute().data
        ]

        mf_scores = multi_factor.compute(result)
        result.multi_factor_scores = mf_scores.to_dict()
        result.needs_improvement = True  # バックフィル分は強制的に改善対象

        # 現在のパラメータを取得
        current_params = fetch_latest_params(symbol)

        logger.info(
            "[%s] ワースト: target=%s MAPE=%.1f%% 方向=%s",
            symbol, target_date, result.error_rate,
            "✅" if mf_scores.direction_accuracy else "❌",
        )

        # LLM Judge 実行
        reasoning, param_updates = judge.analyze(result, current_params)
        if reasoning or param_updates:
            insert_feedback(
                symbol=symbol,
                error_rate=result.error_rate,
                self_reflection_notes=f"[improvement_cycle] {reasoning}",
                parameter_updates=param_updates,
            )
            logger.info("[%s] 改善案を保存 → %s", symbol, param_updates)
        else:
            logger.info("[%s] 改善不要と判断", symbol)

    logger.info("=== 改善サイクル 完了 ===")


if __name__ == "__main__":
    main()
