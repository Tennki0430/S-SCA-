"""LLM による定性的評価・パラメータ改善提案（PDCAのA）。

Claude Haiku に誤差の原因を多角的に分析させ、次の予測を改善するための
パラメータを提案させる。

提案できるパラメータ（PARAM_SCHEMA 参照）:
  changepoint_prior_scale  - トレンド変化への感度
  seasonality_prior_scale  - 季節性の強さ
  seasonality_mode         - additive / multiplicative
  window_days              - 学習に使う日数（30〜180）
  excluded_regressors      - ノイズになっている外生変数を除外するリスト

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

REFLECTION_THRESHOLD_PCT = 5.0   # MAPE がこの%以上なら分析実行
SHOCK_THRESHOLD_PCT = 10.0       # 外部ショックスコアがこの%以上なら特別分析


class LLMJudge:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def should_analyze(self, result: EvaluationResult) -> bool:
        """分析が必要かどうかを判定する。"""
        # MAPE が閾値以上
        if result.error_rate >= REFLECTION_THRESHOLD_PCT:
            return True
        # 方向を誤った（MAPE が小さくても方向誤りは要分析）
        mf = result.multi_factor_scores
        if mf.get("direction_accuracy") == 0:
            logger.info("[%s] 方向誤りのため分析実行（MAPE=%.2f%%）", result.symbol, result.error_rate)
            return True
        return False

    def analyze(
        self, result: EvaluationResult, current_params: dict
    ) -> tuple[str, dict]:
        """誤差情報を Claude に渡し、(原因分析テキスト, 改善パラメータ dict) を返す。

        Returns:
            reasoning: Claude による誤差原因の説明文
            param_updates: 変更すべきパラメータ dict（変更不要なら空 dict）
                           window_days, excluded_regressors も含む場合がある
        """
        if not self.should_analyze(result):
            logger.info("[%s] 誤差 %.2f%% / 方向正解 → 調整不要。", result.symbol, result.error_rate)
            return "", {}

        schema_summary = {
            k: {
                "current": current_params.get(k, v.get("default")),
                "range": (
                    f"{v.get('min')} 〜 {v.get('max')}"
                    if "min" in v else str(v.get("options", ""))
                ),
                "effect": _param_effect(k),
            }
            for k, v in PARAM_SCHEMA.items()
        }
        news_headlines = fetch_recent_news(result.symbol, limit=5)
        prompt = build_reflection_prompt(
            result, schema_summary, news_headlines, current_params
        )

        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
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

        # excluded_regressors が文字列で返ってきた場合はリストに変換
        if "excluded_regressors" in param_updates:
            val = param_updates["excluded_regressors"]
            if isinstance(val, str):
                param_updates["excluded_regressors"] = [
                    s.strip() for s in val.split(",") if s.strip()
                ]

        logger.info("[%s] 根本原因: %s", result.symbol, reasoning[:100])
        if param_updates:
            logger.info("[%s] パラメータ更新提案: %s", result.symbol, param_updates)
        return reasoning, param_updates


def _param_effect(key: str) -> str:
    effects = {
        "changepoint_prior_scale": "大きいほどトレンド変化に敏感。急変を見逃すなら上げる",
        "seasonality_prior_scale": "大きいほど季節性を強く反映",
        "holidays_prior_scale":    "祝日・イベントの影響度",
        "seasonality_mode":        "価格変動が比率的なら multiplicative",
        "window_days":             "小さくすると直近重視・大きくすると長期トレンド重視",
        "excluded_regressors":     "ノイズになっている外生変数を除外するリスト（例: ['Gold']）",
    }
    return effects.get(key, "")
