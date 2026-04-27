"""パイプライン実行管理（オーケストレーター）。

PDCAサイクル全体を管理する。パイプラインが止まるときはここを見る。

P（Plan）   → agents/oracle.py       Prophet で14日後価格を予測
D（Do）     → agents/merchant.py     Discord/X に投稿
C（Check）  → evaluators/accuracy.py  予測精度を定量評価
A（Act）    → evaluators/llm_judge.py Claude がパラメータ改善案を提案
"""

import logging

from src.utils.database import keepalive, fetch_latest_params
from harness.reporter import Reporter
from evaluators.llm_judge import LLMJudge

logger = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(self) -> None:
        self.reporter = Reporter()
        self.llm_judge = LLMJudge()

    def run(self) -> None:
        logger.info("========== S-SCA パイプライン 開始 ==========")

        # Supabase pause 防止（最初に必ず実行）
        keepalive()
        logger.info("Keepalive 完了")

        # --- データ収集 ---
        from src.agents import scout_price, scout_logistics, scout_geopolitical, scout_news
        scout_price.run()
        scout_logistics.run()
        scout_geopolitical.run()
        scout_news.run()

        # --- P: Plan（予測） ---
        from src.agents import oracle
        oracle.run()

        # --- D: Do（投稿） ---
        from src.agents import merchant
        merchant.run()

        # --- C: Check（精度照合） ---
        logger.info("=== 精度照合（Check）開始 ===")
        results = self.reporter.evaluate_and_save()
        logger.info("=== 精度照合 完了（%d 件照合） ===", len(results))

        # --- A: Act（自律改善） ---
        logger.info("=== LLM Judge（Act）開始 ===")
        for result in results:
            if not result.passed:
                current_params = fetch_latest_params(result.symbol)
                param_updates = self.llm_judge.analyze(result, current_params)
                if param_updates:
                    notes = f"誤差 {result.error_rate:.2f}% → パラメータ更新: {param_updates}"
                    self.reporter.save_llm_notes(
                        result.symbol, result.error_rate, notes, param_updates
                    )
                    logger.info("[%s] パラメータ更新保存: %s", result.symbol, param_updates)
        logger.info("=== LLM Judge 完了 ===")

        logger.info("========== S-SCA パイプライン 完了 ==========")
