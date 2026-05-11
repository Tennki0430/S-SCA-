#!/bin/bash
# macOS launchd エージェント登録スクリプト
# 実行: bash scripts/setup_launchd.sh
#
# 【ノート PC 対応】
#   1. pmset でスリープ中の Mac を 9:00 JST (0:00 UTC) に自動起動
#   2. launchd でログイン時 + 2時間ごとにドラフトチェック
#
# 注意: pmset の自動起動は電源アダプタ接続時のみ安定動作します。

set -euo pipefail

PLIST_LABEL="com.s-sca.note-post"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PATH="$PROJECT_DIR/scripts/post_note.sh"

chmod +x "$SCRIPT_PATH"

mkdir -p "$HOME/Library/LaunchAgents"

# launchd plist を生成
# RunAtLoad: ログイン時に即実行
# StartInterval: 7200秒 = 2時間ごとに実行（PC が起きている間）
cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SCRIPT_PATH}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>7200</integer>
    <key>StandardOutPath</key>
    <string>/tmp/s-sca-note-post.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/s-sca-note-post-error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
        <key>TERM</key>
        <string>xterm-256color</string>
    </dict>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✅ launchd エージェント登録完了"
echo "   実行タイミング: ログイン時 + 2時間ごと（PC が起きている間）"
echo "   ログ: /tmp/s-sca-note-post.log"
echo ""

# pmset でスリープ中の Mac を 9:00 JST (0:00 UTC) に自動起動
echo "📋 次に pmset でスリープ自動起動を設定します（sudo が必要です）"
echo ""
sudo pmset repeat wakeorpoweron MTWRFSS 0:0:0

echo ""
echo "✅ pmset スリープ自動起動 設定完了"
echo "   起動時刻: 毎日 0:00 UTC (= 9:00 JST)"
echo "   条件: 電源アダプタ接続中"
echo ""
echo "【確認コマンド】"
echo "  pmset -g sched                        # スケジュール確認"
echo "  launchctl list | grep s-sca           # launchd 確認"
echo "  tail -f /tmp/s-sca-note-post.log      # ログ監視"
echo ""
echo "【停止する場合】"
echo "  launchctl unload ${PLIST_PATH}"
echo "  sudo pmset repeat cancel"
