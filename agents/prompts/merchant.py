"""Merchant エージェント用 Claude プロンプト。"""

from datetime import date


def build_analysis_prompt(
    symbol: str,
    current_price: float,
    predicted_price: float,
    change_pct: float,
    target_date: date,
) -> str:
    direction = "上昇" if change_pct > 0 else "下落"
    return (
        f"あなたはコモディティ市場のアナリストです。\n"
        f"銘柄: {symbol}\n"
        f"現在価格: ${current_price:.2f}\n"
        f"14日後（{target_date}）の予測価格: ${predicted_price:.2f}（{change_pct:+.1f}%、{direction}）\n\n"
        f"物流指標（BDI）および地政学リスク（VIX・金・原油・ドル指数）の動向を踏まえ、"
        f"この予測の根拠を日本語で3文以内で簡潔に説明してください。"
        f"最後にX投稿用の140字以内の要約も追加してください。\n"
        f"フォーマット:\n[根拠]\n<3文以内の説明>\n[X投稿]\n<140字以内>"
    )
