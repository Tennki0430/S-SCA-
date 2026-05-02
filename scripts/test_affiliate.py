"""アフィリエイト記事のテスト生成・投稿スクリプト。
時間制限・閾値チェックをバイパスして1銘柄分の記事を生成し、
内容を確認してからnote/Xに投稿する。
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from src.agents.affiliate_writer import (
    COMMODITY_MAP,
    _generate_article,
    _load_thumbnail,
    _post_note,
    _post_note_playwright,
    _post_x,
    _upload_note_image,
)
from src.utils.config import NOTE_EMAIL, NOTE_PASSWORD
from src.utils.database import fetch_prediction

# ── テスト対象銘柄を選ぶ ──────────────────────────────────────
# 変更したい場合はここを書き換える
TEST_SYMBOL = "Copper"

# ── DBから最新の予測を取得（なければダミーデータ）──────────────
target_date = date.today() + timedelta(days=14)
pred = fetch_prediction(TEST_SYMBOL, target_date)

if pred and pred.get("current_price"):
    current   = float(pred["current_price"])
    predicted = float(pred["predicted_price"])
else:
    print(f"⚠️  {TEST_SYMBOL} の予測レコードがないためダミーデータを使用")
    current   = 4.52
    predicted = 4.90

change_pct = (predicted - current) / current * 100
info = COMMODITY_MAP[TEST_SYMBOL]

print("=" * 50)
print(f"銘柄    : {info['label']} ({TEST_SYMBOL})")
print(f"現在価格: ${current:.2f}")
print(f"予測価格: ${predicted:.2f}（{change_pct:+.1f}%）")
print(f"対象日  : {target_date}")
print("=" * 50)

# ── 記事生成 ─────────────────────────────────────────────────
print("\n📝 Claude Haiku で記事を生成中...")
title, note_body, x_text = _generate_article(
    TEST_SYMBOL, change_pct, current, predicted, target_date
)

print("\n【タイトル】")
print(title)
print("\n【note本文（先頭200字）】")
print(note_body[:200] + "...")
print("\n【X投稿文】")
print(x_text)
print()

# ── 投稿確認 ─────────────────────────────────────────────────
answer = input("👆 この内容でnoteとXに投稿しますか？ (y/N): ").strip().lower()

if answer != "y":
    print("キャンセルしました。")
    sys.exit(0)

# ── note 投稿（Playwright 優先 → cookie フォールバック） ────────
print("\n📤 note に投稿中...")
thumbnail_bytes = _load_thumbnail()

if NOTE_EMAIL and NOTE_PASSWORD:
    print("   → Playwright（メール/パスワード）で投稿します")
    note_url = _post_note_playwright(title, note_body, info["hashtags"], thumbnail_bytes)
else:
    print("   → Cookie 方式で投稿します（NOTE_SESSION_COOKIE）")
    eyecatch_key = _upload_note_image(thumbnail_bytes)
    note_url = _post_note(title, note_body, info["hashtags"], eyecatch_key)

if note_url:
    print(f"✅ note 投稿完了: {note_url}")
else:
    print("⚠️  note 投稿失敗（ログを確認してください）")
    note_url = None

# ── X 投稿 ──────────────────────────────────────────────────
print("📤 X に投稿中...")
x_final = f"{x_text}\n{note_url}" if note_url else x_text
_post_x(x_final[:280])
print("✅ X 投稿完了")

print("\n=== テスト完了 ===")
