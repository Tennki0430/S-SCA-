"""Skill: Discord Webhook への投稿。Merchant が使う再利用可能な通知能力。"""

import logging

import requests

from src.utils.config import DISCORD_WEBHOOK_URL
from src.utils.retry import retry

logger = logging.getLogger(__name__)


@retry(max_attempts=3, backoff_factor=2)
def post(message: str) -> bool:
    """Discord Webhook にメッセージを投稿する。成功なら True を返す。"""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL 未設定のためスキップ")
        return False
    resp = requests.post(
        DISCORD_WEBHOOK_URL,
        json={"content": message},
        timeout=15,
    )
    resp.raise_for_status()
    logger.info("Discord 投稿成功")
    return True
