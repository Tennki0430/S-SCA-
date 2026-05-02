"""Affiliate Writer Agent: 価格上昇予測時にアフィリエイト記事を生成してX/noteに自動投稿する。

Oracle が「銅 +8%」などを予測したとき、Claude Haiku が日本語記事を生成し
note.com（詳細記事）と X（短文アラート）に同時投稿する。

note 投稿は Playwright ブラウザ自動化（NOTE_EMAIL + NOTE_PASSWORD）を使用する。
フォールバックとして NOTE_SESSION_COOKIE（非公式API）も残す。
"""

import logging
import sys
import types
import urllib.parse
import yaml
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
    SYMBOLS,
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET,
    NOTE_EMAIL, NOTE_PASSWORD, NOTE_SESSION_COOKIE, NOTE_USERNAME,
    AMAZON_ASSOCIATE_TAG,
    PA_API_ACCESS_KEY, PA_API_SECRET_KEY,
    AFFILIATE_THRESHOLD_PCT,
)
from src.utils.amazon_paapi import search_best_product
from src.utils.database import fetch_prediction
from src.utils.retry import retry

# デフォルトnoteサムネイル（assets/note_thumbnail.png）
import pathlib
_DEFAULT_THUMBNAIL = pathlib.Path(__file__).parents[2] / "assets" / "note_thumbnail.png"
_AMAZON_LINKS_PATH = pathlib.Path(__file__).parents[2] / "config" / "amazon_links.yaml"

logger = logging.getLogger(__name__)


def _load_amazon_links() -> dict[str, dict[str, str]]:
    """config/amazon_links.yaml から銘柄ごとの Amazon 商品URLを読み込む。

    Returns:
        {symbol: {product_name: url}} 形式の辞書。
        URL が空欄の商品はキーに含まれない。
    """
    if not _AMAZON_LINKS_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(_AMAZON_LINKS_PATH.read_text(encoding="utf-8")) or {}
        result: dict[str, dict[str, str]] = {}
        for symbol, products in data.items():
            if not isinstance(products, list):
                continue
            urls = {
                p["name"]: p["url"]
                for p in products
                if isinstance(p, dict) and p.get("name") and p.get("url")
            }
            if urls:
                result[symbol] = urls
        return result
    except Exception as e:
        logger.warning("amazon_links.yaml 読み込み失敗: %s", e)
        return {}


# モジュール読み込み時に一度だけロード（GitHub Actions で毎回ファイルを読む）
_AMAZON_LINKS: dict[str, dict[str, str]] = _load_amazon_links()

JST = timezone(timedelta(hours=9))
AFFILIATE_POST_HOUR_JST = 9   # 毎朝9:00 JST に投稿

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 銘柄ごとのアフィリエイト設定
# products の第2要素は Amazon Associates リンクビルダーで生成した商品URLを推奨。
#   例: ("商品名", "https://www.amazon.co.jp/dp/B0XXXXXXXXX")
# URLが未設定の場合はキーワード文字列を入れると検索URLにフォールバックする。
#   例: ("商品名", "電動工具 充電式")
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


def _load_thumbnail() -> bytes | None:
    """assets/note_thumbnail.png を読み込んで返す。"""
    if _DEFAULT_THUMBNAIL.exists():
        logger.info("デフォルトサムネイルを使用: %s", _DEFAULT_THUMBNAIL.name)
        return _DEFAULT_THUMBNAIL.read_bytes()
    return None


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


def _amazon_url(url_or_keyword: str) -> str:
    """Amazon アフィリエイトURLを返す。

    url_or_keyword に "https://" で始まる URL を渡すとそのままタグを付けて返す。
    キーワード文字列を渡すと検索URLを生成する（フォールバック）。

    Associates リンクビルダーで生成した URL（dp/ASIN 形式）をそのまま渡すことを推奨。
    例: "https://www.amazon.co.jp/dp/B0XXXXXXXXX"
    """
    if url_or_keyword.startswith("http"):
        url = url_or_keyword.rstrip()
        if AMAZON_ASSOCIATE_TAG and "tag=" not in url:
            sep = "&" if "?" in url else "?"
            url += f"{sep}tag={AMAZON_ASSOCIATE_TAG}"
        return url
    # キーワード → 検索URL（商品URLが未設定の場合のフォールバック）
    params = {"k": url_or_keyword}
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
    symbol_links = _AMAZON_LINKS.get(symbol, {})

    # 商品リンク解決順: ① YAML手動設定 → ② PA API自動取得 → ③ キーワード検索URL
    product_lines = []
    for name, kw in info["products"]:
        if symbol_links.get(name):
            # ① YAML に URL が手動設定済み
            url = _amazon_url(symbol_links[name])
        else:
            # ② PA API で実際に売れている商品を検索
            pa_product = search_best_product(
                keyword=kw,
                access_key=PA_API_ACCESS_KEY,
                secret_key=PA_API_SECRET_KEY,
                associate_tag=AMAZON_ASSOCIATE_TAG,
            )
            if pa_product:
                url = pa_product.url
                name = pa_product.title[:40]  # 実際の商品名に置き換え
            else:
                # ③ フォールバック：キーワード検索URL
                url = _amazon_url(kw)
        product_lines.append(f"- {name}: {url}")

    products_text = "\n".join(product_lines)

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


def _post_note_playwright(
    title: str,
    body: str,
    hashtags: list[str],
    thumbnail_bytes: bytes | None = None,
) -> str | None:
    """Playwright ブラウザ自動化で note.com に記事を投稿し、公開URLを返す。

    NOTE_EMAIL / NOTE_PASSWORD で通常ログインするため、
    NOTE_SESSION_COOKIE の期限切れ問題を回避できる。
    """
    import os as _os
    import tempfile

    if not NOTE_EMAIL or not NOTE_PASSWORD:
        logger.info("NOTE_EMAIL/NOTE_PASSWORD 未設定。Playwright 投稿をスキップ。")
        return None

    tmp_path: str | None = None
    if thumbnail_bytes:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(thumbnail_bytes)
            tmp_path = f.name

    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        logger.warning("playwright がインストールされていません。`pip install playwright` を実行してください。")
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = ctx.new_page()

            # ── ログイン ──────────────────────────────────────────────
            page.goto("https://note.com/login", wait_until="networkidle", timeout=30000)
            page.fill("#email", NOTE_EMAIL)
            page.fill("#password", NOTE_PASSWORD)
            page.click('button:has-text("ログイン")')
            page.wait_for_timeout(5000)
            page.wait_for_load_state("networkidle")
            logger.info("note.com ログイン完了（URL: %s）", page.url)

            # ── 新規テキスト投稿ページ ─────────────────────────────────
            page.goto("https://note.com/notes/new", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # ── タイトル入力 ───────────────────────────────────────────
            page.wait_for_selector("textarea[placeholder='記事タイトル']", timeout=15000)
            page.fill("textarea[placeholder='記事タイトル']", title)
            page.wait_for_timeout(500)

            # ── 本文入力（ProseMirror） ────────────────────────────────
            editor = page.locator(".ProseMirror").last
            editor.click()
            page.keyboard.type(body, delay=5)
            page.wait_for_timeout(1000)

            # ── 「公開に進む」ボタン → 公開モーダルページへ ──────────
            page.click('button:has-text("公開に進む")', timeout=10000)
            page.wait_for_url("**/publish/**", timeout=15000)
            page.wait_for_timeout(2000)

            # ── アイキャッチ画像アップロード ──────────────────────────
            if tmp_path:
                # note の公開モーダルはファイル入力を label/div で隠しているため
                # set_input_files を直接呼ぶ
                file_input = page.locator('input[type="file"]')
                if file_input.count() > 0:
                    file_input.first.set_input_files(tmp_path)
                    page.wait_for_timeout(4000)
                    logger.info("アイキャッチ画像をアップロードしました")
                else:
                    logger.info("アイキャッチ file input が見つかりません。スキップ。")

            # ── ハッシュタグ追加 ──────────────────────────────────────
            tag_sel = "input[placeholder='ハッシュタグを追加する']"
            if page.locator(tag_sel).count() > 0:
                for tag in hashtags:
                    page.fill(tag_sel, tag)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(500)

            # ── 最終「投稿する」ボタン ────────────────────────────────
            page.click('button:has-text("投稿する")', timeout=10000)
            page.wait_for_timeout(5000)
            page.wait_for_load_state("networkidle")

            published_url = page.url
            browser.close()

        # editor.note.com/notes/{key}/publish → note.com/{user}/n/{key} へ変換
        if "editor.note.com/notes/" in published_url:
            note_key = published_url.split("/notes/")[1].split("/")[0]
            if NOTE_USERNAME:
                published_url = f"https://note.com/{NOTE_USERNAME}/n/{note_key}"

        if "note.com" in published_url:
            logger.info("note 投稿完了: %s", published_url)
            return published_url

        return None

    except Exception as e:
        logger.warning("Playwright note 投稿失敗: %s", e)
        return None
    finally:
        if tmp_path and _os.path.exists(tmp_path):
            _os.unlink(tmp_path)


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

            # note 投稿（Playwright 優先 → cookie フォールバック）
            thumbnail_bytes = _load_thumbnail()
            if NOTE_EMAIL and NOTE_PASSWORD:
                note_url = _post_note_playwright(
                    title, note_body, info["hashtags"], thumbnail_bytes
                )
            else:
                eyecatch_key = _upload_note_image(thumbnail_bytes)
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
