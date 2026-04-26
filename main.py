"""S-SCA オーケストレーター — GitHub Actions から呼び出されるエントリポイント。

Phase 1 時点では scout_price のみ実行。
Phase 2・3 で各エージェントを順次 import して追加していく。
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("main")


def run_pipeline() -> None:
    logger.info("========== S-SCA パイプライン 開始 ==========")

    # Supabase pause 防止（他のエージェントが全て失敗しても必ず実行）
    from src.utils.database import keepalive
    keepalive()
    logger.info("Keepalive 完了")

    # --- Phase 1 ---
    from src.agents import scout_price
    scout_price.run()

    # --- Phase 2 ---
    from src.agents import scout_logistics
    scout_logistics.run()

    from src.agents import scout_geopolitical
    scout_geopolitical.run()

    from src.agents import oracle
    oracle.run()

    from src.agents import merchant
    merchant.run()

    # --- Phase 3 ---
    from src.agents import accuracy_monitor
    accuracy_monitor.run()

    from src.agents import self_reflection
    self_reflection.run()

    logger.info("========== S-SCA パイプライン 完了 ==========")


if __name__ == "__main__":
    run_pipeline()
