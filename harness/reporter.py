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
