"""既存 feedback_log に対して深いPDCA分析を遡及適用するスクリプト。

error_rate はあるが self_reflection_notes が空のレコードを全て対象に、
LLMJudge（Claude Haiku）が根本原因と改善策を分析して書き込む。

使い方:
    python scripts/enrich_feedback.py
"""

import sys
import time
import logging
from datetime import date

sys.path.insert(0, ".")

from src.utils.database import (
    fetch_feedbacks_needing_analysis,
    fetch_prediction,
    update_feedback_notes,
)
from src.models.prophet_wrapper import PARAM_SCHEMA
from harness.dataloader import DataLoader
from evaluators.base import EvaluationResult
from evaluators.llm_judge import LLMJudge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ANALYSIS_THRESHOLD_PCT = 5.0  # この誤差率(%)超のレコードを対象にする


def enrich_one(fb: dict, loader: DataLoader, judge: LLMJudge) -> bool:
    """1件の feedback_log レコードを分析して更新する。True=成功 / False=スキップ。"""
    fb_id = fb["id"]
    symbol = fb["symbol"]
    error_rate = float(fb["error_rate"])
    ts = fb.get("timestamp", "")

    # feedback_log の timestamp を target_date として使う
    try:
        target_date = date.fromisoformat(ts[:10])
    except (ValueError, TypeError):
        logger.warning("[%s] id=%d timestamp 不正。スキップ。", symbol, fb_id)
        return False

    # 対応する prediction_log を取得
    pred = fetch_prediction(symbol, target_date)
    if pred is None:
        logger.info("[%s] id=%d target_date=%s の予測なし。スキップ。", symbol, fb_id, target_date)
        return False

    predicted_price = float(pred["predicted_price"])
    actual_price = float(pred.get("current_price") or 0)
    # current_price は「予測時の価格」なので actual は別途推定
    # feedback_log に error_rate があるので actual を逆算: actual = predicted / (1 ± mape/100)
    # より正確には: MAPE = |pred - actual| / actual → actual ≈ pred / (1 + sign * mape/100)
    # 符号が不明なので current_price を fallback として使う
    if actual_price <= 0:
        # actual を error_rate から近似（MAPE 定義より）
        # 予測が高すぎた場合と低すぎた場合で符号が異なるが、MAPE 計算には影響しない
        actual_price = predicted_price / (1 + error_rate / 100)

    try:
        predicted_date_str = pred.get("timestamp", "")
        predicted_date = date.fromisoformat(predicted_date_str[:10]) if predicted_date_str else None
    except ValueError:
        predicted_date = None

    # EvaluationResult を構築
    result = EvaluationResult(
        symbol=symbol,
        error_rate=error_rate,
        predicted=predicted_price,
        actual=actual_price,
        passed=error_rate < 10.0,
        notes="",
        predicted_date=predicted_date,
        target_date=target_date,
        current_price_at_pred=float(pred["current_price"]) if pred.get("current_price") else None,
        reasoning_text=pred.get("reasoning_text") or "",
        regressors_at_pred=loader.load_regressor_snapshot(predicted_date) if predicted_date else {},
        regressors_at_target=loader.load_regressor_snapshot(target_date),
        prev_feedbacks=loader.load_prev_feedbacks(symbol, limit=5),
    )

    # 現在パラメータ（prediction_log の prophet_params を使用）
    current_params = pred.get("prophet_params") or {}

    # LLMJudge で分析
    try:
        reasoning, param_updates = judge.analyze(result, current_params)
    except Exception as e:
        logger.error("[%s] id=%d LLM分析失敗: %s", symbol, fb_id, e)
        return False

    if not reasoning:
        logger.info("[%s] id=%d 誤差が閾値未満のため分析スキップ。", symbol, fb_id)
        return False

    # feedback_log を更新
    update_feedback_notes(fb_id, reasoning, param_updates)
    logger.info("[%s] id=%d 更新完了: %s...", symbol, fb_id, reasoning[:60])
    return True


def run() -> None:
    logger.info("=== feedback_log 遡及分析 開始 ===")

    targets = fetch_feedbacks_needing_analysis(threshold_pct=ANALYSIS_THRESHOLD_PCT)
    logger.info("対象レコード: %d 件（MAPE > %.1f%%、notes 未記入）", len(targets), ANALYSIS_THRESHOLD_PCT)

    if not targets:
        logger.info("対象なし。全レコードに分析済み、または誤差が閾値以下です。")
        return

    loader = DataLoader()
    judge = LLMJudge()

    success = 0
    skip = 0
    for i, fb in enumerate(targets, 1):
        logger.info("[%d/%d] symbol=%s id=%d MAPE=%.1f%%",
                    i, len(targets), fb["symbol"], fb["id"], float(fb["error_rate"]))
        ok = enrich_one(fb, loader, judge)
        if ok:
            success += 1
        else:
            skip += 1
        # Claude API レートリミット対策
        if i < len(targets):
            time.sleep(1.0)

    logger.info("=== 完了: 更新 %d 件 / スキップ %d 件 ===", success, skip)


if __name__ == "__main__":
    run()
