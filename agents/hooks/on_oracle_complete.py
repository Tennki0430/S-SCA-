"""Hook: Oracle が予測を完了したとき Merchant を起動する。

harness/runner.py の P→D 遷移で呼ばれる。
"""

import logging

from src.agents import merchant

logger = logging.getLogger(__name__)


def handle() -> None:
    """Oracle 完了後に Discord / X へ投稿する。"""
    logger.info("[Hook] on_oracle_complete: Merchant 起動")
    merchant.run()
