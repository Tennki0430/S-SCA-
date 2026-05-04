"""Affiliate Writer Agent: 価格上昇予測時にアフィリエイト記事を生成してX/noteに自動投稿する。

Oracle が「銅 +8%」などを予測したとき、Claude Haiku が日本語記事を生成し
note.com（詳細記事）と X（短文アラート）に同時投稿する。

note 投稿は Playwright セッション方式（scripts/setup_note_session.py で取得）を使用する。
"""

import logging
import re
import sys
import time
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
    NOTE_USERNAME,
    AMAZON_ASSOCIATE_TAG,
    AFFILIATE_THRESHOLD_PCT,
)
from src.utils.database import fetch_prediction

# デフォルトnoteサムネイル（assets/note_thumbnail.png）
import pathlib
_DEFAULT_THUMBNAIL = pathlib.Path(__file__).parents[2] / "assets" / "note_thumbnail.png"
_AMAZON_LINKS_PATH = pathlib.Path(__file__).parents[2] / "config" / "amazon_links.yaml"

logger = logging.getLogger(__name__)

_AMAZON_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}


def _get_asin(keyword: str) -> str | None:
    """Amazon Japan でキーワード検索し、最初の商品の ASIN を返す。

    data-asin 属性（10 文字英数字）を HTML から抽出する。
    取得失敗時は None を返す（呼び出し元が検索 URL にフォールバック）。
    """
    try:
        url = "https://www.amazon.co.jp/s?k=" + urllib.parse.quote(keyword)
        resp = requests.get(url, headers=_AMAZON_SEARCH_HEADERS, timeout=15)
        resp.raise_for_status()
        asins = re.findall(r'data-asin="([A-Z0-9]{10})"', resp.text)
        valid = [a for a in asins if a]
        asin = valid[0] if valid else None
        if asin:
            logger.info("[ASIN] '%s' → %s", keyword[:30], asin)
        return asin
    except Exception as e:
        logger.warning("[ASIN] 取得失敗 '%s': %s", keyword[:30], e)
        return None


import json as _json

_AMAZON_COOKIE_CACHE = pathlib.Path.home() / ".cache" / "s-sca" / "amazon_cookies.json"
_NOTE_SESSION_CACHE = pathlib.Path.home() / ".cache" / "s-sca" / "note_session.json"


def _load_amazon_cookie_cache() -> list | None:
    if not _AMAZON_COOKIE_CACHE.exists():
        return None
    try:
        return _json.loads(_AMAZON_COOKIE_CACHE.read_text())
    except Exception:
        return None


def _save_amazon_cookie_cache(cookies: list) -> None:
    _AMAZON_COOKIE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _AMAZON_COOKIE_CACHE.write_text(_json.dumps(cookies))
    logger.info("[amzn.to] セッションクッキーを保存: %s", _AMAZON_COOKIE_CACHE)


def _load_note_session() -> dict | None:
    if not _NOTE_SESSION_CACHE.exists():
        return None
    try:
        return _json.loads(_NOTE_SESSION_CACHE.read_text())
    except Exception:
        return None


def _get_amzn_short_urls_batch(asins: list[str]) -> dict[str, str]:
    """Amazon SiteStripe API で amzn.to 短縮URLを一括取得する。

    キャッシュ済みクッキーを Playwright コンテキストに読み込み、
    ブラウザ内から SiteStripe API を叩く（JavaScript 実行環境が必要）。
    setup_amazon_cookies.py で事前にクッキーを保存しておく必要がある。
    """
    if not asins or not AMAZON_ASSOCIATE_TAG:
        return {}

    cached = _load_amazon_cookie_cache()
    if not cached:
        logger.info("[amzn.to] クッキー未保存。scripts/setup_amazon_cookies.py を実行してください。")
        return {}

    from playwright.sync_api import sync_playwright

    result: dict[str, str] = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ))
            # キャッシュクッキーをブラウザコンテキストに注入
            ctx.add_cookies(cached)

            page = ctx.new_page()
            # 最初のASIN商品ページでSiteStripeセッションを確立
            page.goto(f"https://www.amazon.co.jp/dp/{asins[0]}", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)

            # 各ASINの商品ページを開き SiteStripe「テキスト」ボタンから amzn.to を取得
            for asin in asins:
                try:
                    page.goto(
                        f"https://www.amazon.co.jp/dp/{asin}",
                        wait_until="domcontentloaded",
                        timeout=20000,
                    )
                    page.wait_for_timeout(2000)

                    # SiteStripe「テキスト」ボタンをクリック
                    text_btn = page.locator(
                        '#sitb-strip-text-link, '
                        'a[id*="sitestripe-text"], '
                        'button[id*="sitestripe-text"], '
                        '.SiteStripeTextLink, '
                        'a:has-text("テキスト"), '
                        'a:has-text("Text")'
                    )
                    if text_btn.count() == 0:
                        logger.warning("[amzn.to] %s: SiteStripe テキストボタン未発見", asin)
                        continue

                    text_btn.first.click()
                    page.wait_for_timeout(1500)

                    # 表示されたポップアップの短縮URLを取得
                    short_input = page.locator(
                        'input[value*="amzn.to"], '
                        'input[id*="short-url"], '
                        '#sitb-strip-short-url, '
                        '.sitb-strip-url-field'
                    )
                    if short_input.count() > 0:
                        short_url = short_input.first.input_value()
                        if short_url and "amzn.to" in short_url:
                            result[asin] = short_url
                            logger.info("[amzn.to] %s → %s", asin, short_url)
                        else:
                            logger.warning("[amzn.to] %s: 短縮URL未取得（値=%s）", asin, short_url[:40])
                    else:
                        logger.warning("[amzn.to] %s: 短縮URLフィールド未発見", asin)

                    time.sleep(0.5)
                except Exception as e:
                    logger.warning("[amzn.to] %s 取得失敗: %s", asin, e)

            browser.close()

    except Exception as e:
        logger.warning("[amzn.to] Playwright セッション失敗: %s", e)

    return result


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
    """assets/note_thumbnail.png を 1280×670px にリサイズして返す。

    note.com の推奨サイズに合わせてリサイズすることでアップロードを高速化する。
    """
    if not _DEFAULT_THUMBNAIL.exists():
        return None
    try:
        from PIL import Image
        import io as _io
        logger.info("デフォルトサムネイルを使用: %s", _DEFAULT_THUMBNAIL.name)
        img = Image.open(_DEFAULT_THUMBNAIL).convert("RGB")
        img.thumbnail((1280, 670), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        resized = buf.getvalue()
        logger.info("サムネイルリサイズ: %dKB → %dKB", len(_DEFAULT_THUMBNAIL.read_bytes()) // 1024, len(resized) // 1024)
        return resized
    except Exception as e:
        logger.warning("サムネイルリサイズ失敗、元画像を使用: %s", e)
        return _DEFAULT_THUMBNAIL.read_bytes()


def _amazon_url(url_or_keyword: str, asin: str | None = None) -> str:
    """Amazon アフィリエイトURLを返す。

    優先順位:
    1. asin が指定されていれば dp/ASIN 形式の直リンク
    2. url_or_keyword が "https://" で始まれば URL そのまま（タグ付与）
    3. それ以外はキーワード検索URL（フォールバック）
    """
    tag = AMAZON_ASSOCIATE_TAG
    if asin:
        base = f"https://www.amazon.co.jp/dp/{asin}"
        return f"{base}?tag={tag}" if tag else base
    if url_or_keyword.startswith("http"):
        url = url_or_keyword.rstrip()
        if tag and "tag=" not in url:
            sep = "&" if "?" in url else "?"
            url += f"{sep}tag={tag}"
        return url
    params: dict[str, str] = {"k": url_or_keyword}
    if tag:
        params["tag"] = tag
    return "https://www.amazon.co.jp/s?" + urllib.parse.urlencode(params)


def _suggest_products_with_claude(symbol: str, info: dict) -> dict[str, str]:
    """Claude Haiku にカテゴリごとの具体的な人気商品名を提案させる。

    Returns:
        {カテゴリ名: 具体的な商品名} の辞書。失敗時は空辞書。
    """
    categories = "\n".join(f"- {name}" for name, _ in info["products"])
    prompt = (
        f"日本のAmazonでよく売れている具体的な商品名（ブランド名・型番を含む）を提案してください。\n"
        f"銘柄: {info['label']}（値上がり予測中）\n\n"
        f"カテゴリ一覧:\n{categories}\n\n"
        f"出力形式（他のテキスト不要。1行1カテゴリ）:\n"
        f"カテゴリ名|具体的な商品名\n\n"
        f"例:\n"
        f"充電式電動工具|マキタ DF484DRGX 充電式ドライバドリル\n"
        f"高耐久USBケーブル|Anker PowerLine III USB-C ケーブル\n"
    )
    try:
        message = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        result: dict[str, str] = {}
        for line in message.content[0].text.strip().split("\n"):
            if "|" in line:
                category, product = line.split("|", 1)
                result[category.strip()] = product.strip()
        logger.info("[%s] Claude商品提案: %s", symbol, result)
        return result
    except Exception as e:
        logger.warning("[%s] Claude商品提案失敗: %s", symbol, e)
        return {}


def _generate_article(
    symbol: str,
    change_pct: float,
    current_price: float,
    predicted_price: float,
    target_date: date,
) -> tuple[str, str, str, list[str]]:
    """Claude Haiku で note 記事本文・タイトル・X短文を生成する。

    Returns:
        (title, note_body, x_text, product_urls)
        product_urls: OGP カードとして埋め込む Amazon URL リスト
    """
    info = COMMODITY_MAP[symbol]
    symbol_links = _AMAZON_LINKS.get(symbol, {})

    # 商品リンク解決順: ① YAML手動URL → ② Claude提案の具体的商品名 → ③ 汎用キーワード
    ai_suggestions = _suggest_products_with_claude(symbol, info)

    # Pass 1: 商品名・ASIN・フォールバックURLを解決
    products_resolved: list[tuple[str, str | None, str]] = []
    for name, kw in info["products"]:
        if symbol_links.get(name):
            url = _amazon_url(symbol_links[name])
            products_resolved.append((name, None, url))
        elif ai_suggestions.get(name):
            specific_name = ai_suggestions[name]
            asin = _get_asin(specific_name)
            url = _amazon_url(specific_name, asin=asin)
            products_resolved.append((specific_name, asin, url))
            time.sleep(1)
        else:
            asin = _get_asin(kw)
            url = _amazon_url(kw, asin=asin)
            products_resolved.append((name, asin, url))
            time.sleep(1)

    # Pass 2: amzn.to 短縮URLを一括取得（Amazon SiteStripe API）
    all_asins = [a for _, a, _ in products_resolved if a]
    short_url_map = _get_amzn_short_urls_batch(all_asins)

    # Pass 3: OGP カード用 URL リストと Claude 向け商品名リストを作成
    product_urls: list[str] = []
    product_name_lines: list[str] = []
    for display_name, asin, fallback_url in products_resolved:
        final_url = short_url_map.get(asin, fallback_url) if asin else fallback_url
        product_urls.append(final_url)
        product_name_lines.append(f"・{display_name}")

    products_text = "\n".join(product_name_lines)

    # Claude には商品名のみ渡す（URLは別途 OGP カードで挿入）
    prompt = (
        f"あなたはコモディティ価格の値上がりを先読みするアフィリエイトライターです。\n\n"
        f"【予測データ】\n"
        f"銘柄: {info['label']}（{symbol}）\n"
        f"現在価格: ${current_price:.2f}\n"
        f"14日後（{target_date}）の予測価格: ${predicted_price:.2f}（{change_pct:+.1f}%）\n"
        f"消費者向け製品への波及タイミング: {info['lag_weeks']}後\n\n"
        f"【値上がり前に買うべき商品カテゴリ】\n"
        f"{products_text}\n\n"
        f"以下の形式で出力してください。他のテキスト不要。\n\n"
        f"[タイトル]\n"
        f"【値上がり警報】〜〜（50字以内）\n\n"
        f"[note本文]\n"
        f"note.comに投稿する記事（300〜500字）。\n"
        f"「なぜ今買うべきか」を冒頭で説明し、上記の商品カテゴリを本文中に自然に言及する。\n"
        f"URLは一切書かないこと（別途商品リンクカードを添付する）。\n"
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

    return title, note_body, x_text, product_urls


def _type_note_body(page: "Page", body: str) -> None:  # type: ignore[name-defined]
    """note ProseMirrorエディタに本文テキストを入力する（URLなし）。"""
    page.keyboard.type(body, delay=4)


def _insert_ogp_cards(page: "Page", product_urls: list[str]) -> None:  # type: ignore[name-defined]
    """商品URLを単独行に貼り付けて note.com の OGP カード（バナー形式）を挿入する。

    note.com はURLのみの行を自動的に商品画像・タイトル付きのカードとして表示する。
    """
    if not product_urls:
        return

    # 「おすすめ商品」見出しを追加
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("▼ 値上がり前に買うべきおすすめ商品", delay=4)
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")

    for url in product_urls:
        # URLを単独行に入力 → note.com が OGP カードに変換
        page.keyboard.type(url, delay=4)
        page.keyboard.press("Enter")
        # OGP カードの読み込みを待つ
        page.wait_for_timeout(2500)
        page.keyboard.press("Enter")


def _post_note_playwright(
    title: str,
    body: str,
    hashtags: list[str],
    thumbnail_bytes: bytes | None = None,
    product_urls: list[str] | None = None,
) -> str | None:
    """Playwright ブラウザ自動化で note.com に記事を投稿し、公開URLを返す。

    scripts/setup_note_session.py で保存したセッション状態を復元して投稿する。
    reCAPTCHA の回避のため、手動ログインで取得したセッションを再利用する。
    """
    import os as _os
    import tempfile

    session_state = _load_note_session()
    if not session_state:
        logger.info("note セッション未保存。scripts/setup_note_session.py を実行してください。")
        return None

    tmp_path: str | None = None
    if thumbnail_bytes:
        # JPEG でリサイズ済みのためサフィックスを .jpg に変更
        suffix = ".jpg" if thumbnail_bytes[:3] == b"\xff\xd8\xff" else ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
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
            # 保存済みセッション（Cookie + localStorage）を復元してログイン状態を再現
            ctx = browser.new_context(
                storage_state=session_state,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()

            # セッション確認
            page.goto("https://note.com/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            logger.info("note.com セッション復元（URL: %s）", page.url)

            # ── 新規テキスト投稿ページ ─────────────────────────────────
            page.goto("https://note.com/notes/new", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            # ── アイキャッチ画像アップロード（タイトル・本文より先に行う） ──
            # アップロード完了前に「公開に進む」を押すとバリデーションエラーになるため、
            # 最初にアイキャッチを設定してサーバー側の処理が終わるまで待機する。
            if tmp_path:
                try:
                    eyecatch_btn = None
                    for sel in [
                        'button.sc-131cded0-2.crfVxf',
                        'button.sc-131cded0-2',
                        'button[aria-label="画像を追加"]',
                    ]:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            eyecatch_btn = loc.first
                            logger.info("アイキャッチボタン発見: %s", sel)
                            break

                    if eyecatch_btn:
                        eyecatch_btn.click()
                        page.wait_for_timeout(1500)
                        with page.expect_file_chooser(timeout=8000) as fc_info:
                            page.locator('button:has-text("画像をアップロード")').first.click()
                        fc_info.value.set_files(tmp_path)
                        page.wait_for_timeout(3000)
                        save_btn = page.locator('.ReactModalPortal button:has-text("保存")')
                        if save_btn.count() > 0:
                            save_btn.first.click(timeout=8000)
                            # CropModal が閉じる → サーバー転送完了のシグナル
                            page.wait_for_selector(
                                '.CropModal__overlay',
                                state='hidden',
                                timeout=30000,
                            )
                        # eyecatch エリアのローディング（• • •）が消えるまで追加待機
                        page.wait_for_timeout(5000)
                        logger.info("アイキャッチ画像をアップロードしました")
                    else:
                        logger.warning("アイキャッチボタンが見つかりません。スキップ。")
                except Exception as _e:
                    logger.warning("アイキャッチアップロード失敗（スキップ）: %s", _e)

            # ── タイトル入力 ───────────────────────────────────────────
            page.wait_for_selector("textarea[placeholder='記事タイトル']", timeout=15000)
            page.fill("textarea[placeholder='記事タイトル']", title)
            page.wait_for_timeout(500)

            # ── 本文入力（ProseMirror）──────────────────────────────────
            editor = page.locator(".ProseMirror").last
            editor.click()
            _type_note_body(page, body)
            # 商品 OGP カードを本文末尾に挿入
            if product_urls:
                _insert_ogp_cards(page, product_urls)
            page.wait_for_timeout(1000)

            # ── 「公開に進む」ボタン → 公開モーダルページへ ──────────
            page.click('button:has-text("公開に進む")', timeout=15000)
            page.wait_for_url("**/publish/**", timeout=20000)
            page.wait_for_timeout(2000)

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
            title, note_body, x_text, product_urls = _generate_article(
                symbol, change_pct, current, predicted, target_date
            )

            # note 投稿（Playwright セッション方式）
            thumbnail_bytes = _load_thumbnail()
            if _load_note_session():
                note_url = _post_note_playwright(
                    title, note_body, info["hashtags"], thumbnail_bytes, product_urls
                )
            else:
                logger.warning("[%s] note セッション未保存。scripts/setup_note_session.py を実行してください。", symbol)
                note_url = None

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
