#!/bin/bash
# 自動 note 投稿スクリプト
# macOS launchd から毎朝 9:00 JST (0:00 UTC) に実行される
# セットアップ: bash scripts/setup_launchd.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="/tmp/s-sca-note-post-$(date +%Y%m%d).log"
LOCK_FILE="/tmp/s-sca-note-post.lock"

# .env から DISCORD_WEBHOOK_URL を取得（.env.local があればそちらを優先）
DISCORD_WEBHOOK_URL=""
for env_file in "$PROJECT_DIR/.env" "$PROJECT_DIR/.env.local"; do
    if [ -f "$env_file" ]; then
        val=$(grep '^DISCORD_WEBHOOK_URL=' "$env_file" \
            | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
        [ -n "$val" ] && DISCORD_WEBHOOK_URL="$val"
    fi
done

discord_notify() {
    [ -z "$DISCORD_WEBHOOK_URL" ] && return 0
    local escaped
    escaped=$(printf '%s' "$1" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
    curl -s -X POST "$DISCORD_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"content\": $escaped}" || true
}

# 多重起動防止
if [ -f "$LOCK_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 他のインスタンス実行中。スキップ。" >> "$LOG_FILE"
    exit 0
fi
touch "$LOCK_FILE"

# 終了時クリーンアップ
on_exit() {
    local code=$?
    rm -f "$LOCK_FILE"
    if [ $code -ne 0 ]; then
        discord_notify "⚠️ **note 自動投稿スクリプト失敗**
終了コード: $code
ログ確認: \`tail -50 $LOG_FILE\`"
    fi
}
trap on_exit EXIT

exec >> "$LOG_FILE" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') note 自動投稿チェック開始 ==="

cd "$PROJECT_DIR"

# claude バイナリを探す
CLAUDE_BIN=""
for candidate in \
    /usr/local/bin/claude \
    /opt/homebrew/bin/claude \
    "$HOME/.npm-global/bin/claude" \
    "$HOME/.local/bin/claude" \
    "$HOME/node_modules/.bin/claude"; do
    if [ -x "$candidate" ]; then
        CLAUDE_BIN="$candidate"
        break
    fi
done
if [ -z "$CLAUDE_BIN" ]; then
    CLAUDE_BIN=$(command -v claude 2>/dev/null || echo "")
fi
if [ -z "$CLAUDE_BIN" ]; then
    echo "ERROR: claude バイナリが見つかりません。npm install -g @anthropic-ai/claude-code を実行してください。"
    exit 1
fi
echo "claude: $CLAUDE_BIN"

# 最新ドラフトを取得
echo "git pull 実行中..."
git pull --rebase --autostash origin main

# 未投稿の🤖自動生成ドラフトがあるか確認
if [ ! -f "themes.md" ] || ! grep -q '^- \[ \].*🤖' themes.md; then
    echo "投稿待ちの🤖ドラフトなし。終了。"
    exit 0
fi

echo "🤖 ドラフト検知。note-publisher エージェント起動..."

# --dangerously-skip-permissions: launchd 無人実行に必要（自分の Mac でのみ使用すること）
if ! "$CLAUDE_BIN" --dangerously-skip-permissions \
    "note-publisherエージェントを実行してください。themes.mdの最初の未投稿🤖自動生成ドラフトを1つ選んで、Chrome DevTools MCPを使ってnote.comへの投稿を公開まで完了させてください（自動公開モード）。bot検知・アカウント停止を検出した場合は即座に中断してDiscord通知してください。"; then
    echo "ERROR: claude エージェント異常終了"
    discord_notify "🚨 **note 自動投稿エラー**
claude エージェントが異常終了しました。
bot 検知またはその他の問題が発生した可能性があります。
ログ確認: \`tail -100 $LOG_FILE\`
→ note.com を手動で確認してください"
    exit 1
fi

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 完了 ==="
