"""Merchant Agent: 予測結果を Claude API で文章化し Discord / X に投稿する。"""

import logging
from datetime import date, timedelta

import anthropic
import requests
import tweepy

from src.utils.config import (
    ANTHROPIC_API_KEY,
    DISCORD_WEBHOOK_URL,
    SYMBOLS,
    ALERT_THRESHOLD_PCT,
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET,
)
from src.utils.database import fetch_prediction, insert_prediction
from src.utils.retry import retry

logger = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# 文章生成
# ---------------------------------------------------------------------------

def _generate_reasoning(
    symbol: str,
    current_price: float,
    predicted_price: float,
    change_pct: float,
    target_date: date,
) -> str:
    direction = "上昇" if change_pct > 0 else "下落"
    prompt = (
        f"あなたはコモディティ市場のアナリストです。\n"
        f"銘柄: {symbol}\n"
        f"現在価格: ${current_price:.2f}\n"
        f"14日後（{target_date}）の予測価格: ${predicted_price:.2f}（{change_pct:+.1f}%、{direction}）\n\n"
        f"物流指標（BDI）の動向を踏まえ、この予測の根拠を日本語で3文以内で簡潔に説明してください。"
        f"最後にX投稿用の140字以内の要約も追加してください。"
        f"フォーマット:\n[根拠]\n<3文以内の説明>\n[X投稿]\n<140字以内>"
    )
    message = claude.messages.create(
        model="claude-haiku-4-5-20251001",  # コスト最小化のため Haiku を使用
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _parse_x_post(reasoning_text: str) -> str:
    """reasoning_text から [X投稿] セクションを抽出する。"""
    if "[X投稿]" in reasoning_text:
        return reasoning_text.split("[X投稿]")[-1].strip()
    # フォールバック: 全文を 140 字に切る
    return reasoning_text[:140]


# ---------------------------------------------------------------------------
# 投稿
# ---------------------------------------------------------------------------

@retry(max_attempts=3, backoff=2.0, exceptions=(Exception,))
def _post_discord(content: str) -> None:
    resp = requests.post(
        DISCORD_WEBHOOK_URL,
        json={"content": content},
        timeout=10,
    )
    resp.raise_for_status()


def _post_x(text: str) -> None:
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET]):
        logger.info("X API キー未設定。X への投稿をスキップします。")
        return
    try:
        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_SECRET,
        )
        client.create_tweet(text=text[:280])
    except Exception as e:
        logger.warning("X への投稿失敗: %s", e)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def run() -> None:
    logger.info("=== Merchant Agent 開始 ===")
    target_date = date.today() + timedelta(days=14)

    for symbol in SYMBOLS:
        try:
            pred = fetch_prediction(symbol, target_date)
            if pred is None:
                logger.info("[%s] 本日の予測レコードなし。スキップ。", symbol)
                continue

            current = float(pred["current_price"] or 0)
            predicted = float(pred["predicted_price"])
            if current == 0:
                continue

            change_pct = (predicted - current) / current * 100

            # 閾値未満はアラート不要
            if abs(change_pct) < ALERT_THRESHOLD_PCT:
                logger.info("[%s] 変動 %+.1f%% は閾値未満。投稿をスキップ。", symbol, change_pct)
                continue

            reasoning = _generate_reasoning(symbol, current, predicted, change_pct, target_date)

            # reasoning_text を DB に書き戻す
            insert_prediction(
                symbol=symbol,
                target_date=target_date,
                predicted_price=predicted,
                current_price=current,
                reasoning_text=reasoning,
                prophet_params=pred.get("prophet_params"),
            )

            direction = "🔺" if change_pct > 0 else "🔻"
            discord_msg = (
                f"**【S-SCA アラート】{symbol}**\n"
                f"{direction} 現在: ${current:.2f} → 14日後予測: ${predicted:.2f} ({change_pct:+.1f}%)\n\n"
                f"{reasoning}"
            )
            _post_discord(discord_msg)
            logger.info("[%s] Discord 投稿完了", symbol)

            x_text = _parse_x_post(reasoning)
            _post_x(x_text)
            logger.info("[%s] X 投稿完了", symbol)

        except Exception as e:
            logger.error("[%s] Merchant 処理失敗: %s", symbol, e)

    logger.info("=== Merchant Agent 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
