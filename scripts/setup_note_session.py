"""note.com のログインセッションを保存するセットアップスクリプト。

ブラウザを表示してユーザーが手動でログイン（reCAPTCHA含む）し、
セッション状態（Cookie + localStorage）を保存する。
保存後は affiliate_writer が自動的に再利用する。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SESSION_CACHE = Path.home() / ".cache" / "s-sca" / "note_session.json"

print("=" * 55)
print("note.com セッション セットアップ")
print("=" * 55)
print()
print("ブラウザが開きます。以下の手順で進めてください：")
print("  1. メールアドレスとパスワードを入力")
print("  2. reCAPTCHA を解除してログインボタンをクリック")
print("  3. ログイン完了後、自動で保存されます")
print()

from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    )
    page = ctx.new_page()

    page.goto("https://note.com/login", wait_until="domcontentloaded")
    print("⏳ note.com ログイン完了を待っています（reCAPTCHA を解除してください）...")

    page.wait_for_url(
        lambda url: url.startswith("https://note.com/") and "/login" not in url,
        timeout=180000,
    )
    print(f"✅ ログイン完了（URL: {page.url}）")

    # セッション状態を保存（Cookie + localStorage）
    storage = ctx.storage_state()
    browser.close()

SESSION_CACHE.parent.mkdir(parents=True, exist_ok=True)
SESSION_CACHE.write_text(json.dumps(storage))

cookies = storage.get("cookies", [])
note_session = [c for c in cookies if "note_session" in c.get("name", "")]

print()
print(f"✅ セッションを保存しました: {SESSION_CACHE}")
print(f"   Cookie 件数: {len(cookies)} 件")
if note_session:
    print(f"   note_session Cookie: {[c['name'] for c in note_session]}")
else:
    print("   ⚠️  note_session Cookie が見つかりません（ログイン状態を確認してください）")
print()
print("次回からは自動的にこのセッションが使用されます（有効期限: 約30日）。")
