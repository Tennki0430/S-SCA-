"""Self-Reflection（LLM Judge）用 Claude プロンプト。

Claude が深いPDCA分析を行えるよう、予測時・実績時の先行指標の変化量、
予測根拠（reasoning_text）、過去の誤差パターンを全て渡す。
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

    # 変動率
    pred_pct = (pred_direction / baseline * 100) if baseline else 0
    actual_pct = (actual_direction / baseline * 100) if baseline else 0

    # 先行指標の変化量
    reg_lines = []
    for sym in ["BDI", "VIX", "Gold", "Oil", "DXY"]:
        v_pred = result.regressors_at_pred.get(sym)
        v_tgt = result.regressors_at_target.get(sym)
        if v_pred and v_tgt and v_pred > 0:
            chg = (v_tgt - v_pred) / v_pred * 100
            reg_lines.append(
                f"  - {sym}: {v_pred:.2f} -> {v_tgt:.2f}  ({chg:+.1f}%)"
            )
        elif v_pred:
            reg_lines.append(f"  - {sym}: {v_pred:.2f} (実績時データなし)")
        else:
            reg_lines.append(f"  - {sym}: データなし")
    regressors_text = "\n".join(reg_lines) if reg_lines else "  (データなし)"

    # 過去の誤差履歴
    if result.prev_feedbacks:
        fb_lines = []
        for fb in result.prev_feedbacks:
            ts = (fb.get("timestamp") or "")[:10]
            er = fb.get("error_rate")
            note = fb.get("self_reflection_notes") or ""
            er_str = f"{float(er):.1f}%" if er is not None else "-"
            short_note = note[:60] + "..." if len(note) > 60 else note
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

    # 現在パラメータ
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

        "=== Oracle が予測時に記録した根拠 ===\n"
        f"{result.reasoning_text or '(記録なし)'}\n\n"

        "=== 先行指標の動き（予測実行時 -> 実績時） ===\n"
        "  ※ BDI上昇=物流活発、VIX上昇=市場不安、Gold上昇=リスク回避、"
        "Oil上昇=コスト増、DXY上昇=ドル高（コモディティ安）\n"
        f"{regressors_text}\n\n"

        "=== この銘柄の直近誤差履歴（繰り返しパターンの確認） ===\n"
        f"{prev_text}\n"
        f"{news_text}\n\n"

        "=== 現在のProphetパラメータ（調整対象） ===\n"
        f"{param_text}\n\n"
        "調整可能範囲:\n"
        f"{json.dumps(schema_summary, ensure_ascii=False, indent=2)}\n\n"

        "【分析指針】以下の4点を踏まえて根本原因を特定してください:\n"
        "1. 予測方向は正しかったか？方向を誤った場合は何がモデルを惑わせたか？\n"
        "2. 先行指標の中で最も予測に影響した指標はどれか、その変化は想定外だったか？\n"
        "3. これは一時的な外部ショック（ニュース・地政学）か、モデルの構造的な問題か？\n"
        "4. 過去の誤差履歴と比較して、誤差は改善傾向か悪化傾向か？\n\n"

        "以下のJSON形式のみで返してください（他のテキスト不要）:\n"
        "{\n"
        '  "reasoning": "根本原因の特定（上記4点を踏まえて3〜5文で具体的に）",\n'
        '  "parameter_updates": {"変更するパラメータ名": 新しい値}\n'
        "}\n\n"
        "変更不要なパラメータは含めないこと。変更不要なら parameter_updates は {} にすること。"
    )
