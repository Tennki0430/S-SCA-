"""Affiliate Writer Agent: 価格上昇予測時にnote下書きを生成してDiscord/X通知する。

Oracle が「銅 +8%」などを予測したとき、Claude Haiku が Amazon アフィリエイトリンク付きの
Markdown 記事を生成し data/note-drafts/ に保存する。
note.com への実際の投稿は note-publisher エージェント（Chrome DevTools MCP）が担う。
"""

import logging
import re
import time
import urllib.parse
import yaml
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
import requests
import tweepy

from src.utils.config import (
    ANTHROPIC_API_KEY,
    JINA_API_KEY,
    SYMBOLS,
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET,
    AMAZON_ASSOCIATE_TAG,
    AFFILIATE_THRESHOLD_PCT,
    DISCORD_WEBHOOK_URL,
)
from src.utils.database import fetch_prediction, insert_affiliate_log

logger = logging.getLogger(__name__)

_AMAZON_LINKS_PATH = Path(__file__).parents[2] / "config" / "amazon_links.yaml"
_DRAFT_DIR = Path(__file__).parents[2] / "data" / "note-drafts"
_THEMES_PATH = Path(__file__).parents[2] / "themes.md"

JST = timezone(timedelta(hours=9))
AFFILIATE_POST_HOUR_JST = 9

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_AMAZON_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

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


def _get_asin(keyword: str) -> str | None:
    """Amazon Japan でキーワード検索し、最初の商品の ASIN を返す。"""
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


def _amazon_url(url_or_keyword: str, asin: str | None = None) -> str:
    """Amazon アフィリエイト URL を返す。

    優先順位:
    1. asin が指定されていれば dp/ASIN 形式の直リンク（タグ付き）
    2. url_or_keyword が http で始まれば URL そのまま（タグ付与）
    3. それ以外はキーワード検索 URL（フォールバック）
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


def _load_amazon_links() -> dict[str, dict[str, str]]:
    """config/amazon_links.yaml から銘柄ごとの Amazon 商品 URL を読み込む。"""
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


_AMAZON_LINKS: dict[str, dict[str, str]] = _load_amazon_links()


def _competitive_analysis(keyword: str) -> str:
    """Jina Search で上位5記事のタイトル・URLを取得して要約する。

    取得結果は _generate_texts の Claude Haiku プロンプトに注入し、
    競合が書いていない独自の切り口を記事に盛り込む。
    """
    if not JINA_API_KEY:
        return ""
    try:
        resp = requests.get(
            f"https://s.jina.ai/{urllib.parse.quote(keyword)}",
            headers={
                "Authorization": f"Bearer {JINA_API_KEY}",
                "X-Return-Format": "text",
            },
            timeout=20,
        )
        resp.raise_for_status()
        text = resp.text[:2000]
        logger.info("[Jina] 競合分析完了: %s (%d chars)", keyword, len(text))
        return text
    except Exception as e:
        logger.warning("[Jina] 競合分析失敗: %s", e)
        return ""


def _suggest_products_with_claude(symbol: str, info: dict) -> dict[str, str]:
    """Claude Haiku に具体的な人気商品名を提案させる。"""
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


def _add_campaign(url: str, campaign_id: str) -> str:
    """Amazon URL にキャンペーン識別パラメータを付与する。

    Amazon Associates 側ではこのパラメータを集計に使わないが、
    affiliate_log との突き合わせや将来のリダイレクタ導入時に役立つ。
    """
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}ref=ssca-{campaign_id}"


def _resolve_products(
    symbol: str, info: dict, campaign_id: str
) -> list[tuple[str, str]]:
    """銘柄ごとの商品名と Amazon アフィリエイト URL のペアを解決する。

    解決順: ① YAML 手動 URL → ② Claude 提案の具体的商品名 → ③ 汎用キーワード検索 URL
    """
    symbol_links = _AMAZON_LINKS.get(symbol, {})
    ai_suggestions = _suggest_products_with_claude(symbol, info)

    resolved: list[tuple[str, str]] = []
    for name, kw in info["products"]:
        if symbol_links.get(name):
            url = _add_campaign(_amazon_url(symbol_links[name]), campaign_id)
            resolved.append((name, url))
        elif ai_suggestions.get(name):
            specific_name = ai_suggestions[name]
            asin = _get_asin(specific_name)
            url = _add_campaign(_amazon_url(specific_name, asin=asin), campaign_id)
            resolved.append((specific_name, url))
            time.sleep(1)
        else:
            asin = _get_asin(kw)
            url = _add_campaign(_amazon_url(kw, asin=asin), campaign_id)
            resolved.append((name, url))
            time.sleep(1)

    return resolved


def _generate_texts(
    symbol: str,
    change_pct: float,
    current_price: float,
    predicted_price: float,
    target_date: date,
    info: dict,
    products: list[tuple[str, str]],
) -> tuple[str, str, str]:
    """Claude Haiku でタイトル・note 本文・X 短文を生成する。"""
    products_text = "\n".join(f"・{name}" for name, _ in products)

    # Jina で競合記事を調査して差別化に活かす
    kw = f"{info['label']} 値上がり 対策"
    competitor_context = _competitive_analysis(kw)
    competitor_section = (
        f"\n【競合記事の傾向（差別化に活かす）】\n{competitor_context}\n"
        if competitor_context else ""
    )

    prompt = (
        f"あなたはコモディティ価格の値上がりを先読みするアフィリエイトライターです。\n\n"
        f"【予測データ（AIによる参考予測値）】\n"
        f"銘柄: {info['label']}（{symbol}）\n"
        f"現在価格: ${current_price:.2f}\n"
        f"14日後（{target_date}）の予測価格: ${predicted_price:.2f}（{change_pct:+.1f}%）\n"
        f"消費者向け製品への波及タイミング: {info['lag_weeks']}後\n"
        f"{competitor_section}\n"
        f"【値上がり前に買うべき商品カテゴリ】\n"
        f"{products_text}\n\n"
        f"以下の形式で出力してください。他のテキスト不要。\n\n"
        f"[タイトル]\n"
        f"【値上がり警報】〜〜（50字以内）\n\n"
        f"[note本文]\n"
        f"note.comに投稿する記事（300〜500字）。\n"
        f"「なぜ今買うべきか」を冒頭で説明し、上記の商品カテゴリを本文中に自然に言及する。\n"
        f"競合記事と被らない独自の視点・具体的な数字を入れる。\n"
        f"URLは一切書かないこと（別途商品リンクカードを添付する）。\n\n"
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


def _build_markdown(
    title: str,
    note_body: str,
    products: list[tuple[str, str]],
) -> str:
    """note 投稿用の Markdown を生成する。

    Amazon の URL は単独行に置くと note が OGP カード（商品画像付き）に自動変換する。
    """
    lines: list[str] = [f"# {title}", ""]

    for para in note_body.split("\n\n"):
        para = para.strip()
        if para:
            lines.extend([para, ""])

    lines.extend(["## おすすめ商品（値上がり前に）", ""])
    for name, url in products:
        lines.extend([name, "", url, ""])

    lines.extend([
        "---",
        "",
        "*本記事はAIによる価格予測（参考値）を元にした情報提供です。投資判断の根拠にはなりません。*",
    ])

    return "\n".join(lines)


def _save_draft(slug: str, markdown: str) -> Path:
    """Markdown を data/note-drafts/ に保存する。"""
    _DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    path = _DRAFT_DIR / f"{slug}.md"
    path.write_text(markdown, encoding="utf-8")
    logger.info("下書き保存: %s", path)
    return path


def _queue_to_themes(
    title: str,
    symbol: str,
    change_pct: float,
    target_date: date,
    draft_path: Path,
) -> None:
    """themes.md に自動生成エントリを追加する。

    note-publisher エージェントが draft: パスを見てそのまま入稿する。
    """
    if not _THEMES_PATH.exists():
        logger.warning("themes.md が見つかりません: %s", _THEMES_PATH)
        return

    rel_path = draft_path.relative_to(_THEMES_PATH.parent)
    timestamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    entry = (
        f"- [ ] **{title}** — 🤖 自動生成 / draft: {rel_path}\n"
        f"  - 予測: {symbol} {change_pct:+.1f}% (14日後: {target_date})\n"
        f"  - 生成: {timestamp} JST\n"
    )

    content = _THEMES_PATH.read_text(encoding="utf-8")
    marker = "## 完了済み"
    if marker in content:
        content = content.replace(marker, entry + "\n" + marker)
    else:
        content = content.rstrip() + "\n\n" + entry + "\n"

    _THEMES_PATH.write_text(content, encoding="utf-8")
    logger.info("themes.md にエントリを追加: %s", title)


def _notify_discord(
    symbol: str, change_pct: float, title: str, draft_path: Path, campaign_id: str
) -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": (
                f"📈 **価格上昇シグナル検知**\n"
                f"銘柄: **{symbol}** / 予測変動: **{change_pct:+.1f}%** (14日後)\n"
                f"記事タイトル: {title}\n"
                f"下書き: `{draft_path.name}`\n"
                f"キャンペーンID: `{campaign_id}` （affiliate_log + Amazon Associates で照合）\n"
                f"→ 今夜 9:00 JST に note-publisher が自動投稿します\n"
                f"  （手動投稿: `claude` で `note-publisher` エージェントを実行）"
            )},
            timeout=15,
        )
        logger.info("Discord 通知送信完了")
    except Exception as e:
        logger.warning("Discord 通知失敗: %s", e)


def _notify_discord_error(symbol: str, error: str, context: str = "") -> None:
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": (
                f"🚨 **Affiliate Writer エラー**\n"
                f"銘柄: **{symbol}**\n"
                f"エラー: {error}\n"
                + (f"補足: {context}\n" if context else "")
                + f"→ GitHub Actions のログを確認してください"
            )},
            timeout=15,
        )
    except Exception as e:
        logger.warning("Discord エラー通知失敗: %s", e)


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
            campaign_id = f"{symbol.lower()}-{date.today().isoformat()}"

            # Amazon アフィリエイトリンクを解決
            products = _resolve_products(symbol, info, campaign_id)

            # 全商品が検索URL（/s?k=）の場合は OGP カードが出ないため警告通知
            search_only = all("/s?" in url for _, url in products)
            if search_only:
                pass
                # _notify_discord_error(
                #     symbol,
                #     "全商品が検索URLにフォールバックしました（OGPカード非対応）",
                #     "config/amazon_links.yaml に /dp/ASIN/ 形式のURLを設定すると改善されます",
                # )

            # Claude Haiku でタイトル・本文・X短文を生成
            title, note_body, x_text = _generate_texts(
                symbol, change_pct, current, predicted, target_date, info, products
            )

            if not title:
                logger.warning("[%s] タイトル生成失敗。スキップ。", symbol)
                # _notify_discord_error(symbol, "Claude Haiku によるタイトル生成に失敗しました", "記事がスキップされました")
                continue

            # Amazon リンク付き Markdown 下書きを保存
            slug = campaign_id
            markdown = _build_markdown(title, note_body, products)
            draft_path = _save_draft(slug, markdown)

            # affiliate_log に記録（クリック計測の土台）
            try:
                insert_affiliate_log(
                    campaign_id=campaign_id,
                    symbol=symbol,
                    change_pct=change_pct,
                    title=title,
                    draft_path=str(draft_path),
                    products=[{"name": n, "url": u} for n, u in products],
                )
                logger.info("[%s] affiliate_log に記録: campaign_id=%s", symbol, campaign_id)
            except Exception as e:
                logger.warning("[%s] affiliate_log 保存失敗（処理は継続）: %s", symbol, e)

            # themes.md に追加（note-publisher エージェントがピックアップ）
            _queue_to_themes(title, symbol, change_pct, target_date, draft_path)

            # Discord 通知（停止中）
            # _notify_discord(symbol, change_pct, title, draft_path, campaign_id)

            # X 短文アラート（記事下書きへの誘導）
            _post_x(x_text)

            logger.info("[%s] 処理完了: draft=%s", symbol, draft_path.name)

        except Exception as e:
            logger.error("[%s] Affiliate Writer 処理失敗: %s", symbol, e)
            # _notify_discord_error(symbol, str(e), "Affiliate Writer の処理中に予期しないエラーが発生しました")

    logger.info("=== Affiliate Writer Agent 完了 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
