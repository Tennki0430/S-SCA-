
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

詳細なプロジェクト計画・アーキテクチャ・開発フェーズは `.claude/CLAUDE.md` を参照してください。

## クイックスタート

```bash
# 1. 仮想環境を作成・有効化
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. 依存関係インストール
pip install -r requirements.txt

# 3. 環境変数をセットアップ
cp .env.example .env
# .env を開いて各キーを入力する

# 4. DB テーブルを初期化（初回のみ）
python init_db.py
# → 表示された SQL を Supabase の SQL Editor に貼り付けて Run

# 5. 動作確認
python main.py
```

## エージェント個別実行

```bash
python -m src.agents.scout_price        # 価格収集（Wheat/Corn/Naphtha/Copper/Lithium）
python -m src.agents.scout_logistics    # 物流指標収集（BDRY ETF）
python -m src.agents.scout_geopolitical # 地政学リスク収集（VIX/Gold/Oil/DXY）
python -m src.agents.oracle             # Prophet 予測（14日後）
python -m src.agents.merchant           # Claude Haiku で投稿文生成・Discord投稿
```

## テスト

```bash
pytest tests/ -v
pytest tests/test_oracle.py -v   # 単一ファイル
```
