"""Self-Reflection（LLM Judge）用 Claude プロンプト。"""

import json


def build_reflection_prompt(
    symbol: str,
    error_rate: float,
    schema_summary: dict,
    news_headlines: list[str] | None = None,
) -> str:
    news_section = ""
    if news_headlines:
        headlines_text = "\n".join(f"  - {h}" for h in news_headlines)
        news_section = (
            f"\n直近のニュース（誤差の外部要因として参考にしてください）:\n"
            f"{headlines_text}\n"
        )

    return (
        f"あなたは時系列予測モデル（Prophet）のチューニング専門家です。\n\n"
        f"銘柄: {symbol}\n"
        f"直近の予測誤差（MAPE）: {error_rate:.2f}%\n"
        f"{news_section}"
        f"現在のパラメータと調整可能範囲:\n"
        f"{json.dumps(schema_summary, ensure_ascii=False, indent=2)}\n\n"
        f"ニュースで示された外部要因（突発イベント・政策変更など）を考慮したうえで、"
        f"誤差を改善するために変更すべきパラメータを JSON のみで返してください。\n"
        f"変更不要なパラメータは含めないこと。返答は JSON のみ。\n"
        f"例: {{\"changepoint_prior_scale\": 0.1}}"
    )
