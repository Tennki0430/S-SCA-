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

**コスト方針**: Claude API 呼び出しは `merchant`・`self_reflection` の 2 箇所のみ。予測本体は Prophet で完結させトークンコストを最小化する。

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

## requirements.txt（雛形）

```
# 予測エンジン
prophet==1.1.5
pandas==2.2.2
numpy==1.26.4

# データ取得
yfinance==0.2.40
requests==2.32.3
beautifulsoup4==4.12.3

# DB / 環境変数
supabase==2.5.0
python-dotenv==1.0.1

# AI
anthropic==0.28.0

# SNS 投稿
tweepy==4.14.0

# テスト
pytest==8.2.2
pytest-mock==3.14.0
```

> `pip install -r requirements.txt` で全パッケージが揃う。バージョンは固定しており、将来の破壊的変更を防ぐ。

---

## Free Tier Limits（課金防止）

| サービス | 無料上限 | 超えたときの挙動 | 対策 |
|---|---|---|---|
| GitHub Actions | 2,000 分/月 | 課金発生 | 1 ジョブあたり 5 分以内に収める |
| Supabase DB | 500 MB ストレージ | 超過で書き込み停止 | market_data は 90 日以上の古いレコードを定期削除 |
| Supabase（稼働） | 7 日無アクセスで自動停止 | DB に繋がらなくなる | hourly cron で毎回 write して停止防止 |
| Anthropic API | 初回 $5 クレジット後は従量 | 課金発生 | 呼び出しは merchant・self_reflection の 2 箇所に限定 |
| X API（Free） | 投稿 1,500 件/月 | 投稿 API が 403 エラー | 1 日 1 回投稿に絞る（月 30 件程度） |
| Discord Webhook | 実質無制限 | レートリミット（30 req/分） | retry デコレーターで自動リトライ |

---

## Commands

```bash
# 依存関係インストール
pip install -r requirements.txt

# 環境変数セットアップ（ローカル開発用）
cp .env.example .env
# .env に実際の値を記入する

# 個別エージェント手動実行
python -m src.agents.scout_price        # 価格収集
python -m src.agents.scout_logistics    # 物流指標収集
python -m src.agents.oracle             # Prophet 予測
python -m src.agents.merchant           # SNS / Discord 投稿
python -m src.agents.accuracy_monitor   # 予測精度照合
python -m src.agents.self_reflection    # パラメータ自動調整

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
        │     BDI スクレイピング → market_data テーブルへ保存
        │
        ├─► Oracle Agent
        │     Prophet で 14 日後価格を予測
        │     ※ 物流データを add_regressor() で外生変数注入
        │     → prediction_log テーブルへ保存
        │
        ├─► Merchant Agent
        │     Claude API で「予測の理由」を文章化
        │     → Discord Webhook / X API に投稿
        │
        └─► Accuracy Monitor
              14 日前の予測 vs 実績を照合 → feedback_log へ保存
                    │
                    └─► Self-Reflection
                          Claude API で誤差原因を分析
                          → 翌日の Prophet パラメータを DB に書き込み
```

### Directory Structure

```
S-SCA/
├── main.py                       # オーケストレーター（エントリポイント）
├── requirements.txt
├── .env.example
├── .github/
│   └── workflows/
│       └── agents.yml            # hourly cron ワークフロー
├── src/
│   ├── agents/
│   │   ├── scout_price.py        # 価格収集（Yahoo Finance）
│   │   ├── scout_logistics.py    # 物流指標収集（BDI スクレイピング）
│   │   ├── oracle.py             # Prophet 予測エンジン
│   │   ├── merchant.py           # Claude API + SNS 投稿
│   │   ├── accuracy_monitor.py   # 予測精度照合
│   │   └── self_reflection.py    # Prophet パラメータ自動調整
│   ├── models/
│   │   └── prophet_wrapper.py    # Prophet 共通ラッパー
│   └── utils/
│       ├── database.py           # Supabase 接続クライアント
│       ├── config.py             # 環境変数ロード（GitHub Secrets 対応）
│       └── retry.py              # 指数バックオフ付きリトライデコレーター
├── init_db.py                    # テーブル初期化 SQL 実行（初回のみ）
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

### Phase 3 — 自律成長ループ（Day 6–7）

- [ ] `src/agents/accuracy_monitor.py`：14 日前の予測と実績を照合
- [ ] `src/agents/self_reflection.py`：誤差原因を Claude に分析させ Prophet パラメータを更新
- [ ] `src/utils/retry.py`：指数バックオフ付きリトライデコレーター（全外部 API に適用）
- [ ] Supabase pause 防止：毎時実行時に必ず 1 件 write して無料枠の自動停止を回避

---

## Data Sources

### 価格データ（`scout_price.py`）

`yfinance` ライブラリで取得。ティッカーシンボルは以下を使用する。

```python
SYMBOLS = {
    "Wheat":  "ZW=F",   # シカゴ小麦先物
    "Corn":   "ZC=F",   # シカゴコーン先物
    "Copper": "HG=F",   # 銅先物
    "Lithium": "LIT",   # リチウム ETF（先物なし、代替）
    "Nickel": "^NICKEL" # ニッケル（取得できない場合は代替を検討）
}
# 使用例
import yfinance as yf
df = yf.download("ZW=F", period="90d", interval="1d")
```

### 物流データ（`scout_logistics.py`）

| 指標 | 取得方法 | URL / 補足 |
|---|---|---|
| BDI（バルチック海運指数） | Investing.com スクレイピング | `https://www.investing.com/indices/baltic-dry-overview` |
| BDI（代替・安定） | `quandl` / `nasdaq-data-link` ライブラリ | コード: `CHRIS/CBOE_BDI` |
| 港湾混雑 | MarineTraffic API（無料枠: 100 req/月） | 主要港の停泊船数を取得 |

> BDI スクレイピングは `requests` + `beautifulsoup4` で実装。`User-Agent` ヘッダーを必ず付与すること。

---

## Prophet Tuning Parameters（Self-Reflection 対象）

`self_reflection.py` が調整するパラメータと許容範囲。`feedback_log.parameter_updates` に JSONB で保存し、翌日の `oracle.py` が読み込む。

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
- **Self-healing loop**: `accuracy_monitor` → `self_reflection` → パラメータを `feedback_log` に保存 → 翌日の `oracle` がそれを読み込む、という自律改善サイクル。
- **Claude API 呼び出し箇所の限定**: `merchant`（投稿文生成）と `self_reflection`（誤差分析）の 2 箇所のみ。予測計算は Prophet で完結させ、APIコストを最小化する。
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
