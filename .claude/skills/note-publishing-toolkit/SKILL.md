---
name: note-publishing-toolkit
description: note.com に記事を 1 本仕上げる全工程ツールキット。テーマ決定 → 競合分析 (Jina Reader) → 記事生成 → ファクトチェック → 画像生成 (Gemini 3.1 Flash Image) → 入稿 (Chrome DevTools MCP) → デザイン QA → 公開 → 振り返りの 9 ステップ。「note 記事自動投稿」「note 入稿」「note 下書き」と言われたらこのスキルを使う。
---

# note 記事入稿ツールキット

note.com に高品質な記事を 1 本投稿する 9 ステップ完全ガイド。

## 必要な環境変数 (`.env`)

| キー | 必須 | 用途 |
|---|---|---|
| `NOTE_EMAIL` | ✅ | note ログイン |
| `NOTE_PASSWORD` | ✅ | note ログイン |
| `JINA_API_KEY` | ✅ | 競合分析 + ファクトチェック |
| `GEMINI_API_KEY` | ✅ | 画像生成 |

→ 画像はすべて note 直接アップロードで完結する。外部画像ホスト（R2 / S3 等）は不要。
→ `.env.local` があれば `.env` より優先される。通常は `.env` 1 ファイルで完結。

## 必要な MCP

- `chrome-devtools` (note 入稿、必須)
- `.mcp.json` がプロジェクト直下に設置済み。Claude Code 起動時に自動で読み込まれる

## 9 ステップ全工程

```
[Step 0] 起動チェック (agent.md で定義)
   ↓
[Step 0B] 🤖 自動生成ドラフト確認 (draft: パスがあれば Steps 1〜4 をスキップ)
   ↓
[Step 1] テーマ決定 (themes.md から選択) ← 自動生成ドラフトがある場合はスキップ
   ↓
[Step 2] 競合分析 (★ Jina Reader で上位 5 記事を全文取得) ← 同上スキップ
   ↓
[Step 3] 記事生成 (★ persona.md の人格で執筆) ← 同上スキップ
   ↓
[Step 4] ファクトチェック (★ Jina Reader で公式ソース照合) ← 同上スキップ
   ↓
[Step 5] 画像生成 (Gemini 3.1 Flash Image でサムネ + 図解)
   ↓
[Step 6] note 入稿 (Chrome DevTools MCP で実 Chrome 操作 + ローカル画像直接アップ)
   ↓
[Step 7] デザイン QA (PC + モバイル スクショ → Read tool 目視)
   ↓
[Step 8] 公開 + 通知 + 振り返り
```

★ = 省略禁止のコアステップ

---

## Step 0B: 自動生成ドラフト確認（価格上昇トリガー）

themes.md の選択テーマに `draft:` パスが含まれている場合、**Steps 1〜4 をすべてスキップ**して Step 5 から開始する。

### ドラフトエントリの見分け方

```
- [ ] **タイトル** — 🤖 自動生成 / draft: data/note-drafts/copper-2026-05-22.md
  - 予測: Copper +8.3% (14日後: 2026-06-05)
  - 生成: 2026-05-22 09:00 JST
```

### ドラフト読み込み手順

```bash
# 1. draft: パスを抽出
DRAFT_PATH="data/note-drafts/copper-2026-05-22.md"

# 2. ドラフトを読む
Read($DRAFT_PATH)

# 3. note-publish.py で JSON プランに変換（Step 6-1 で使用）
python3 .claude/skills/note-publishing-toolkit/scripts/note-publish.py \
  --article $DRAFT_PATH \
  > /tmp/note-plan.json
# サムネは Step 5 で生成するため、この時点では --thumbnail を指定しない
```

### 自動生成ドラフトに含まれる Amazon リンク

ドラフトの `## おすすめ商品（値上がり前に）` セクションに Amazon アフィリエイト URL が 1 行 1 URL で記載されている。
note エディタは URL を単独行に入力すると自動で OGP リンクカードに変換するため、**入稿時にそのまま `link` ブロックとして貼り付ける**だけでよい。

Step 6-4 Pass 2 の `link` ブロック処理:
```
kind: 'link' → Pass 1 でテキストとして流し込み済み → Pass 2 では何もしない
               （URL 単独行はそのまま note が OGP カードに変換する）
```

### スキップできるステップ一覧

| ステップ | スキップ理由 |
|---|---|
| Step 1 テーマ決定 | 🤖 affiliate_writer が選択済み |
| Step 2 競合分析 | 本文生成済みのため不要 |
| Step 3 記事生成 | ドラフトに本文あり |
| Step 4 ファクトチェック | 予測値は affiliate_writer が確認済み |
| Step 5 画像生成 | **実施する**（ドラフトにはサムネなし） |

---

## Step 0: 起動チェック (agent.md で定義)

呼び出し側 agent.md が「前回の重複回避」「自己フィードバック確認」を担当する。

---

## Step 1: テーマ決定 (themes.md から選択)

`themes.md` の上から最初の `- [ ]` 未投稿テーマを 1 つ選ぶ。

選択基準:
- **同じテーマを連続で出さない**
- 前回の記事を確認して被らないようにする

→ 選んだテーマを **メイン KW** として記事タイトルに使う。

---

## Step 2: 競合分析 (★ 最重要、省略禁止)

### a. 上位 5 記事の URL 取得 (Jina Search)

```bash
source .env.local
curl -s "https://s.jina.ai/${MAIN_KW}" \
  -H "Authorization: Bearer ${JINA_API_KEY}" \
  -H "X-Return-Format: text"
```

→ 上位 5 記事の URL を記録。

### b. 公式以外の上位記事を 3 本以上、Jina Reader で全文取得

```bash
curl -s "https://r.jina.ai/${ARTICLE_URL}" \
  -H "Authorization: Bearer ${JINA_API_KEY}" \
  -H "X-Return-Format: text"
```

### c. 比較表を作る (この表がないと次に進めない)

| 項目 | 競合 A | 競合 B | 競合 C | うちの記事 (計画) |
|---|---|---|---|---|
| タイトル | | | | |
| 文字数 | | | | |
| 見出し数 | | | | |
| 情報の網羅性 | | | | |
| 数値・事実の正確性 | | | | |
| 具体性 (実例・固有名詞) | | | | |
| 独自視点 | | | | |
| 画像・図解 | | | | |
| 弱点 | | | | |

### d. 勝ち筋を 3 つ以上明文化

→ 勝ち筋を **記事構成に直接反映** する (Step 3 で使う)。

### 絶対のルール (競合分析)

1. **本文に競合への直接言及を入れない**
2. **比較表を作らないと次のステップに進めない**
3. **公式以外を最低 3 本** 全文取得する

---

## Step 3: 記事生成

### 構成パターン (5 種から 1 つ選ぶ、前回と被らせない)

| パターン | 内容 | 向くテーマ |
|---|---|---|
| **羅列型** | 各要素を h2 で並べる | 複数の対応策・商品比較 |
| **時系列型** | 時間順に展開 | 予測の根拠→現状→アクション |
| **Q&A 型** | 読者の質問に答える | FAQ・初心者向け解説 |
| **数値シミュレーション型** | 数字から逆算 | コスト・利益の試算系 |
| **難易度順** | 簡単 → 難しい / すぐできる → 準備が必要 | 段階的アクションガイド |

### 人格・口調 (persona.md を使う)

`references/persona.md` に書かれた「書き手」の人格を必ず使う。

### 禁止表現 (汎用 AI 表現リスト)

```
〜することができます    →  〜できます
〜が可能です            →  〜できます
幅広く                  →  具体的に書く
網羅的に                →  具体的に書く
他のサイトでは          →  そもそも言及しない
どこよりも              →  そもそく言及しない
一助となれば            →  そもそも書かない
ぜひ参考にしてください  →  別の締め方
```

→ 上記表現が 1 つでも入ったら Step 3 やり直し。

### 記事メタデータ

- **文字数**: 800〜1,500 字
- **見出し**: h2 を 3〜6 個、h3 は h2 の中で必要なら使う

→ `data/note-drafts/${SLUG}.md` に保存。(ディレクトリがなければ作成する)

---

## Step 4: ファクトチェック (★ 公開前に必ず実施)

### a. 記事中の事実を抽出してリスト化

- 数値 (予測変化率・価格・期間)
- 市場データ (BDI・VIX・Gold・Oil の実数値)
- 固有名詞 (制度名・商品名・指標名)

### b. 各事実の公式ソース URL を Jina Reader で取得

```bash
curl -s "https://r.jina.ai/${OFFICIAL_URL}" \
  -H "Authorization: Bearer ${JINA_API_KEY}" \
  -H "X-Return-Format: text"
```

### c. 突き合わせ判定

| 項目 | 判定基準 |
|---|---|
| 予測数値 | prediction_log の最新値と一致するか |
| 市場指標 | 直近の市場データと大きくかけ離れていないか |
| 固有名詞 | 正式名称と一致するか |

---

## Step 5: 画像生成 (Gemini 3.1 Flash Image)

→ `references/image-style-guide.md` を参照。

保存先: `data/note-images/${SLUG}-thumb.png`

品質チェック (Read tool で確認):
- [ ] 日本語テキストが崩れていない
- [ ] 予測数字が記事と一致している
- [ ] サイズが 16:9 になっている

---

## Step 6: note 入稿 (Chrome DevTools MCP)

→ 詳細操作は `references/editor-guide.md` を参照。

### 6-1: Markdown → 入稿プラン JSON 変換

```bash
python3 .claude/skills/note-publishing-toolkit/scripts/note-publish.py \
  --article data/note-drafts/${SLUG}.md \
  --thumbnail data/note-images/${SLUG}-thumb.png \
  > /tmp/note-plan.json
```

### 6-2: ページ起動 + ログイン (セッション自動復帰)

```
mcp__chrome-devtools__new_page → https://note.com/notes/new
```

- 飛び先が `/login` ならログイン処理 (セッション切れ時の自動対応):
  ```
  mcp__chrome-devtools__navigate_page → https://note.com/login
  mcp__chrome-devtools__fill_form → email / password (.env.local から)
  mcp__chrome-devtools__click → ログインボタン
  mcp__chrome-devtools__wait_for → URL 変化
  ```
- `/reset_password` 検知時は **即 abort** + Discord 通知「手動再ログイン要」

**ログイン後は Chrome Profile に cookie が保存されるため、次回以降は自動スキップ。**

### 6-3: サムネイルアップロード

```
mcp__chrome-devtools__click → button[aria-label="画像を追加"]
mcp__chrome-devtools__upload_file → data/note-images/${SLUG}-thumb.png
mcp__chrome-devtools__click → 「保存」
```

### 6-4: タイトル + 本文入力 (2 パス方式)

詳細は `references/editor-guide.md` の「2 パス方式」セクションを参照。

Pass 1: `document.execCommand` で全段落を一括流し込み
Pass 2: ツールバー操作でブロック整形 (h2 / 引用 / リスト)
Pass 3: 一括修復スクリプト実行

### 6-5: 下書き保存

```
mcp__chrome-devtools__press_key → Meta+s (Mac)
mcp__chrome-devtools__wait_for → "下書き保存しました" テキスト出現
```

### 6-6: Draft URL 取得

```
mcp__chrome-devtools__evaluate_script → window.location.href
```

---

## Step 7: デザイン QA

```
mcp__chrome-devtools__resize_page (1280, 1200) → take_screenshot → data/note-images/${SLUG}-pc.png
mcp__chrome-devtools__emulate (iPhone 12) → take_screenshot → data/note-images/${SLUG}-mobile.png
```

→ **両方を Read tool で必ず目視確認**。

チェック項目:
- [ ] サムネが正しく表示
- [ ] 見出し (h2/h3) が太字で正しく変換
- [ ] 引用ブロックが灰色背景
- [ ] リストが箇条書きスタイル
- [ ] 不要な空段落・空 li がない
- [ ] モバイルでタイトルが画面幅に収まる

---

## Step 8: 公開 + 通知 + 振り返り

### 8-1: 公開 (手動推奨)

下書き OK ならユーザーが note.com 上で:
1. 「公開に進む」
2. ハッシュタグ追加
3. 「投稿する」

→ 完全自動化は note 側の bot 検知リスクあり、手動推奨。

### 8-2: 通知

Discord Webhook でテキスト通知:
- 記事タイトル + 下書き URL
- 文字数
- ファクトチェック結果
- デザインチェック結果

### 8-3: 振り返り

`data/note-logs/` にログを追記:
- 記事 URL / タイトル / 文字数
- 使用した予測値 (銘柄・変化率)
- デザイン QA 結果
- 自己改善メモ

---

## ハードルール (集約)

1. **1 回の実行で投稿するのは最大 1 記事**
2. **競合分析なしに記事を書き始めてはならない** (Step 2 必須)
3. **記事構成は競合分析から逆算で決める**
4. **生 URL を貼らない** (テキストリンクで)
5. **サムネイル画像は省略禁止**
6. **公開前に必ずファクトチェック**
7. **公開前に必ず下書き保存してスクリーンショット確認** (PC + モバイル両方)
8. **画像は `gemini-3.1-flash-image-preview` のみ** (旧モデル禁止)
9. **800 字未満の記事は公開しない**
10. **本文に競合への直接言及を入れない**
11. **AI 表現禁止リスト** (Step 3 参照) を 1 つでも含んだら書き直し
12. **予測数字は「AIによる参考予測値」と必ず注記する**
