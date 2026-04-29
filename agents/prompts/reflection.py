"""Self-Reflection（LLM Judge）用 Claude プロンプト。

Claude が深いPDCA分析を行えるよう、以下の情報を全て渡す:
  - 予測時・実績時の先行指標の変化量
  - 多角的評価スコア（方向精度・VIX補正MAPE・外部ショックスコア）
  - 予測根拠（reasoning_text）
  - 過去の誤差パターン
  - 拡張パラメータ（window_days・excluded_regressors）の説明
"""

import json
from evaluators.base import EvaluationResult


def build_reflection_prompt(
    result: EvaluationResult,
    schema_summary: dict,
    news_headlines: list[str] | None = None,
    current_params: dict | None = None,
) -> str:
    # 予測方向の正誤
    baseline = result.current_price_at_pred or result.actual
    pred_direction = result.predicted - baseline
    actual_direction = result.actual - baseline
    direction_ok = (pred_direction >= 0) == (actual_direction >= 0)
    direction_label = "正しい" if direction_ok else "逆（モデルが方向を誤った）"

    pred_pct = (pred_direction / baseline * 100) if baseline else 0
    actual_pct = (actual_direction / baseline * 100) if baseline else 0

    # 先行指標の変化量
    reg_lines = []
    for sym in ["BDI", "VIX", "Gold", "Oil", "DXY"]:
        v_pred = result.regressors_at_pred.get(sym)
        v_tgt = result.regressors_at_target.get(sym)
        if v_pred and v_tgt and v_pred > 0:
            chg = (v_tgt - v_pred) / v_pred * 100
            reg_lines.append(f"  - {sym}: {v_pred:.2f} -> {v_tgt:.2f}  ({chg:+.1f}%)")
        elif v_pred:
            reg_lines.append(f"  - {sym}: {v_pred:.2f} (実績時データなし)")
        else:
            reg_lines.append(f"  - {sym}: データなし")
    regressors_text = "\n".join(reg_lines) if reg_lines else "  (データなし)"

    # 多角的評価スコア
    mf = result.multi_factor_scores
    mf_direction = mf.get("direction_accuracy", "-")
    mf_vix_mape = mf.get("vix_adjusted_mape", "-")
    mf_shock = mf.get("external_shock_score", "-")
    mf_culprit = mf.get("shock_culprit", "不明")
    mf_completeness = mf.get("data_completeness", "-")
    vix_at_pred = result.regressors_at_pred.get("VIX", 0)

    mf_text = (
        f"  - 方向精度: {'✅ 正解' if mf_direction == 1 else '❌ 方向を誤った'}\n"
        f"  - VIX補正MAPE: {mf_vix_mape:.1f}%（VIX={vix_at_pred:.1f}、補正後の実効誤差）\n"
        f"  - 外部ショックスコア: {mf_shock:.1f}%（最大変動: {mf_culprit}）\n"
        f"  - データ完全性: {mf_completeness * 100:.0f}%"
        if isinstance(mf_direction, int) else "  (データなし)"
    )

    # 過去の誤差履歴
    if result.prev_feedbacks:
        fb_lines = []
        for fb in result.prev_feedbacks:
            ts = (fb.get("timestamp") or "")[:10]
            er = fb.get("error_rate")
            note = fb.get("self_reflection_notes") or ""
            er_str = f"{float(er):.1f}%" if er is not None else "-"
            short_note = note[:80] + "..." if len(note) > 80 else note
            fb_lines.append(f"  - {ts}: MAPE {er_str}  ({short_note})")
        prev_text = "\n".join(fb_lines)
    else:
        prev_text = "  (履歴なし / 初回評価)"

    # ニュース
    news_text = ""
    if news_headlines:
        news_text = "\n直近ニュース（外部ショックの参考）:\n" + "\n".join(
            f"  - {h}" for h in news_headlines
        )

    param_text = json.dumps(current_params or {}, ensure_ascii=False)

    return (
        "あなたはコモディティ価格予測AI（Prophet）のPDCAサイクル担当アナリストです。\n"
        "以下の情報を元に「なぜ予測が外れたか」を根本原因まで特定し、\n"
        "次回の予測精度を上げるための具体的なパラメータ改善を提案してください。\n\n"

        "=== 予測の概要 ===\n"
        f"銘柄: {result.symbol}\n"
        f"予測実行日: {result.predicted_date}\n"
        f"予測対象日: {result.target_date}（14日後）\n"
        f"予測時の市場価格: ${baseline:.4f}\n"
        f"予測価格: ${result.predicted:.4f}  ({pred_pct:+.1f}% の変動を予測)\n"
        f"実績価格: ${result.actual:.4f}  (実際は {actual_pct:+.1f}% 変動)\n"
        f"予測誤差（MAPE）: {result.error_rate:.2f}%\n"
        f"予測の方向性: {direction_label}\n\n"

        "=== 多角的評価スコア ===\n"
        f"{mf_text}\n\n"

        "=== Oracle が予測時に記録した根拠 ===\n"
        f"{result.reasoning_text or '(記録なし)'}\n\n"

        "=== 先行指標の動き（予測実行時 -> 実績時） ===\n"
        "  ※ BDI上昇=物流活発、VIX上昇=市場不安、Gold上昇=リスク回避、"
        "Oil上昇=コスト増、DXY上昇=ドル高（コモディティ安）\n"
        f"{regressors_text}\n\n"

        "=== この銘柄の直近誤差履歴（繰り返しパターンの確認） ===\n"
        f"{prev_text}\n"
        f"{news_text}\n\n"

        "=== 現在のパラメータ（調整対象） ===\n"
        f"{param_text}\n\n"
        "調整可能なパラメータと効果:\n"
        f"{json.dumps(schema_summary, ensure_ascii=False, indent=2)}\n\n"

        "【分析指針】以下の5点を踏まえて根本原因を特定してください:\n"
        "1. 方向を誤った場合 → どの外生変数がモデルを誤った方向に引っ張ったか？\n"
        "   その変数を excluded_regressors で除外すべきか？\n"
        "2. 外部ショックスコアが高い場合 → 一時的な外部要因か？\n"
        "   window_days を短くして直近データを重視すべきか？\n"
        "3. MAPEが高く方向も正しい場合 → changepoint_prior_scale を調整すべきか？\n"
        "4. 誤差が繰り返し発生している場合 → 構造的な問題。seasonality_mode の変更を検討。\n"
        "5. データ完全性が低い場合 → 外生変数データ不足が原因の可能性がある。\n\n"

        "【重要】外部ショックスコアが15%以上の場合は、パラメータ変更より\n"
        "「一時的な外部要因による誤差」と結論付け、parameter_updates は最小限にすること。\n\n"

        "以下のJSON形式のみで返してください（他のテキスト不要）:\n"
        "{\n"
        '  "reasoning": "根本原因の特定（上記5点を踏まえて3〜5文で具体的に）",\n'
        '  "parameter_updates": {\n'
        '    "changepoint_prior_scale": 数値,\n'
        '    "window_days": 整数(30〜180),\n'
        '    "excluded_regressors": ["除外する変数名"]\n'
        '  }\n'
        "}\n\n"
        "変更不要なパラメータは含めないこと。全て変更不要なら parameter_updates は {} にすること。"
    )
