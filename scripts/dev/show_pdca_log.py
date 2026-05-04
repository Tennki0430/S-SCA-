"""PDCAサイクルの改善履歴を読みやすく表示するスクリプト。

feedback_log から以下を抽出して一覧表示する:
- 誤差の推移（MAPE の時系列）
- パラメータが変更された時点と変更内容
- 変更前後での精度の変化

実行方法:
    source venv/bin/activate
    python scripts/show_pdca_log.py
    python scripts/show_pdca_log.py --symbol Copper  # 銘柄を絞る
"""

import sys
import os
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.utils.database import get_client

PASS_THRESHOLD = 10.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="銘柄を絞る（例: Copper）")
    args = parser.parse_args()

    client = get_client()
    query = (
        client.table("feedback_log")
        .select("id,timestamp,symbol,error_rate,self_reflection_notes,parameter_updates")
        .not_.is_("error_rate", "null")
        .order("timestamp", desc=False)
    )
    if args.symbol:
        query = query.eq("symbol", args.symbol)
    result = query.execute()

    # 銘柄別に整理
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for r in result.data:
        by_symbol[r["symbol"]].append(r)

    symbols = [args.symbol] if args.symbol else sorted(by_symbol.keys())

    for symbol in symbols:
        records = by_symbol.get(symbol, [])
        if not records:
            continue

        print(f"\n{'=' * 60}")
        print(f"  {symbol} の PDCA 改善ログ（{len(records)}件）")
        print(f"{'=' * 60}")

        error_rates = [float(r["error_rate"]) for r in records]
        avg_mape = sum(error_rates) / len(error_rates)
        pass_count = sum(1 for e in error_rates if e < PASS_THRESHOLD)
        print(f"  平均MAPE: {avg_mape:.1f}%  |  合格率: {pass_count}/{len(records)} ({pass_count/len(records)*100:.0f}%)")

        # パラメータ変更があったレコードを抽出
        param_changes = [
            r for r in records
            if r.get("parameter_updates") and r["parameter_updates"] != {}
        ]
        print(f"  パラメータ変更: {len(param_changes)}回\n")

        # タイムライン表示
        prev_params: dict = {}
        for i, r in enumerate(records):
            ts = r["timestamp"][:10]
            er = float(r["error_rate"])
            status = "✅" if er < PASS_THRESHOLD else "❌"
            note = (r.get("self_reflection_notes") or "").replace("\n", " ")
            pu = r.get("parameter_updates") or {}

            # ノートの種別を判定
            if "[improvement_cycle]" in note:
                note_type = "🔧改善"
                note_body = note.replace("[improvement_cycle]", "").strip()
            elif "[backfill]" in note:
                note_type = "📊評価"
                note_body = note.replace("[backfill]", "").strip()
            else:
                note_type = "📝分析"
                note_body = note

            print(f"  {ts}  {status} MAPE={er:5.1f}%  {note_type}")

            # 根拠の要約（長い場合は切る）
            if note_body and note_type != "📊評価":
                short = note_body[:120] + "..." if len(note_body) > 120 else note_body
                print(f"    └ {short}")

            # パラメータ変更があれば変更前後を表示
            if pu:
                print(f"    └ 【パラメータ変更】")
                for k, v in pu.items():
                    before = prev_params.get(k, "(デフォルト)")
                    print(f"       {k}: {before} → {v}")

                # 変更後の精度改善を確認（次のレコードと比較）
                if i + 1 < len(records):
                    next_er = float(records[i + 1]["error_rate"])
                    delta = next_er - er
                    arrow = "↘改善" if delta < -0.5 else ("↗悪化" if delta > 0.5 else "→変化なし")
                    print(f"       効果: 次回 MAPE {er:.1f}% → {next_er:.1f}% ({arrow})")

                prev_params.update(pu)

        # サマリー：現在のパラメータ設定
        if prev_params:
            print(f"\n  【現在の適用パラメータ（最終変更値）】")
            for k, v in prev_params.items():
                print(f"    {k}: {v}")
        else:
            print(f"\n  【パラメータ変更なし → デフォルト値で稼働中】")

    # 全銘柄まとめ
    if not args.symbol:
        print(f"\n{'=' * 60}")
        print("  全銘柄サマリー")
        print(f"{'=' * 60}")
        print(f"  {'銘柄':10s} {'件数':>5s}  {'平均MAPE':>9s}  {'合格率':>7s}  {'改善回数':>8s}")
        print(f"  {'-'*55}")
        for symbol in sorted(by_symbol.keys()):
            recs = by_symbol[symbol]
            errs = [float(r["error_rate"]) for r in recs]
            avg = sum(errs) / len(errs)
            pct = sum(1 for e in errs if e < PASS_THRESHOLD) / len(errs) * 100
            changes = sum(1 for r in recs if r.get("parameter_updates") and r["parameter_updates"] != {})
            print(f"  {symbol:10s} {len(recs):>5d}件  {avg:>8.1f}%  {pct:>6.1f}%  {changes:>7d}回")


if __name__ == "__main__":
    main()
