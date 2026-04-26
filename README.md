# Sentient Supply-Chain Agent (S-SCA)

世界の物流遅延を先行指標として、レアメタル・穀物の **14日後の価格を予測** し、仕入れアラートをDiscord / X に自律投稿するAIエージェント・システム。

---

## 概要

```
物流データ（BDI）+ 価格データ → Prophet 予測 → Claude が文章化 → Discord / X に自動投稿
                                                        ↑
                                          予測誤差を自己分析してパラメータを自動改善
```

24時間放置しても GitHub Actions が毎時自動実行し、予測・投稿・自己改善を繰り返す。

---

## エージェント構成

| エージェント | 役割 |
|---|---|
| `scout_price` | Yahoo Finance から Wheat / Corn / Copper の先物価格を取得 |
| `scout_logistics` | BDI（バルチック海運指数）をスクレイピング |
| `oracle` | Prophet + BDI regressor で14日後の価格を予測 |
| `merchant` | Claude Haiku で予測理由を文章化 → Discord / X に投稿 |
| `accuracy_monitor` | 14日前の予測 vs 実績を照合して誤差率を記録 |
| `self_reflection` | 誤差を Claude Haiku に分析させ Prophet パラメータを自動更新 |

---

## Tech Stack

- **Python 3.11+**
- **Prophet** — 時系列予測（物流指標を外生変数として注入）
- **Supabase** — PostgreSQL データベース（無料枠）
- **GitHub Actions** — 毎時自動実行（無料枠）
- **Claude API（Haiku）** — 予測文章生成・誤差分析（コスト最小化）
- **Discord Webhook / X API** — アラート通知（無料枠）

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
|---|---|
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

## GitHub Actions による自動実行

`.github/workflows/agents.yml` に設定済み。GitHub Secrets に環境変数を登録するだけで毎時自動実行される。

**Secrets の登録場所**: リポジトリ → Settings → Secrets and variables → Actions

---

## 自律改善ループ

```
accuracy_monitor が誤差率を記録
        ↓
self_reflection が Claude に分析させる
        ↓
改善パラメータを DB に保存
        ↓
翌日の oracle が新パラメータで予測
```

14日ごとに予測精度が自動改善されていく。

---

## ディレクトリ構造

```
S-SCA/
├── main.py                  # パイプライン起動口
├── init_db.py               # DB 初期化（初回のみ）
├── requirements.txt
├── .env.example
├── .github/workflows/       # GitHub Actions 設定
├── src/
│   ├── agents/              # 各エージェント
│   ├── models/              # Prophet ラッパー
│   └── utils/               # DB・設定・リトライ共通処理
├── tests/                   # ユニットテスト
└── .claude/                 # Claude Code 用プロジェクト設定
```

---

## テスト

```bash
pytest tests/ -v
```
