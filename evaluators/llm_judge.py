"""LLM による定性的評価・パラメータ改善提案（PDCAのA）。

Claude Haiku に誤差の原因を分析させ、次の Prophet パラメータを提案させる。
Claude の分析が甘い・厳しいと感じたときは agents/prompts/reflection.py を変更する。
"""

import json
import logging

import anthropic

from src.utils.config import ANTHROPIC_API_KEY
from src.models.prophet_wrapper import PARAM_SCHEMA
from evaluators.base import EvaluationResult
from agents.prompts.reflection import build_reflection_prompt

logger = logging.getLogger(__name__)

REFLECTION_THRESHOLD_PCT = 5.0  # この誤差率(%)未満なら調整不要


class LLMJudge:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def analyze(self, result: EvaluationResult, current_params: dict) -> dict:
        """誤差情報を Claude に渡し、改善パラメータを dict で返す。不要なら空 dict。"""
        if result.error_rate < REFLECTION_THRESHOLD_PCT:
            logger.info("[%s] 誤差 %.2f%% は閾値未満。調整不要。", result.symbol, result.error_rate)
            return {}

        schema_summary = {
            k: {
                "current": current_params.get(k, v["default"]),
                "range": f"{v.get('min', v.get('options'))} 〜 {v.get('max', '')}",
            }
            for k, v in PARAM_SCHEMA.items()
        }
        prompt = build_reflection_prompt(result.symbol, result.error_rate, schema_summary)

        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(raw[start:end])
            logger.warning("[%s] Claude の返答を JSON として解析できませんでした: %s", result.symbol, raw)
            return {}
