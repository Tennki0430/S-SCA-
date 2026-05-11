#!/usr/bin/env python3
"""note 入稿プラン JSON 生成スクリプト

Markdown を読んで、note エディタに流し込みやすい構造化 JSON に変換する。
ブラウザは触らない。実際の入稿は Claude Code が Chrome DevTools MCP で行う。

使い方:
  python3 note-publish.py \
    --article path/to/article.md \
    --thumbnail path/to/thumb.png > /tmp/note-plan.json

入力 Markdown の対応記法:
  # タイトル              (1記事に1つ)
  ## H2 見出し
  ### H3 見出し
  ```コードブロック```
  > 引用
  - 箇条書きリスト
  ---                     (区切り線)
  https://x.com/...       (単独行で X 埋め込み)

出力 JSON 形式:
  {
    "title": "...",
    "thumbnail": "/abs/path/to/thumb.png" | null,
    "blocks": [
      {"kind": "h2", "text": "..."},
      {"kind": "p",  "text": "..."},
      {"kind": "list", "items": [...]},
      ...
    ],
    "block_count": 12
  }
"""
import argparse
import json
import re
import sys
from pathlib import Path


def strip_md(s):
    """Markdown 装飾 (太字 / イタリック / インラインコード / リンク) を除去"""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'\*(.+?)\*', r'\1', s)
    s = re.sub(r'`(.+?)`', r'\1', s)
    s = re.sub(r'\[(.+?)\]\((.+?)\)', r'\1 ( \2 )', s)
    return s


def parse_markdown(md):
    """Markdown を (kind, content) タプルのリストに変換"""
    lines = md.split('\n')
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith('# ') and not any(b[0] == 'title' for b in blocks):
            blocks.append(('title', strip_md(line[2:].strip())))
            i += 1
        elif line.startswith('## '):
            blocks.append(('h2', strip_md(line[3:].strip())))
            i += 1
        elif line.startswith('### '):
            blocks.append(('h3', strip_md(line[4:].strip())))
            i += 1
        elif line.startswith('```'):
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith('```'):
                code.append(lines[i])
                i += 1
            i += 1
            if code:
                blocks.append(('code', '\n'.join(code)))
        elif line.startswith('> '):
            quote_lines = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith('> '):
                quote_lines.append(lines[i][2:])
                i += 1
            blocks.append(('quote', strip_md(' '.join(quote_lines))))
        elif line.startswith('- '):
            items = []
            while i < len(lines) and lines[i].startswith('- '):
                items.append(strip_md(lines[i][2:]))
                i += 1
            blocks.append(('list', items))
        elif re.match(r'^https?://(x\.com|twitter\.com)/', line.strip()):
            blocks.append(('tweet', line.strip()))
            i += 1
        elif re.match(r'^https?://', line.strip()):
            # URL 単独行 → OGP カード挿入が必要（Pass 2 で埋め込み UI を使う。execCommand では変換されない）
            blocks.append(('link', line.strip()))
            i += 1
        elif line.strip().startswith('<!--'):
            i += 1
        elif line.strip() == '---':
            blocks.append(('hr', ''))
            i += 1
        elif line.strip() == '':
            i += 1
        else:
            blocks.append(('p', strip_md(line.strip())))
            i += 1
    return blocks


def build_plan(md_path, thumb_path):
    md = Path(md_path).read_text()
    blocks = parse_markdown(md)

    title = next((b[1] for b in blocks if b[0] == 'title'), None)
    if not title:
        print(json.dumps({'error': 'No title (# ...) found in article'}), file=sys.stderr)
        sys.exit(1)

    body = []
    for kind, content in blocks:
        if kind == 'title':
            continue
        if kind == 'list':
            body.append({'kind': 'list', 'items': content})
        else:
            body.append({'kind': kind, 'text': content})

    thumbnail = None
    if thumb_path and Path(thumb_path).exists():
        thumbnail = str(Path(thumb_path).resolve())

    return {
        'title': title,
        'thumbnail': thumbnail,
        'blocks': body,
        'block_count': len(body),
    }


def main():
    parser = argparse.ArgumentParser(description='Markdown → note 入稿プラン JSON')
    parser.add_argument('--article', required=True, help='記事 Markdown ファイルのパス')
    parser.add_argument('--thumbnail', help='サムネイル画像のパス (省略可)')
    args = parser.parse_args()

    plan = build_plan(args.article, args.thumbnail)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
