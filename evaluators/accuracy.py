"""定量的精度評価（MAPE）。

採点が厳しすぎる・甘すぎると感じたときは PASS_THRESHOLD_PCT を変更する。
"""

import logging
from evaluators.base import BaseEvaluator, EvaluationResult

logger = logging.getLogger(__name__)

PASS_THRESHOLD_PCT = 10.0  # 誤差がこの%未満なら合格


class AccuracyEvaluator(BaseEvaluator):
    def evaluate(self, symbol: str, predicted: float, actual: float) -> EvaluationResult:
        error_rate = abs(actual - predicted) / actual * 100
        passed = error_rate < PASS_THRESHOLD_PCT
        notes = (
            f"予測 ${predicted:.2f} / 実績 ${actual:.2f} / "
            f"誤差 {error_rate:.2f}% → {'✅ 合格' if passed else '❌ 要改善'}"
        )
        logger.info("[%s] %s", symbol, notes)
        return EvaluationResult(
            symbol=symbol,
            error_rate=error_rate,
            predicted=predicted,
            actual=actual,
            passed=passed,
            notes=notes,
        )
