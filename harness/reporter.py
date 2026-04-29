"""結果の集計・保存（PDCAのCとAの間）。

予測と実績を照合してスコアを出し、feedback_log に保存する。
結果が保存されないときはここを見る。
"""

import logging
from datetime import date

from src.utils.config import SYMBOLS
from src.utils.database import insert_feedback
from evaluators.accuracy import AccuracyEvaluator
from evaluators.base import EvaluationResult
from harness.dataloader import DataLoader

logger = logging.getLogger(__name__)


class Reporter:
    def __init__(self) -> None:
        self.evaluator = AccuracyEvaluator()
        self.loader = DataLoader()

    def evaluate_and_save(self) -> list[EvaluationResult]:
        """今日が target_date の予測を照合し、結果を feedback_log に保存して返す。"""
        target_date = date.today()
        results: list[EvaluationResult] = []

        for symbol in SYMBOLS:
            try:
                pred = self.loader.load_prediction(symbol, target_date)
                if pred is None:
                    logger.info(
                        "[%s] target_date=%s の予測なし（運用14日未満）。スキップ。",
                        symbol, target_date,
                    )
                    continue

                actual = self.loader.load_actual_price(symbol)
                if actual is None:
                    logger.warning("[%s] 実績価格を取得できません。スキップ。", symbol)
                    continue

                result = self.evaluator.evaluate(
                    symbol=symbol,
                    predicted=float(pred["predicted_price"]),
                    actual=actual,
                )

                # PDCA深掘り用コンテキストを付与
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
                    self.loader.load_regressor_snapshot(predicted_date)
                    if predicted_date else {}
                )
                result.regressors_at_target = self.loader.load_regressor_snapshot(target_date)
                result.prev_feedbacks = self.loader.load_prev_feedbacks(symbol, limit=5)

                insert_feedback(symbol=symbol, error_rate=result.error_rate)
                results.append(result)

            except Exception as e:
                logger.error("[%s] 照合失敗: %s", symbol, e)

        return results

    def save_llm_notes(
        self,
        symbol: str,
        error_rate: float,
        notes: str,
        param_updates: dict,
    ) -> None:
        insert_feedback(
            symbol=symbol,
            error_rate=error_rate,
            self_reflection_notes=notes,
            parameter_updates=param_updates,
        )
