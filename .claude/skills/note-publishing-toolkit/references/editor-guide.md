# noteエディタ操作ガイド（Chrome DevTools MCP）

## 前提

- noteのエディタはProseMirror/TipTapベース
- フローティングツールバーはテキスト選択時のみ表示される
- ツールバーのボタンは選択状態が確定してから即座に click すれば uid 指定でも動く（古い記述では「タイムアウトしやすい」とあったが、Selection API で範囲を確定 → take_snapshot → click の順なら安定）

## ★ 入稿の鉄則: 2 パス方式（execCommand 流し込み → ツールバー整形）

### 大前提 — type_text と Enter の罠 (2026-05-06 検証)

| 操作 | 期待 | 実際 |
|---|---|---|
| `type_text(text, submitKey=Enter)` | 段落 + Enter で次段落 | **全行が `<br>` 連結された 1 つの `<p>`** になる |
| `press_key("Enter")` 単独 | 段落分割 | やはり soft break (`<br>`) |
| `dispatchEvent(KeyboardEvent('keydown', {key:'Enter'}))` | 段落分割 | `isTrusted: false` で ProseMirror が無視 |
| `markdown autocomplete (> ## -)` | 連続変換 | 引用ブロック内が全部飲み込まれる / `## ` がリテラル文字列のまま等、信頼性ゼロ |

→ **type_text + Enter は使わない。**

### 唯一安定する Pass 1: `document.execCommand`

ProseMirror は `document.execCommand('insertParagraph')` には反応する (検証済み):

```javascript
async (blocks) => {
  // blocks = [{ kind: 'p'|'quote'|'h2'|'h3'|'list-item', text: '...' }, ...]
  const editor = document.querySelector('.ProseMirror');
  editor.focus();
  document.execCommand('selectAll');
  document.execCommand('delete');
  for (let i = 0; i < blocks.length; i++) {
    document.execCommand('insertText', false, blocks[i].text);
    if (i < blocks.length - 1) document.execCommand('insertParagraph');
  }
  return { count: editor.children.length };
}
```

→ N 個の `<p>` が確実に生成される。markdown プレフィックスは付けない (kind は Pass 2 で使う)。

### Pass 2: ツールバー操作でブロック整形

#### 2-A: フローティングツールバーを呼び出す

Selection API だけでは出ない。**マウスイベントを dispatch する必要がある**:

```javascript
const target = Array.from(editor.querySelectorAll(':scope > p, :scope > h2'))
  .find(el => el.textContent.includes(markerText));
target.scrollIntoView({ block: 'center' });
const range = document.createRange();
range.selectNodeContents(target);
window.getSelection().removeAllRanges();
window.getSelection().addRange(range);
const rect = target.getBoundingClientRect();
const opts = {
  bubbles: true, cancelable: true, view: window, button: 0,
  clientX: rect.x + 30, clientY: rect.y + rect.height/2
};
target.dispatchEvent(new MouseEvent('mousedown', opts));
target.dispatchEvent(new MouseEvent('mouseup', opts));
await new Promise(r => setTimeout(r, 700));  // ツールバー描画待ち
```

#### 2-B: ボタン click — 「2 つのツールバーが存在する」罠

note エディタには似たラベルのボタンが **2 種類** 存在する:

| 種類 | 場所 | 役割 |
|---|---|---|
| **floating toolbar** | 選択時に画面下部に出現 (id 無し) | 選択中ブロックの**変換** (見出し化 / 引用化 / リスト化) |
| **slash/insert menu** | 段落左の「+」やスラッシュ`/`で出現 | カーソル位置に**新規挿入** (空の見出し / 空のリスト) |

両方に「大見出し」「箇条書きリスト」「引用」が存在する。**`document.querySelectorAll('button')` で `textContent === '箇条書きリスト'` を最初に拾うとほぼ insert menu のほうがヒット**し、結果として「現在の段落の隣に空の UL が挿入される」失敗パターンが多発する。

対策: **viewport に表示中** かつ **floating toolbar コンテナ内** のものだけを拾うフィルタを噛ませる:

```javascript
const findFloatingBtn = (label) => Array.from(document.querySelectorAll('button')).find(b => {
  if (b.textContent.trim() !== label) return false;
  const r = b.getBoundingClientRect();
  // visible かつ画面下半分 (floating toolbar は画面下に出る) を許容
  return r.width > 0 && r.height > 0 && r.top >= 0 && r.top < window.innerHeight;
});
```

それでも誤爆するときは、**`take_snapshot` → 該当 uid を確認 → `click(uid)`** に切り替える。MCP click は CDP 経由で trusted event を発火するので、JS click より信頼性が高い (実測で 引用 / 大見出し は JS click で OK、リストは `take_snapshot + click(uid)` 必須)。

#### 2-C: 各 kind の処理レシピ

| kind | 操作 |
|---|---|
| `p` | 何もしない (Pass 1 の `<p>` のまま) |
| `quote` | floating の「引用」を click → `<figure><blockquote>` に変換 |
| `h2` | 「見出し」expandable click → ドロップダウンで「大見出し」 click |
| `h3` | 同上 → 「小見出し」 |
| `list-item` (連続 N 個) | **1 段落ずつ**「リスト」expandable click → 「箇条書きリスト」 click。各段落が独立した `<ul>` になるので Pass 3 で連結 |

#### 2-D: Pass 3 — 後始末 (一括修復)

```javascript
() => {
  const editor = document.querySelector('.ProseMirror');
  // 空 h2 / 空 li を削除
  for (const h of editor.querySelectorAll('h2,h3')) if (!h.textContent.trim()) h.remove();
  for (const li of editor.querySelectorAll('li')) if (!li.textContent.trim()) li.remove();
  // 連続 ul を merge (Pass 2-C の list-item 群を1つの ul にまとめる)
  let merged = 0;
  while (true) {
    const uls = Array.from(editor.querySelectorAll(':scope > ul'));
    let didMerge = false;
    for (const ul of uls) {
      const next = ul.nextElementSibling;
      if (next && next.tagName === 'UL') {
        while (next.firstChild) ul.appendChild(next.firstChild);
        next.remove(); merged++; didMerge = true; break;
      }
    }
    if (!didMerge) break;
  }
  // 連続空段落削除
  let prevEmpty = false;
  for (const p of editor.querySelectorAll(':scope > p')) {
    const e = !p.textContent.trim();
    if (e && prevEmpty) p.remove();
    prevEmpty = e;
  }
  return merged;
}
```

### 既知の未解決課題 (2026-05-06)

- **リスト変換の信頼性**: 1 段落 1 リストへの変換は `take_snapshot + click(uid)` の組合せで成功するが、ループ内で `findBtn` + JS click だと「リスト」expandable が見つからない / 空 UL を挿入する事象が多発。原因不明。安定運用には **list は 1 つずつ手動で `take_snapshot` → uid 直 click** が必要 (= 3〜10 ツールコール / リストブロック)。
- **ドロップダウンの再利用**: 連続して見出し化する場合、前回開いたドロップダウンが残ったまま次のクリックを受けることがある。**`document.body.click()` + 待機 300ms** で毎回リセットすると改善する。


## エディタへのアクセス

```
new_page → https://note.com/notes/new
```

未ログインなら `/login?redirectPath=%2Fnotes%2Fnew` に飛ばされる。ログイン後は自動で `https://editor.note.com/notes/{id}/edit/` に遷移。

**初回起動直後はサイドバーに「AIと相談」ダイアログが開く** ことがある (uid 取れる「閉じる」ボタンで dismiss してから本文入力に進むこと)。

## セッション切れ時のログイン

```
mcp__chrome-devtools__fill_form
  - uid=email_input → NOTE_EMAIL の値
  - uid=password_input → NOTE_PASSWORD の値
mcp__chrome-devtools__click → 「ログイン」ボタン
mcp__chrome-devtools__wait_for → ["記事タイトル","本文を入力","ログインできません"]
```

クレデンシャル運用の注意:
- `.env.local` は MCP プロセスから自然に env 経由で参照させるのが理想だが、現状は `fill_form` の `value` にリテラル文字列で渡すのが標準。tool 呼び出しの引数として 1 度だけ流れる
- **bash の echo / print 等で stdout に出すのは厳禁** (transcript に永続的に残る)。`source .env.local` で env に読み込み → 値を確認する場合は `${#NOTE_PASSWORD}` で長さだけ見る等、内容を露出させない
- ログイン成功後は profile (例: `~/.cache/chrome-devtools-mcp/automan-profile`) に cookie が永続化されるので、**次回以降は `/login` をスキップして直接エディタに入れる**

## ファイルパスの制約 (Chrome DevTools MCP の `upload_file`)

`upload_file` は workspace root か `$TMPDIR` (macOS なら `/var/folders/.../T/`) 配下のファイルしか受け付けない。**`/tmp/` 直下は弾かれる** (シンボリックリンクでも NG)。

```bash
# NG: /tmp/note-thumb.png
# OK: $TMPDIR/note-thumb.png  ← こちらを使う
# OK: $WORKSPACE/.claude/data/note-thumb.png
```

サムネ・図解の生成スクリプトは `$TMPDIR` または workspace 内に書き出すこと。

## タイトル入力

スナップショットで `textbox "記事タイトル"` のuidを取得してクリック → type_text。

## 本文入力

★ **本文の段落分割は `document.execCommand` のみ信頼できる** (詳細は冒頭の「2 パス方式」セクション)。
- ❌ `type_text(text, submitKey=Enter)` で複数行を一括入力 → 全部 `<br>` で連結された 1 段落になる
- ❌ `type_text` の `text` に `\n` を埋めても同様
- ❌ `press_key("Enter")` 単独でも段落分割しない
- ✅ `evaluate_script` 内で `document.execCommand('insertText', false, text)` + `document.execCommand('insertParagraph')` を交互に呼ぶ

URL を単独行で書くとリンクカードに自動展開される (これは type_text でも動く)。

## リッチフォーマット適用

### 共通パターン: テキスト選択 → ツールバー操作

noteエディタではフローティングツールバーのボタンをuid指定でクリックするとタイムアウトすることが多い。
**evaluate_scriptでDOM操作する方法が安定する。**

### 見出し設定（大見出し = h2）

```javascript
// Step 1: テキスト選択
async () => {
  const paragraphs = document.querySelectorAll('p');
  for (const p of paragraphs) {
    if (p.textContent.includes('対象テキスト')) {
      const range = document.createRange();
      range.selectNodeContents(p);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      return 'selected';
    }
  }
  return 'not found';
}

// Step 2: 見出しボタン → 大見出しボタン（連続クリック）
async () => {
  const buttons = document.querySelectorAll('button');
  for (const btn of buttons) {
    if (btn.textContent.trim() === '見出し') {
      btn.click();
      break;
    }
  }
  await new Promise(r => setTimeout(r, 500));
  const buttons2 = document.querySelectorAll('button');
  for (const btn of buttons2) {
    if (btn.textContent.trim() === '大見出し') {  // or '小見出し'
      btn.click();
      return 'done';
    }
  }
  return 'failed';
}
```

### 見出しレベル

| 種類 | HTML | 用途 |
|------|------|------|
| 大見出し | h2 | セクション見出し（①出産・子育て応援給付金 等） |
| 小見出し | h3 | サブセクション（必要な場合のみ） |

### 引用ブロック

```javascript
async () => {
  // テキスト選択後
  const buttons = document.querySelectorAll('button');
  for (const btn of buttons) {
    if (btn.textContent.trim() === '引用' || btn.getAttribute('aria-label') === '引用') {
      btn.click();
      return 'applied';
    }
  }
  return 'not found';
}
```

引用適用後、「出典を入力」フィールドが表示される。

### 箇条書きリスト

```javascript
async () => {
  // テキスト選択後
  const buttons = document.querySelectorAll('button');
  for (const btn of buttons) {
    if (btn.textContent.trim() === 'リスト') {
      btn.click();
      break;
    }
  }
  await new Promise(r => setTimeout(r, 500));
  const buttons2 = document.querySelectorAll('button');
  for (const btn of buttons2) {
    if (btn.textContent.trim() === '箇条書きリスト') {  // or '番号付きリスト'
      btn.click();
      return 'done';
    }
  }
  return 'failed';
}
```

### 太字

```javascript
// テキスト選択後
async () => {
  const buttons = document.querySelectorAll('button');
  for (const btn of buttons) {
    if (btn.textContent.trim() === '太字' || btn.getAttribute('aria-label') === '太字') {
      btn.click();
      return 'applied';
    }
  }
  return 'not found';
}
```

### テキストの置換（「■ 」プレフィックス除去など）

```javascript
() => {
  const headings = document.querySelectorAll('h2');
  for (const h of headings) {
    if (h.textContent.startsWith('■ ')) {
      const walker = document.createTreeWalker(h, NodeFilter.SHOW_TEXT);
      const firstText = walker.nextNode();
      if (firstText) {
        firstText.textContent = firstText.textContent.replace('■ ', '');
      }
    }
  }
  return 'done';
}
```

### テキストリンクの設定（★「補助金エージェント」に必ず使う★）

生URLを貼るのではなく、テキストにリンクを設定する。

```javascript
async () => {
  // 1. テキストの特定部分を選択
  const paras = document.querySelectorAll('p');
  for (const p of paras) {
    if (p.textContent.includes('補助金エージェント編集部')) {
      const textNode = p.firstChild || p.childNodes[0];
      if (textNode && textNode.nodeType === 3) {
        const text = textNode.textContent;
        const start = text.indexOf('補助金エージェント');
        const end = start + '補助金エージェント'.length;
        const range = document.createRange();
        range.setStart(textNode, start);
        range.setEnd(textNode, end);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
      }
      break;
    }
  }
  await new Promise(r => setTimeout(r, 300));

  // 2. ツールバーのリンクボタンをクリック
  for (const btn of document.querySelectorAll('button')) {
    if (btn.textContent.trim() === 'リンク') { btn.click(); break; }
  }
  await new Promise(r => setTimeout(r, 500));

  // 3. URL入力フィールドにURLを入力
  //    → take_snapshotでtextbox "https://" のuidを取得
  //    → click → type_text("https://your-site.example.com")
  //    → 「適用」ボタンをclick
}
```

**注意: DOM直接編集はProseMirrorの内部状態と不整合になる可能性がある。**
見出しの「■ 」除去は動作確認済みだが、本文の大規模なDOM操作は避けること。

## 利用可能なツールバー機能一覧

| ボタン | 機能 | 備考 |
|--------|------|------|
| AIアシスタント | AI補助 | note側のAI機能 |
| 見出し | 大見出し/小見出し/指定なし | ドロップダウン |
| B | 太字 | |
| 取り消し線 | 取り消し線 | |
| リスト | 箇条書き/番号付き | ドロップダウン |
| 文章の配置 | 左揃え/中央/右揃え | ドロップダウン |
| リンク | URLリンク設定 | |
| 引用 | 引用ブロック | 出典入力フィールド付き |
| コード | コードブロック | |
| 削除 | ブロック削除 | |
| 音声を編集 | 音声編集 | |

## 「+」メニューボタン

本文の段落左に表示される「+」ボタンからも要素を挿入できる（画像等）。
ただし自動化では未検証。

## 公開設定画面

```
「公開に進む」ボタンクリック → 公開設定ページに遷移
```

### 設定項目

| 項目 | 操作 |
|------|------|
| ハッシュタグ | 自動提案をクリック or テキスト入力 |
| 記事タイプ | 無料（デフォルト）/ 有料 |
| マガジン追加 | 「追加」ボタン |
| クリエイターページ表示 | トグル（デフォルトON） |
| AI学習対価還元 | トグル（デフォルトON） |
| コメント受付 | トグル（プレミアム機能） |
| 予約投稿 | 日時設定（プレミアム機能） |

### 公開実行

「投稿する」ボタンをクリック。

## トラブルシューティング

### ブラウザプロセスが残っている場合

```bash
pkill -f "chrome-devtools-mcp/chrome-profile"
```

### ツールバーボタンがクリックできない

フローティングツールバーのボタンはuid指定だとタイムアウトしやすい。
`evaluate_script` でJavaScriptから `document.querySelectorAll('button')` → `.click()` を使う。

### リンクカードが展開されない

URLを単独の行（段落）に入力する必要がある。テキストと同じ行に書くとインラインリンクになる。

### デザイン崩れの自動修復（★入稿後に必ず実行★）

リッチフォーマット適用後、ProseMirrorの状態不整合で以下の問題が発生しやすい:

#### 1. 空のh2（見出しの下に謎の空白行）

見出し設定時に元の空行もh2に変換されることがある。

```javascript
() => {
  const headings = document.querySelectorAll('h2');
  let removed = 0;
  for (const h of headings) {
    if (h.textContent.trim() === '' || h.textContent.trim() === ' ') {
      h.remove();
      removed++;
    }
  }
  return 'removed ' + removed + ' empty h2';
}
```

#### 2. 空のリスト項目・空のリスト

箇条書きリスト設定時に空要素が生まれることがある。

```javascript
() => {
  let removed = 0;
  const listItems = document.querySelectorAll('li');
  for (const li of listItems) {
    if (li.textContent.trim() === '') { li.remove(); removed++; }
  }
  const lists = document.querySelectorAll('ul, ol');
  for (const ul of lists) {
    if (ul.children.length === 0 || ul.textContent.trim() === '') { ul.remove(); removed++; }
  }
  return 'removed ' + removed + ' empty list elements';
}
```

#### 3. 引用ブロックが空（テキストがブロックの外に出る）

引用設定時、ブロック内のpが空のまま、テキストが次の兄弟pに入ることがある。

```javascript
() => {
  const figures = document.querySelectorAll('figure');
  for (const fig of figures) {
    const bq = fig.querySelector('blockquote');
    if (bq && bq.textContent.trim() === '') {
      const nextP = fig.nextElementSibling;
      if (nextP && nextP.tagName === 'P') {
        const bqP = bq.querySelector('p');
        if (bqP) {
          bqP.textContent = nextP.textContent;
          nextP.remove();
          return 'fixed blockquote';
        }
      }
    }
  }
  return 'no fix needed';
}
```

#### 4. 一括修復スクリプト（推奨）

入稿・フォーマット適用後に以下を実行して全体を一括修復する:

```javascript
() => {
  const results = [];
  // 空h2削除
  for (const h of document.querySelectorAll('h2')) {
    if (h.textContent.trim() === '' || h.textContent.trim() === ' ') { h.remove(); results.push('empty h2'); }
  }
  // 空リスト削除
  for (const li of document.querySelectorAll('li')) {
    if (li.textContent.trim() === '') { li.remove(); results.push('empty li'); }
  }
  for (const ul of document.querySelectorAll('ul, ol')) {
    if (ul.children.length === 0) { ul.remove(); results.push('empty list'); }
  }
  // 引用ブロック修復
  for (const fig of document.querySelectorAll('figure')) {
    const bq = fig.querySelector('blockquote');
    if (bq && bq.textContent.trim() === '') {
      const nextP = fig.nextElementSibling;
      if (nextP && nextP.tagName === 'P') {
        const bqP = bq.querySelector('p');
        if (bqP) { bqP.textContent = nextP.textContent; nextP.remove(); results.push('blockquote'); }
      }
    }
  }
  // 連続空段落の削除
  let prevEmpty = false;
  for (const p of document.querySelectorAll('p')) {
    const isEmpty = p.textContent.trim() === '';
    if (isEmpty && prevEmpty) { p.remove(); results.push('consecutive empty p'); }
    prevEmpty = isEmpty;
  }
  return 'fixed: ' + results.join(', ');
}
```
