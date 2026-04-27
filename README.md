# Sentient Supply-Chain Agent (S-SCA)

世界の物流遅延・地政学リスクを先行指標として、レアメタル・穀物の **14日後の価格を予測** し、仕入れアラートを Discord / X に自律投稿する AI エージェント・システム。

---

## 概要

```
物流データ（BDRY ETF）
地政学リスク（VIX / Gold / Oil / DXY）  →  Prophet 予測  →  Claude が文章化  →  Discord / X に自動投稿
価格データ（Wheat / Corn / Naphtha / Copper / Lithium）         ↑
                                                  予測誤差を自己分析してパラメータを自動改善
```

24時間放置しても GitHub Actions が毎時自動実行し、予測・投稿・自己改善を繰り返す。

---

## エージェント構成（PDCA）

| フェーズ | エージェント | 役割 |
|----------|-------------|------|
| 前処理 | `scout_price` | Yahoo Finance から Wheat / Corn / Naphtha / Copper / Lithium の先物価格を取得 |
| 前処理 | `scout_logistics` | BDRY ETF（yfinance）から物流指標（BDI プロキシ）を取得 |
| 前処理 | `scout_geopolitical` | VIX / Gold / Oil / DXY（yfinance）から地政学リスクを取得 |
| 前処理 | `scout_news` | yfinance から各銘柄の最新ニュースを取得し news_log に保存 |
| P（Plan） | `oracle` | Prophet + 外生変数 5 本で14日後の価格を予測 |
| D（Do） | `merchant` | Claude Haiku で予測理由を文章化 → Discord / X に投稿 |
| C（Check） | `evaluators/accuracy` | 14日前の予測 vs 実績を MAPE で採点 |
| A（Act） | `evaluators/llm_judge` | 誤差原因をニュース文脈付きで Claude Haiku に分析させ、結果を Supabase に保存 |

全体の流れは **`harness/runner.py`**（PipelineRunner）が管理する。

---

## Tech Stack

| Layer | 技術 | 理由 |
|-------|------|------|
| 言語 | Python 3.11+ | Prophet / pandas エコシステム |
| 予測 | Prophet（Meta） | 外生変数 regressor 対応、ローカル計算でコストゼロ |
| データ取得 | yfinance | 価格・物流・地政学リスクをまとめて取得 |
| DB | Supabase（PostgreSQL） | 無料枠、REST API 完備 |
| 自動実行 | GitHub Actions | 毎時 cron、無料枠 |
| AI | Claude Haiku | 投稿文生成・誤差分析の 2 箇所のみ（コスト最小化） |
| 通知 | Discord Webhook / X API | 無料枠範囲内 |

---

## セットアップ

### 1. 環境構築

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cp .env.example .env
# .env を開いて各キーを入力する
```

| 変数名 | 取得先 |
|--------|--------|
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase ダッシュボード → Settings → API |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `DISCORD_WEBHOOK_URL` | Discord サーバー設定 → 連携サービス → ウェブフック |
| `X_API_*` | https://developer.x.com |

### 3. データベース初期化（初回のみ）

```bash
python init_db.py
```

表示された SQL を **Supabase の SQL Editor** に貼り付けて実行する。

### 4. 動作確認

```bash
python main.py
```

---

## エージェント個別実行

```bash
python -m src.agents.scout_price        # 価格収集
python -m src.agents.scout_logistics    # 物流指標収集
python -m src.agents.scout_geopolitical # 地政学リスク収集
python -m src.agents.oracle             # Prophet 予測
python -m src.agents.merchant           # Discord / X 投稿
```

---

## GitHub Actions による自動実行

`.github/workflows/agents.yml` に設定済み。GitHub Secrets に環境変数を登録するだけで毎時自動実行される。

**Secrets の登録場所**: リポジトリ → Settings → Secrets and variables → Actions

---

## 自律改善ループ（C → A）

```
evaluators/accuracy が MAPE を採点
        ↓（10% 超で FAIL）
evaluators/llm_judge が news_log のニュースを取得
        ↓
Claude に「誤差原因の説明文 + 改善パラメータ」を構造化 JSON で生成させる
        ↓
feedback_log に原因分析テキストとパラメータ更新を保存
        ↓
翌日の oracle が新パラメータで予測
```

---

## ディレクトリ構造

```
S-SCA/
├── main.py                      # エントリポイント（PipelineRunner を呼ぶだけ）
├── init_db.py                   # DB 初期化（初回のみ）
├── requirements.txt
├── config/
│   └── settings.yaml            # 銘柄・モデル・閾値（コードを触らず変更可）
├── .github/workflows/
│   └── agents.yml               # hourly cron ワークフロー
├── agents/                      # エージェント共通コンポーネント
│   ├── skills/                  # 能力（Discord 通知・Claude API 呼び出し）
│   ├── rules/                   # 制約ポリシー（コスト・データ品質）
│   ├── hooks/                   # イベントハンドラ（評価失敗・予測完了）
│   └── prompts/                 # Claude へのプロンプト関数
├── src/
│   ├── agents/                  # エージェント本体（scout × 4・oracle・merchant）
│   ├── models/                  # Prophet ラッパー
│   └── utils/                   # DB・設定・リトライ共通処理
├── evaluators/                  # C（Check）: 採点ロジック
│   ├── base.py                  # BaseEvaluator / EvaluationResult
│   ├── accuracy.py              # MAPE 採点
│   └── llm_judge.py             # Claude によるパラメータ改善提案
├── harness/                     # パイプライン管理
│   ├── runner.py                # PDCA オーケストレーター
│   ├── reporter.py              # 評価結果の保存
│   └── dataloader.py            # Supabase データ取得
├── tests/                       # ユニットテスト
└── .claude/                     # Claude Code 用プロジェクト設定
```

---

## テスト

```bash
pytest tests/ -v
pytest tests/test_oracle.py -v   # 単一ファイル
```
