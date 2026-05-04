"""Amazon Associates のセッションクッキーを保存するセットアップスクリプト。

ブラウザを表示してユーザーが手動でログイン（MFA含む）し、
Amazon Associates Central も訪問して amzn.to 短縮URLに必要な
Associates 認証クッキーを一緒に保存する。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

COOKIE_CACHE = Path.home() / ".cache" / "s-sca" / "amazon_cookies.json"

print("=" * 55)
print("Amazon Associates クッキー セットアップ")
print("=" * 55)
print()
print("ブラウザが開きます。以下の手順で進めてください：")
print("  1. Amazon にログイン（MFA も入力）")
print("  2. トップページが表示されたら自動で次へ進みます")
print()

from dotenv import load_dotenv
load_dotenv()

from src.utils.config import AMAZON_ASSOCIATE_TAG
from playwright.sync_api import sync_playwright

TEST_ASIN = "B09RPL4D5C"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ))
    page = ctx.new_page()

    # Step 1: Amazon.co.jp にログイン
    page.goto("https://www.amazon.co.jp/gp/sign-in.html", wait_until="domcontentloaded")
    print("⏳ Amazon ログイン完了を待っています（MFA がある場合は入力してください）...")

    page.wait_for_url(
        lambda url: "amazon.co.jp" in url and "/ap/" not in url and "signin" not in url,
        timeout=120000,
    )
    print(f"✅ Amazon ログイン完了")

    # Step 2: Amazon Associates Central にアクセスして Associates 認証クッキーを取得
    print("⏳ Amazon Associates のクッキーを取得中...")
    page.goto("https://affiliate.amazon.co.jp/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # Step 3: 商品ページでSiteStripeを読み込む
    print("⏳ SiteStripe を読み込み中...")
    page.goto(f"https://www.amazon.co.jp/dp/{TEST_ASIN}", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)

    # SiteStripe バーが表示されているか確認
    sitestripe_visible = page.locator('[id*="siteStripe"], [id*="sitb-strip"], .SiteStripeContainer').count() > 0
    if sitestripe_visible:
        print("✅ SiteStripe を確認")
    else:
        print("⚠️  SiteStripe が表示されていません（Associates アカウントでログインされているか確認してください）")

    # Step 4: SiteStripe API を Playwright 経由でテスト
    print("⏳ amzn.to 短縮URL の取得をテスト中...")
    api_resp = page.request.get(
        "https://www.amazon.co.jp/associates/sitestripe/getShortUrl",
        params={"asin": TEST_ASIN, "tag": AMAZON_ASSOCIATE_TAG, "type": "StripAsin"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    content_type = api_resp.headers.get("content-type", "")
    if "application/json" in content_type:
        data = api_resp.json()
        short_url = data.get("shortUrl", "")
        print(f"✅ amzn.to 取得成功: {short_url}")
    else:
        print(f"⚠️  amzn.to 取得失敗（Content-Type: {content_type}）")
        print("   → Associates アカウントで正しくログインされているか確認してください")

    # 全クッキーを保存
    cookies = ctx.cookies()
    browser.close()

if not cookies:
    print("❌ クッキーが取得できませんでした。")
    sys.exit(1)

COOKIE_CACHE.parent.mkdir(parents=True, exist_ok=True)
COOKIE_CACHE.write_text(json.dumps(cookies))

# Associates クッキーの存在確認
assoc_cookies = [c["name"] for c in cookies if "at-" in c["name"] or "assoc" in c["name"].lower()]
print()
print(f"✅ クッキーを保存しました: {COOKIE_CACHE}")
print(f"   保存件数: {len(cookies)} 件")
if assoc_cookies:
    print(f"   Associates クッキー: {assoc_cookies}")
else:
    print("   ⚠️  Associates クッキーが見つかりません")
print()
print("次回からは自動的にこのクッキーが使用されます。")
