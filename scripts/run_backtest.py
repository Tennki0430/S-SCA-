"""バックテストを実行し、結果を JSON 保存 + Discord 通知する。

使い方（プロジェクトルートから）:
    python scripts/run_backtest.py
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

# Prophet / cmdstanpy の verbose ログを抑制してから import
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
for noisy in ("prophet", "cmdstanpy", "stan", "pystan"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

sys.path.insert(0, str(Path(__file__).parents[1]))

import requests

from evaluators.backtest import BacktestEvaluator
from src.utils.config import DISCORD_WEBHOOK_URL

OUTPUT_PATH = Path(__file__).parents[1] / "data" / "backtest_results.json"
PASS_THRESHOLD_PCT = 10.0


def main() -> None:
    print(f"[{date.today()}] バックテスト開始（全銘柄 / 90日間 / 14日先予測）")

    evaluator = BacktestEvaluator()
    results = evaluator.run_all()

    # JSON 保存（ダッシュボードから参照）
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"run_at": date.today().isoformat(), "results": results}
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"結果を保存: {OUTPUT_PATH}")

    # ターミナルサマリー
    print("\n=== バックテスト結果 ===")
    ok_results = [r for r in results if r["status"] == "ok"]
    passed_count = sum(1 for r in ok_results if r["passed"])
    for r in results:
        if r["status"] == "ok":
            icon = "✅" if r["passed"] else "❌"
            print(f"{icon} {r['symbol']:<10} MAPE {r['avg_mape']:5.1f}%  ({r['windows']}窓)")
        else:
            print(f"⚠️  {r['symbol']:<10} {r['status']}")
    print(f"\n合格（MAPE<{PASS_THRESHOLD_PCT:.0f}%）: {passed_count}/{len(ok_results)} 銘柄")

    # Discord 通知
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL 未設定。通知をスキップ。")
        return

    lines = [
        f"📊 **バックテスト完了** ({date.today()})",
        f"90日間・14日先予測・スライディングウィンドウ（{PASS_THRESHOLD_PCT:.0f}%以内を合格）",
        "",
    ]
    for r in results:
        if r["status"] == "ok":
            icon = "🟢" if r["passed"] else "🔴"
            lines.append(
                f"{icon} **{r['symbol']}**: 平均MAPE **{r['avg_mape']:.1f}%** ({r['windows']}窓)"
            )
        else:
            lines.append(f"⚠️  **{r['symbol']}**: データ不足")

    lines += [
        "",
        f"合格: **{passed_count}/{len(ok_results)}** 銘柄",
        "→ 本番の精度評価（prediction_log vs 実績）は14日ごとに累積します",
    ]

    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": "\n".join(lines)},
            timeout=15,
        )
        print("Discord に通知しました")
    except Exception as e:
        print(f"Discord 通知失敗: {e}")


if __name__ == "__main__":
    main()
