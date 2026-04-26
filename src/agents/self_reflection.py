"""Self-Reflection: 予測誤差を Claude（Haiku）に分析させ、翌日の Prophet パラメータを更新する。"""

import json
import logging

import anthropic

from src.utils.config import ANTHROPIC_API_KEY, SYMBOLS
from src.utils.database import fetch_latest_params, insert_feedback
from src.utils.database import get_client
from src.models.prophet_wrapper import PARAM_SCHEMA

logger = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# この誤差率（%）未満なら調整不要
REFLECTION_THRESHOLD = 5.0


def _fetch_latest_error(symbol: str) -> float | None:
    """feedback_log から直近の error_rate を取得する。"""
    client = get_client()
    result = (
        client.table("feedback_log")
        .select("error_rate")
        .eq("symbol", symbol)
        .order("timestamp", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data or result.data[0]["error_rate"] is None:
        return None
    return float(result.data[0]["error_rate"])


def _ask_claude(symbol: str, error_rate: float, current_params: dict) -> dict:
    """Claude Haiku に誤差情報を渡し、改善パラメータを JSON で返させる。"""
    schema_summary = {
        k: {"current": current_params.get(k, v["default"]), "range": f"{v.get('min', v.get('options'))} 〜 {v.get('max', '')}"}
        for k, v in PARAM_SCHEMA.items()
    }
    prompt = (
        f"あなたは時系列予測モデル（Prophet）のチューニング専門家です。\n\n"
        f"銘柄: {symbol}\n"
        f"直近の予測誤差（MAPE）: {error_rate:.2f}%\n"
        f"現在のパラメータと調整可能範囲:\n{json.dumps(schema_summary, ensure_ascii=False, indent=2)}\n\n"
        f"誤差を改善するために変更すべきパラメータを JSON のみで返してください。\n"
        f"変更不要なパラメータは含めないこと。返答は JSON のみ。\n"
        f"例: {{\"changepoint_prior_scale\": 0.1}}"
    )
    message = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # JSON ブロックが含まれている場合に対応
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
        logger.warning("[%s] Claude の返答を JSON として解析できませんでした: %s", symbol, raw)
        return {}


def run() -> None:
    logger.info("=== Self-Reflection 開始 ===")

    for symbol in SYMBOLS:
        try:
            error_rate = _fetch_latest_error(symbol)
            if error_rate is None:
                logger.info("[%s] 誤差データなし（照合前）。スキップ。", symbol)
                continue

            if error_rate < REFLECTION_THRESHOLD:
                logger.info("[%s] 誤差 %.2f%% は閾値未満。パラメータ調整不要。", symbol, error_rate)
                continue

            current_params = fetch_latest_params(symbol)
            updates = _ask_claude(symbol, error_rate, current_params)

            if not updates:
                logger.info("[%s] Claude から更新パラメータなし。", symbol)
                continue

            insert_feedback(
                symbol=symbol,
                error_rate=error_rate,
                self_reflection_notes=f"誤差 {error_rate:.2f}% を受けてパラメータを更新: {updates}",
                parameter_updates=updates,
            )
            logger.info("[%s] パラメータ更新を保存しました: %s", symbol, updates)

        except Exception as e:
            logger.error("[%s] Self-Reflection 失敗: %s", symbol, e)

    logger.info("=== Self-Reflection 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
