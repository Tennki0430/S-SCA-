"""Hook: 予測精度が閾値を下回ったとき（MAPE > 10%）に LLM Judge を起動する。

harness/runner.py の C→A サイクルで呼ばれる。
"""

import logging

from evaluators.base import EvaluationResult
from evaluators.llm_judge import LLMJudge

logger = logging.getLogger(__name__)

_judge = LLMJudge()


def handle(result: EvaluationResult, current_params: dict) -> dict:
    """評価 FAIL のとき呼ばれ、改善パラメータ dict を返す。

    Returns:
        改善提案パラメータ dict（変更なしなら空 dict）
    """
    logger.info(
        "[Hook] on_evaluation_fail: %s MAPE=%.2f%%",
        result.symbol,
        result.error_rate,
    )
    updates = _judge.analyze(result, current_params)
    if updates:
        logger.info("[Hook] パラメータ更新案: %s", updates)
    return updates
