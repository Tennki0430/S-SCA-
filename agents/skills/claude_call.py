"""Skill: Claude Haiku への API 呼び出し。Merchant と LLM Judge が使う共通能力。"""

import logging

from anthropic import Anthropic

from src.utils.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def call(prompt: str, max_tokens: int = 512) -> str:
    """Claude Haiku にプロンプトを送り、テキスト応答を返す。

    コスト管理のため呼び出し箇所は merchant / llm_judge の 2 箇所に限定する。
    """
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.content[0].text
    logger.info("Claude 呼び出し完了 (tokens: %d)", response.usage.output_tokens)
    return result
