"""Affiliate Writer Agent: 価格上昇予測時にアフィリエイト記事を生成してX/noteに自動投稿する。

Oracle が「銅 +8%」などを予測したとき、Claude Haiku が日本語記事を生成し
note.com（詳細記事）と X（短文アラート）に同時投稿する。

note 投稿には非公式API（Cookie認証）を使用するため、
環境変数 NOTE_SESSION_COOKIE にブラウザの note_session_v5 Cookie 値を設定する。
"""

import logging
import sys
import types
import urllib.parse
from datetime import date, datetime, timedelta, timezone

if "imghdr" not in sys.modules:
    _imghdr = types.ModuleType("imghdr")
    _imghdr.what = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    sys.modules["imghdr"] = _imghdr

import anthropic
import requests
import tweepy

from src.utils.config import (
    ANTHROPIC_API_KEY,
    DISCORD_WEBHOOK_URL,
    SYMBOLS,
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET,
    NOTE_SESSION_COOKIE, NOTE_USERNAME,
    AMAZON_ASSOCIATE_TAG,
    AFFILIATE_THRESHOLD_PCT,
)
from src.utils.database import fetch_market_data, fetch_prediction
from src.utils.retry import retry
from src.utils.thumbnail import generate_chart

# デフォルトnoteサムネイル（assets/note_thumbnail.png）
import pathlib
_DEFAULT_THUMBNAIL = pathlib.Path(__file__).parents[2] / "assets" / "note_thumbnail.png"

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
AFFILIATE_POST_HOUR_JST = 9   # 毎朝9:00 JST に投稿

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 銘柄ごとのアフィリエイト設定
COMMODITY_MAP: dict[str, dict] = {
    "Copper": {
        "label": "銅",
        "lag_weeks": "1〜2ヶ月",
        "products": [
            ("充電式電動工具", "電動工具 充電式"),
            ("高耐久USBケーブル", "USBケーブル 高耐久"),
            ("延長コード・電線", "延長コード 耐熱"),
        ],
        "hashtags": ["銅価格上昇", "値上がり前に買う", "DIY", "電動工具"],
    },
    "Wheat": {
        "label": "小麦",
        "lag_weeks": "約1ヶ月",
        "products": [
            ("小麦粉まとめ買い", "小麦粉 業務用 まとめ買い"),
            ("パスタ・乾麺", "パスタ まとめ買い"),
            ("食品備蓄セット", "非常食 備蓄 セット"),
        ],
        "hashtags": ["小麦価格上昇", "食品備蓄", "値上がり前に買う", "まとめ買い"],
    },
    "Corn": {
        "label": "トウモロコシ",
        "lag_weeks": "約1ヶ月",
        "products": [
            ("食用油まとめ買い", "サラダ油 まとめ買い"),
            ("コーンスターチ", "コーンスターチ 業務用"),
            ("加工食品備蓄", "缶詰 まとめ買い"),
        ],
        "hashtags": ["食用油値上がり", "まとめ買い", "値上がり前に買う"],
    },
    "Naphtha": {
        "label": "ナフサ",
        "lag_weeks": "2〜3ヶ月",
        "products": [
            ("洗剤詰め替えまとめ買い", "洗剤 詰め替え まとめ買い"),
            ("ゴミ袋・ラップ備蓄", "ゴミ袋 まとめ買い"),
            ("シャンプー詰め替え", "シャンプー 詰め替え まとめ買い"),
        ],
        "hashtags": ["日用品値上がり", "まとめ買い", "値上がり前に買う"],
    },
    "Lithium": {
        "label": "リチウム",
        "lag_weeks": "2〜3ヶ月",
        "products": [
            ("ポータブル電源", "ポータブル電源 大容量"),
            ("大容量モバイルバッテリー", "モバイルバッテリー 大容量 急速充電"),
            ("電動自転車", "電動自転車 折りたたみ"),
        ],
        "hashtags": ["ポータブル電源", "リチウム価格", "値上がり前に買う", "防災"],
    },
}


def _build_thumbnails(
    symbol: str,
    label: str,
    predicted_price: float,
    target_date: date,
) -> tuple[bytes | None, bytes | None]:
    """価格グラフとnoteサムネイルを返す。

    Returns:
        (chart_bytes, thumbnail_bytes)
    """
    # 過去90日の価格データでグラフ生成
    chart_bytes: bytes | None = None
    rows = fetch_market_data(symbol, days=90)
    if len(rows) >= 5:
        dates = [datetime.fromisoformat(r["timestamp"]).date() for r in rows]
        prices = [float(r["price"]) for r in rows]
        chart_bytes = generate_chart(symbol, label, dates, prices, predicted_price, target_date)

    # noteサムネイル: assets/note_thumbnail.png を使用
    thumbnail_bytes: bytes | None = None
    if _DEFAULT_THUMBNAIL.exists():
        thumbnail_bytes = _DEFAULT_THUMBNAIL.read_bytes()
        logger.info("デフォルトサムネイルを使用: %s", _DEFAULT_THUMBNAIL.name)

    return chart_bytes, thumbnail_bytes


def _post_discord_chart(chart_bytes: bytes, caption: str) -> None:
    """価格チャートをDiscordに画像ファイルとして投稿する。"""
    if not DISCORD_WEBHOOK_URL or not chart_bytes:
        return
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": ("chart.png", chart_bytes, "image/png")},
            data={"content": caption},
            timeout=15,
        )
        logger.info("Discord グラフ投稿完了")
    except Exception as e:
        logger.warning("Discord グラフ投稿失敗: %s", e)


def _upload_note_image(image_bytes: bytes) -> str | None:
    """note.com に画像をアップロードし、eyecatch_key を返す。"""
    if not NOTE_SESSION_COOKIE or not image_bytes:
        return None
    try:
        resp = requests.post(
            "https://note.com/api/v2/attachments/image",
            headers={
                "Cookie": f"note_session_v5={NOTE_SESSION_COOKIE}",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            files={"image": ("thumbnail.png", image_bytes, "image/png")},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("key") or data.get("key")
    except Exception as e:
        logger.warning("note 画像アップロード失敗: %s", e)
        return None


def _amazon_url(keyword: str) -> str:
    """Amazon Japan 検索URLを生成する（アソシエイトタグ付き）。"""
    params = {"k": keyword}
    if AMAZON_ASSOCIATE_TAG:
        params["tag"] = AMAZON_ASSOCIATE_TAG
    return "https://www.amazon.co.jp/s?" + urllib.parse.urlencode(params)


def _generate_article(
    symbol: str,
    change_pct: float,
    current_price: float,
    predicted_price: float,
    target_date: date,
) -> tuple[str, str, str]:
    """Claude Haiku で note 記事本文・タイトル・X短文を生成する。

    Returns:
        (title, note_body, x_text)
    """
    info = COMMODITY_MAP[symbol]
    products_text = "\n".join(
        f"- {name}: {_amazon_url(kw)}" for name, kw in info["products"]
    )

    prompt = (
        f"あなたはコモディティ価格の値上がりを先読みするアフィリエイトライターです。\n\n"
        f"【予測データ】\n"
        f"銘柄: {info['label']}（{symbol}）\n"
        f"現在価格: ${current_price:.2f}\n"
        f"14日後（{target_date}）の予測価格: ${predicted_price:.2f}（{change_pct:+.1f}%）\n"
        f"消費者向け製品への波及タイミング: {info['lag_weeks']}後\n\n"
        f"【商品リスト（Amazonリンク付き）】\n"
        f"{products_text}\n\n"
        f"以下の形式で出力してください。他のテキスト不要。\n\n"
        f"[タイトル]\n"
        f"【値上がり警報】〜〜（50字以内）\n\n"
        f"[note本文]\n"
        f"note.comに投稿する記事（400〜600字）。\n"
        f"「なぜ今買うべきか」を冒頭で説明し、商品ごとにAmazonリンクを自然に組み込む。\n"
        f"文末に「*本記事はAIによる価格予測を元にした情報提供です。投資判断の根拠にはなりません。」を追加。\n\n"
        f"[X投稿]\n"
        f"140字以内。予測値と商品カテゴリを含み、記事への誘導文で締める。"
    )

    message = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text

    title = ""
    note_body = ""
    x_text = ""

    if "[タイトル]" in text and "[note本文]" in text:
        title = text.split("[タイトル]")[1].split("[note本文]")[0].strip()
    if "[note本文]" in text and "[X投稿]" in text:
        note_body = text.split("[note本文]")[1].split("[X投稿]")[0].strip()
    if "[X投稿]" in text:
        x_text = text.split("[X投稿]")[-1].strip()[:140]

    return title, note_body, x_text


@retry(max_attempts=3, backoff=2.0, exceptions=(Exception,))
def _post_note(
    title: str,
    body: str,
    hashtags: list[str],
    eyecatch_key: str | None = None,
) -> str | None:
    """note.com に記事を投稿し、公開URLを返す。失敗時は None。

    note.com は公式の投稿APIを公開していないため、ブラウザセッションCookieを使用する。
    NOTE_SESSION_COOKIE に Chrome/Safari の開発者ツールで取得した
    note_session_v5 Cookie の値を設定する。
    """
    if not NOTE_SESSION_COOKIE:
        logger.info("NOTE_SESSION_COOKIE 未設定。note 投稿をスキップ。")
        return None

    note_payload: dict = {
        "title": title,
        "body": body,
        "status": "public",
        "hashtag_list": hashtags,
    }
    if eyecatch_key:
        note_payload["eyecatch_key"] = eyecatch_key

    resp = requests.post(
        "https://note.com/api/v3/notes",
        headers={
            "Cookie": f"note_session_v5={NOTE_SESSION_COOKIE}",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
        json={"note": note_payload},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    note_key = (
        data.get("data", {}).get("key")
        or data.get("key")
        or data.get("data", {}).get("id")
    )
    if note_key and NOTE_USERNAME:
        return f"https://note.com/{NOTE_USERNAME}/n/{note_key}"
    return None


def _post_x(text: str) -> None:
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET]):
        logger.info("X API キー未設定。X 投稿をスキップ。")
        return
    try:
        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_SECRET,
        )
        client.create_tweet(text=text[:280])
        logger.info("X 投稿完了")
    except Exception as e:
        logger.warning("X 投稿失敗: %s", e)


def run() -> None:
    now_jst = datetime.now(JST)
    if now_jst.hour != AFFILIATE_POST_HOUR_JST:
        logger.info("投稿時間外（現在 %02d:00 JST）。アフィリエイト投稿をスキップ。", now_jst.hour)
        return

    logger.info("=== Affiliate Writer Agent 開始 ===")
    target_date = date.today() + timedelta(days=14)

    for symbol in SYMBOLS:
        if symbol not in COMMODITY_MAP:
            continue
        try:
            pred = fetch_prediction(symbol, target_date)
            if pred is None:
                logger.info("[%s] 予測レコードなし。スキップ。", symbol)
                continue

            current = float(pred["current_price"] or 0)
            predicted = float(pred["predicted_price"])
            if current == 0:
                continue

            change_pct = (predicted - current) / current * 100

            if change_pct < AFFILIATE_THRESHOLD_PCT:
                logger.info(
                    "[%s] 変動 %+.1f%% < 閾値 %.1f%%。スキップ。",
                    symbol, change_pct, AFFILIATE_THRESHOLD_PCT,
                )
                continue

            logger.info("[%s] 閾値超え（%+.1f%%）。記事生成開始。", symbol, change_pct)

            info = COMMODITY_MAP[symbol]
            title, note_body, x_text = _generate_article(
                symbol, change_pct, current, predicted, target_date
            )

            # グラフ・サムネイル生成
            chart_bytes, thumbnail_bytes = _build_thumbnails(
                symbol, info["label"], predicted, target_date
            )

            # Discord に価格チャートを投稿
            if chart_bytes:
                caption = (
                    f"**{info['label']} 価格予測チャート**\n"
                    f"{change_pct:+.1f}%  ${current:.2f} → ${predicted:.2f}\n"
                    f"（14日後: {target_date}）"
                )
                _post_discord_chart(chart_bytes, caption)

            # note に画像をアップロード → eyecatch_key 取得
            eyecatch_key = _upload_note_image(thumbnail_bytes or chart_bytes)

            # note に投稿 → URLを取得
            note_url = _post_note(title, note_body, info["hashtags"], eyecatch_key)
            if note_url:
                logger.info("[%s] note 投稿完了: %s", symbol, note_url)
                x_with_url = f"{x_text}\n{note_url}"
                _post_x(x_with_url[:280])
            else:
                _post_x(x_text)

        except Exception as e:
            logger.error("[%s] Affiliate Writer 処理失敗: %s", symbol, e)

    logger.info("=== Affiliate Writer Agent 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
