"""LLM による定性的評価・パラメータ改善提案（PDCAのA）。

Claude Haiku に誤差の原因を分析させ、次の Prophet パラメータを提案させる。
Claude の分析が甘い・厳しいと感じたときは agents/prompts/reflection.py を変更する。
"""

import json
import logging

import anthropic

from src.utils.config import ANTHROPIC_API_KEY
from src.utils.database import fetch_recent_news
from src.models.prophet_wrapper import PARAM_SCHEMA
from evaluators.base import EvaluationResult
from agents.prompts.reflection import build_reflection_prompt

logger = logging.getLogger(__name__)

REFLECTION_THRESHOLD_PCT = 5.0  # この誤差率(%)未満なら調整不要


class LLMJudge:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def analyze(
        self, result: EvaluationResult, current_params: dict
    ) -> tuple[str, dict]:
        """誤差情報を Claude に渡し、(原因分析テキスト, 改善パラメータ dict) を返す。

        Returns:
            reasoning: Claude による誤差原因の説明文
            param_updates: 変更すべきパラメータ dict（変更不要なら空 dict）
        """
        if result.error_rate < REFLECTION_THRESHOLD_PCT:
            logger.info("[%s] 誤差 %.2f%% は閾値未満。調整不要。", result.symbol, result.error_rate)
            return "", {}

        schema_summary = {
            k: {
                "current": current_params.get(k, v["default"]),
                "range": f"{v.get('min', v.get('options'))} 〜 {v.get('max', '')}",
            }
            for k, v in PARAM_SCHEMA.items()
        }
        news_headlines = fetch_recent_news(result.symbol, limit=5)
        prompt = build_reflection_prompt(
            result, schema_summary, news_headlines, current_params
        )

        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    parsed = json.loads(raw[start:end])
                except json.JSONDecodeError:
                    logger.warning("[%s] JSON 解析失敗: %s", result.symbol, raw)
                    return raw, {}
            else:
                logger.warning("[%s] JSON 解析失敗: %s", result.symbol, raw)
                return raw, {}

        reasoning = parsed.get("reasoning", "")
        param_updates = parsed.get("parameter_updates", {})
        logger.info("[%s] 原因: %s", result.symbol, reasoning)
        return reasoning, param_updates
