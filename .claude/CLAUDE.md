# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Sentient Supply-Chain Agent (S-SCA)**

世界の物流遅延を先行指標として、レアメタル・穀物の「14日後の価格」を予測し、アフィリエイト投稿や仕入れアラートを自律的に実行するAIエージェント・システム。

**成功の定義**
- 24時間放置しても GitHub Actions が正常に回り続けること
- 物流の乱れが発生した際、価格高騰の前にアラートが発信されること
- 予測と結果の差異をエージェントが自ら記録し、日々学習ログが更新されること

---

## Tech Stack

| Layer | Choice | 理由 |
|-------|--------|------|
| Language | Python 3.11+ | Prophet/pandas エコシステム |
| Prediction | Prophet (Meta) | 外生変数 regressor 対応、無料 |
| Database | Supabase (PostgreSQL) | 無料枠、REST API 完備 |
| Automation | GitHub Actions | 無料枠で 24h 定期実行 |
| Notification | Discord Webhook + X API | 無料枠範囲内 |
| AI Reasoning | Claude API (`anthropic` SDK) | 文章生成・誤差分析のみに限定してコスト抑制 |

**コスト方針**: Claude API 呼び出しは `merchant`（投稿文生成）・`evaluators/llm_judge.py`（誤差分析）の 2 箇所のみ。予測本体は Prophet で完結させトークンコストを最小化する。

---

## Local Setup（初回のみ）

```bash
# 1. Python 仮想環境を作成・有効化
python -m venv venv
source venv/bin/activate        # Windows の場合: venv\Scripts\activate

# 2. 依存関係インストール
pip install -r requirements.txt

# 3. 環境変数セットアップ
cp .env.example .env
# .env をエディタで開き、各キーに実際の値を入力する
```

---

## requirements.txt（現行）

```
# 予測エンジン
prophet==1.1.5
pandas==2.2.2
numpy==1.26.4

# データ取得
yfinance>=0.2.54
requests>=2.32.0

# DB / 環境変数
supabase>=2.9.0
python-dotenv==1.0.1
websockets>=13.0

# AI
anthropic>=0.49.0

# SNS 投稿
tweepy==4.14.0

# テスト
pytest==8.2.2
pytest-mock==3.14.0
```

> `pip install -r requirements.txt` で全パッケージが揃う。beautifulsoup4 は BDI スクレイピング廃止により削除済み。

---

## Free Tier Limits（課金防止）

| サービス | 無料上限 | 超えたときの挙動 | 対策 |
|---|---|---|---|
| GitHub Actions | 2,000 分/月 | 課金発生 | 1 ジョブあたり 5 分以内に収める |
| Supabase DB | 500 MB ストレージ | 超過で書き込み停止 | market_data は 90 日以上の古いレコードを定期削除 |
| Supabase（稼働） | 7 日無アクセスで自動停止 | DB に繋がらなくなる | hourly cron で毎回 write して停止防止 |
| Anthropic API | 初回 $5 クレジット後は従量 | 課金発生 | 呼び出しは merchant・llm_judge の 2 箇所に限定 |
| X API（Free） | 投稿 1,500 件/月 | 投稿 API が 403 エラー | 1 日 1 回投稿に絞る（月 30 件程度） |
| Discord Webhook | 実質無制限 | レートリミット（30 req/分） | retry デコレーターで自動リトライ |

---

## トラブルシューティング早見表

| 症状 | 見るべきファイル |
|------|----------------|
| 予測がおかしい | `src/agents/oracle.py`、`src/models/prophet_wrapper.py` |
| 投稿文がおかしい | `src/agents/merchant.py`、`agents/prompts/merchant.py` |
| 採点基準を変えたい | `evaluators/accuracy.py`（PASS_THRESHOLD_PCT） |
| Claude の分析が甘い/厳しい | `evaluators/llm_judge.py`、`agents/prompts/reflection.py` |
| パイプライン全体が止まる | `harness/runner.py` |
| データが読めない | `harness/dataloader.py` |
| 結果が保存されない | `harness/reporter.py` |
| 銘柄・モデルを変えたい | `config/settings.yaml` |

---

## Commands

```bash
# 依存関係インストール
pip install -r requirements.txt

# 環境変数セットアップ（ローカル開発用）
cp .env.example .env
# .env に実際の値を記入する

# 個別エージェント手動実行
python -m src.agents.scout_price        # 価格収集（Wheat/Corn/Naphtha/Copper/Lithium）
python -m src.agents.scout_logistics    # 物流指標収集（BDRY ETF / yfinance）
python -m src.agents.scout_geopolitical # 地政学リスク収集（VIX/Gold/Oil/DXY）
python -m src.agents.oracle             # Prophet 予測（14日後・外生変数5本）
python -m src.agents.merchant           # Claude Haiku で投稿文生成・Discord投稿

# 全パイプライン実行（GitHub Actions と同等）
python main.py

# テスト
pytest tests/ -v
pytest tests/test_oracle.py -v          # 単一ファイル指定

# DB テーブル初期化（初回のみ）
python init_db.py
```

---

## Architecture

### Agent Pipeline（毎時実行）

```
GitHub Actions (cron: 0 * * * *)
        │
        ▼
   main.py  ── オーケストレーター
        │
        ├─► Scout Agent (Price)
        │     Yahoo Finance API → market_data テーブルへ保存
        │
        ├─► Scout Agent (Logistics)
        │     BDRY ETF（yfinance）→ market_data テーブルへ保存
        │
        ├─► Scout Agent (Geopolitical)
        │     VIX・Gold・Oil・DXY（yfinance）→ market_data テーブルへ保存
        │
        ├─► Oracle Agent
        │     Prophet で 14 日後価格を予測
        │     ※ BDI + VIX + Gold + Oil + DXY を add_regressor() で外生変数注入
        │     → prediction_log テーブルへ保存
        │
        ├─► Merchant Agent
        │     Claude API で「予測の理由」を文章化
        │     → Discord Webhook / X API に投稿
        │
        └─► harness/reporter.py（C + A）
              └─ evaluators/accuracy.py：14日前の予測 vs 実績 → MAPE 採点
              └─ evaluators/llm_judge.py：不合格なら Claude Haiku がパラメータ改善案を提案
              → feedback_log テーブルへ保存
```

### Directory Structure

```
S-SCA/
├── main.py                       # harness/runner.py を呼ぶだけのエントリポイント
├── init_db.py                    # テーブル初期化 SQL 実行（初回のみ）
├── requirements.txt
├── .env.example
├── config/
│   └── settings.yaml             # 銘柄・モデル・閾値の設定（コードを触らずに変更可）
├── .github/
│   └── workflows/
│       └── agents.yml            # hourly cron ワークフロー
├── harness/
│   ├── runner.py                 # PDCA オーケストレーター（PipelineRunner）
│   ├── reporter.py               # 評価 → feedback_log 保存
│   └── dataloader.py             # Supabase からのデータ取得抽象
├── evaluators/
│   ├── base.py                   # BaseEvaluator / EvaluationResult
│   ├── accuracy.py               # MAPE 採点（AccuracyEvaluator）
│   └── llm_judge.py              # Claude Haiku によるパラメータ改善提案
├── agents/
│   └── prompts/
│       ├── merchant.py           # Discord 投稿文プロンプト
│       └── reflection.py         # パラメータ改善提案プロンプト
├── src/
│   ├── agents/
│   │   ├── scout_price.py        # 価格収集（Wheat/Corn/Naphtha/Copper/Lithium）
│   │   ├── scout_logistics.py    # 物流指標（BDRY ETF / yfinance）
│   │   ├── scout_geopolitical.py # 地政学リスク（VIX/Gold/Oil/DXY）
│   │   ├── oracle.py             # Prophet 予測（外生変数 BDI+VIX+Gold+Oil+DXY）
│   │   └── merchant.py           # Claude Haiku + Discord / X 投稿
│   ├── models/
│   │   └── prophet_wrapper.py    # Prophet 共通ラッパー（複数 regressor 対応）
│   └── utils/
│       ├── database.py           # Supabase 接続クライアント
│       ├── config.py             # 環境変数ロード（GitHub Secrets 対応）
│       └── retry.py              # 指数バックオフ付きリトライデコレーター
└── tests/
    ├── test_scout_price.py
    ├── test_oracle.py
    └── test_database.py
```

---

## Database Schema（Supabase / PostgreSQL）

```sql
-- 価格・物流データ
CREATE TABLE market_data (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT NOT NULL,          -- 'Wheat' | 'Corn' | 'Copper'
    price           NUMERIC NOT NULL,
    logistics_index NUMERIC,                -- BDI 等
    source          TEXT
);

-- 予測ログ
CREATE TABLE prediction_log (
    id               BIGSERIAL PRIMARY KEY,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol           TEXT NOT NULL,
    target_date      DATE NOT NULL,         -- 予測対象日（14 日後）
    predicted_price  NUMERIC NOT NULL,
    current_price    NUMERIC,
    reasoning_text   TEXT,                  -- Claude 生成テキスト
    prophet_params   JSONB                  -- 使用パラメータのスナップショット
);

-- フィードバック・自律改善ログ
CREATE TABLE feedback_log (
    id                    BIGSERIAL PRIMARY KEY,
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol                TEXT NOT NULL,
    error_rate            NUMERIC,           -- MAPE 等
    self_reflection_notes TEXT,              -- Claude 分析テキスト
    parameter_updates     JSONB              -- 翌日適用するパラメータ差分
);
```

---

## Environment Variables

GitHub Secrets に登録し、Actions ワークフローで `env:` として注入する。ローカルは `.env` で管理（`.gitignore` に含めること）。

```
SUPABASE_URL
SUPABASE_KEY
ANTHROPIC_API_KEY
DISCORD_WEBHOOK_URL
X_API_KEY
X_API_SECRET
X_ACCESS_TOKEN
X_ACCESS_SECRET
```

---

## Development Phases

### Phase 1 — 基盤構築（Day 1–2）

- [ ] ディレクトリ構造（`src/agents`, `src/utils`, `src/models`）を作成
- [ ] `src/utils/database.py`：Supabase 接続クライアント + テーブル定義 SQL
- [ ] `src/utils/config.py`：GitHub Secrets / `.env` から環境変数をロード
- [ ] `src/agents/scout_price.py`：Wheat / Corn / Copper の価格取得
- [ ] `.github/workflows/agents.yml`：1 時間おき cron + `main.py` 実行

### Phase 2 — 知能の実装（Day 3–5）

- [ ] `src/agents/scout_logistics.py`：BDI スクレイピング機能
- [ ] `src/models/prophet_wrapper.py`：Prophet 共通ラッパー（`add_regressor` 対応）
- [ ] `src/agents/oracle.py`：物流データを regressor として注入した 14 日予測
- [ ] `src/agents/merchant.py`：Claude API で予測理由を文章化 → Discord / X 投稿

### Phase 3 — 自律成長ループ（完了）

- [x] `evaluators/accuracy.py`：MAPE で予測精度を採点（AccuracyEvaluator）
- [x] `evaluators/llm_judge.py`：Claude Haiku が誤差原因を分析し Prophet パラメータを提案
- [x] `harness/runner.py`：PDCA オーケストレーター（PipelineRunner）
- [x] `src/utils/retry.py`：指数バックオフ付きリトライデコレーター（全外部 API に適用）
- [x] Supabase pause 防止：scout_price.run() が毎回 market_data に INSERT（pause 防止兼用）

### Phase 4 — 収益化（未着手）

- [ ] `src/agents/affiliate_writer.py`：予測が閾値超えたときに SEO 記事を自動生成・投稿
- [ ] X API Secrets を GitHub Secrets に登録（ANTHROPIC_API_KEY・DISCORD_WEBHOOK_URL は登録済み）

---

## Data Sources

### 価格データ（`scout_price.py`）

`yfinance` ライブラリで取得。ティッカーシンボルは以下を使用する。

```python
SYMBOLS = {
    "Wheat":   "ZW=F",  # シカゴ小麦先物
    "Corn":    "ZC=F",  # シカゴコーン先物
    "Naphtha": "RB=F",  # RBOB ガソリン先物（ナフサ代替）
    "Copper":  "HG=F",  # 銅先物
    "Lithium": "LIT",   # リチウム ETF（先物なし、代替）
}
```

### 物流データ（`scout_logistics.py`）

| 指標 | 取得方法 | 補足 |
|---|---|---|
| BDI プロキシ | BDRY ETF（yfinance） | Breakwave Dry Bulk Shipping ETF。Investing.com は GitHub Actions IP をブロックするため廃止 |

> `yf.download("BDRY", period="2d", interval="1d")` で取得。beautifulsoup4 は不要。

### 地政学リスクデータ（`scout_geopolitical.py`）

| 指標 | ティッカー | 意味 |
|---|---|---|
| VIX | `^VIX` | 恐怖指数（市場の不確実性） |
| Gold | `GC=F` | 金先物（安全資産への逃避需要） |
| Oil | `CL=F` | WTI 原油先物（地政学的緊張） |
| DXY | `DX-Y.NYB` | ドル指数（ドル高→コモディティ安） |

---

## Prophet Tuning Parameters（LLM Judge 対象）

`evaluators/llm_judge.py` が Claude Haiku に提案させるパラメータ。`feedback_log.parameter_updates` に JSONB で保存し、翌日の `oracle.py` が読み込む。

```python
PROPHET_PARAM_SCHEMA = {
    "changepoint_prior_scale": {
        "default": 0.05,
        "range": (0.001, 0.5),
        "effect": "大きいほどトレンド変化に敏感。過去に急変動を見逃したなら上げる"
    },
    "seasonality_prior_scale": {
        "default": 10.0,
        "range": (0.1, 20.0),
        "effect": "大きいほど季節性を強く反映する"
    },
    "holidays_prior_scale": {
        "default": 10.0,
        "range": (0.1, 20.0),
        "effect": "祝日・イベントの影響度"
    },
    "seasonality_mode": {
        "default": "additive",
        "options": ["additive", "multiplicative"],
        "effect": "価格変動が比率的なら multiplicative"
    }
}
```

> `self_reflection` は Claude API にこのスキーマと誤差ログを渡し、次に試すパラメータを JSON で返させる。

---

## Key Design Decisions

- **Prophet + logistics regressor**: BDI 等物流指標を `add_regressor()` で外生変数として注入し、純粋な価格時系列より予測精度を向上させる。
- **Self-healing loop**: `evaluators/accuracy.py`（MAPE 採点）→ `evaluators/llm_judge.py`（Claude が改善提案）→ `feedback_log` に保存 → 翌日の `oracle` がそれを読み込む、という自律改善サイクル。
- **Claude API 呼び出し箇所の限定**: `merchant`（投稿文生成）と `evaluators/llm_judge.py`（誤差分析）の 2 箇所のみ。予測計算は Prophet で完結させ、APIコストを最小化する。
- **Retry decorator**: ネットワーク障害やレートリミットで 1 エージェントが落ちてもパイプライン全体が止まらないよう、全外部 API 呼び出しに適用する。
- **Supabase 無料枠の維持**: 7 日間アクセスなしで DB が停止する仕様のため、hourly cron の中で必ず write 処理を含める。

---

## Future Application（参考：収益化の方向性）

予測シグナルをアフィリエイト収益に転換するアイデア。実装は本体完成後に検討する。

| B2B シグナル | ラグ | B2C 転用コンテンツ例 |
|---|---|---|
| リチウム価格 +15%↑ | 2〜3 ヶ月 | 「値上げ前に買うべきポータブル電源 5 選」 |
| 銅価格 +10%↑ | 1〜2 ヶ月 | 「電動工具・ケーブル類の駆け込み購入ガイド」 |
| 小麦価格 +10%↑ | 1 ヶ月 | 「食品備蓄まとめ買いリスト」 |
| BDI 急上昇 | 2〜4 週 | 「輸入家電・家具の値上げ前チェックリスト」 |

仕組み: Oracle の予測が閾値（±10%）を超えたとき、Claude API でSEO記事を自動生成 → Amazon / 楽天アフィリリンク付きで GitHub Pages や note に投稿する `affiliate_writer` エージェントを追加する。
