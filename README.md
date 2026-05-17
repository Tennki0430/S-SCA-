# Sentient Supply-Chain Agent（S-SCA）

世界の物流遅延・地政学リスクを先行指標として、レアメタル・穀物の **14日後の価格を予測** し、仕入れアラートを Discord / X に毎日19:00 JST に自律投稿する AI エージェント・システム。

24時間放置しても GitHub Actions が毎時自動実行し、予測・投稿・自己改善を繰り返す。

## ダッシュボード（GitHub Pages）

**公開URL: https://tennki0430.github.io/S-SCA-/**

予測精度の推移・PDCAサイクルによる自律改善・予測 vs 実績の比較をリアルタイムで確認できる。毎時 GitHub Actions により自動更新。

**ダッシュボード搭載機能:**
- 銘柄ごとのバックテスト精度（MAPE）バーグラフ（5銘柄 / 合格4銘柄）
- 予測 vs 実績の時系列チャート（銘柄タブ切り替え対応）
- PDCAサイクルによる自律改善ログの表示

**バックテスト結果（2026-05-12 実施）:**

| 銘柄 | 平均MAPE | 判定 |
|------|---------|------|
| Wheat | 3.33% | PASS |
| Corn | 6.08% | PASS |
| Copper | 8.39% | PASS |
| Lithium | 7.64% | PASS |
| Naphtha | 10.92% | FAIL |

---

## システム全体フロー

```
┌─────────────────────────────────────────────────────────────────┐
│                  GitHub Actions (毎時 UTC cron)                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ python main.py
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                        harness/runner.py                         │
│              （PipelineRunner：全フェーズを順番に管理）           │
└──┬──────────────────┬─────────────┬────────────────────────────┘
   │ データ収集        │ P（Plan）   │ D（Do） / C（Check） / A（Act）
   ▼                  ▼             ▼
Scout × 4         Oracle        Merchant → evaluators → LLM Judge
```

---

## エージェント構成

| フェーズ | エージェント | 役割 |
|----------|-------------|------|
| 収集 | `scout_price` | Wheat / Corn / Naphtha / Copper / Lithium の価格（Yahoo Finance） |
| 収集 | `scout_logistics` | BDRY ETF（BDI プロキシ、yfinance） |
| 収集 | `scout_geopolitical` | VIX / Gold / Oil / DXY / NatGas / ChinaETF / Brent（yfinance） |
| 収集 | `scout_news` | 各銘柄の最新ニュースを `news_log` に保存 |
| **P** | `oracle` | Prophet ＋ 外生変数 8本 で 14日後を予測し `prediction_log` に保存 |
| **D** | `merchant` | Claude Haiku で投稿文生成 → 毎日19:00 JST に Discord / X 投稿 |
| **D+** | `affiliate_writer` | 予測が閾値（+5%）超えたとき note.com にアフィリエイト記事を自動入稿 |
| **C** | `evaluators/accuracy` | 14日前の予測 vs 実績を MAPE で採点 |
| **A** | `evaluators/llm_judge` | Claude Haiku が誤差原因を分析し、改善パラメータを `feedback_log` に保存 |

---

## PDCAサイクル — 自己修正の仕組み

S-SCA は「予測 → 投稿 → 採点 → 自己分析 → 次の予測に反映」という PDCA ループを毎時間自動で回す。

### ① P（Plan）— Oracle が予測する

```
market_data テーブル（過去 N 日分）
  ├─ 対象銘柄の価格（Wheat, Corn, Naphtha, Copper, Lithium）
  └─ 外生変数 8本（BDI・VIX・Gold・Oil・DXY・NatGas・ChinaETF・Brent）
                    │
                    ▼ z-score 正規化（スケール差を吸収）
                    ▼
            Prophet モデル（add_regressor）
                    │ 14日後の価格を予測
                    ▼
            サニティチェック（現在価格から ±30% 超はクリップ）
                    │
                    ▼
        prediction_log に保存（予測価格 / 現在価格 / 使用パラメータ）
```

**パラメータは feedback_log から自動ロード：**
```
feedback_log.parameter_updates（前回のLLM分析結果）
    ↓ fetch_latest_params(symbol)
oracle.py が changepoint_prior_scale / window_days 等を上書き適用
```

---

### ② D（Do）— Merchant が投稿する

```
prediction_log から当日の予測を取得
        │
        ▼ 変動幅チェック（ALERT_THRESHOLD_PCT 以上か？）
      YES │                  NO → スキップ
        ▼
現在時刻 == 19:00 JST？ ── NO → スキップ（ログのみ）
        │ YES
        ▼
Claude Haiku（claude-haiku-4-5-20251001）に投稿文生成を依頼
        │
        ├─► Discord Webhook に投稿（リトライ最大3回）
        └─► X API に投稿（API キー未設定なら自動スキップ）
```

---

### ③ C（Check）— AccuracyEvaluator が採点する

```
14日前に保存した prediction_log を検索
        │
        ▼
今日の market_data（実際の価格）と照合
        │
        ▼ MAPE 計算
        │   MAPE = |予測 − 実績| / 実績 × 100
        │
        ├─ MAPE < 10% → PASS
        └─ MAPE ≥ 10% → FAIL

さらに多角的評価（multi_factor.py）で以下も計算：
  ・方向精度      → 価格の上下方向を当てたか（0 or 1）
  ・VIX補正MAPE   → 恐怖指数が高い時は許容誤差を緩和（VIX≥25で×1.5）
  ・外部ショックスコア → 外生変数の最大変動幅（%）
  ・データ完全性   → 外生変数 8本のうち何本揃っていたか

いずれかが基準を下回ると needs_improvement = True → A フェーズへ
```

---

### ④ A（Act）— LLM Judge が自己分析する

```
needs_improvement = True の銘柄だけ処理
        │
        ▼ 分析情報をまとめる
  ┌─────────────────────────────────────┐
  │ 予測誤差・MAPE・方向精度             │
  │ 外生変数の予測時→実績時の変化量      │
  │ 直近ニュース（news_log）            │
  │ 過去の誤差履歴（feedback_log）      │
  │ 現在のモデルパラメータ              │
  └─────────────────────────────────────┘
        │
        ▼ Claude Haiku に分析依頼
        │
        ▼ 判定ロジック（5つの視点）
  ┌──────────────────────────────────────────────────────────┐
  │ 1. 方向を誤った？                                        │
  │    → 誤った方向に引っ張った外生変数を excluded_regressors │
  │ 2. 外部ショックスコア ≥ 15%？                            │
  │    → 一時的な外部要因と判断、パラメータ変更は最小限       │
  │ 3. MAPE が高く方向は正しい？                             │
  │    → changepoint_prior_scale を調整                     │
  │ 4. 誤差が繰り返し発生？                                  │
  │    → seasonality_mode の変更を検討                      │
  │ 5. データ完全性が低い？                                  │
  │    → 外生変数不足が原因の可能性                          │
  └──────────────────────────────────────────────────────────┘
        │
        ▼ JSON形式で改善パラメータを出力
        {
          "reasoning": "誤差の根本原因（3〜5文）",
          "parameter_updates": {
            "changepoint_prior_scale": 0.1,
            "window_days": 60,
            "excluded_regressors": ["Gold"]
          }
        }
        │
        ▼ feedback_log に保存
        │
        ▼ 翌時間の oracle が fetch_latest_params() でロード → P へ戻る
```

---

### PDCAループ全体図

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                       毎時間の GitHub Actions 実行              │
  │                                                                 │
  │  ┌──────────┐   予測保存   ┌──────────┐   投稿      ┌────────┐ │
  │  │  P: Oracle│ ──────────► │ D: Merchant│ ──────────►│Discord│ │
  │  │  (Prophet)│             │(Claude Haiku)│           │  / X  │ │
  │  └──────────┘             └──────────┘             └────────┘ │
  │       ▲                                                         │
  │       │ パラメータ                      14日後に実績が出たら    │
  │       │ 自動適用                               ↓               │
  │  ┌────────────┐  改善提案  ┌──────────┐  採点  ┌────────────┐ │
  │  │ A: LLM Judge│◄──────────│C: Accuracy│◄───────│ 実際の価格 │ │
  │  │(Claude Haiku)│          │ Evaluator │        │(market_data)││
  │  └────────────┘           └──────────┘        └────────────┘ │
  └─────────────────────────────────────────────────────────────────┘
```

---

## 外生変数（外部要因）一覧

| 変数 | ティッカー | 意味・対象銘柄への影響 |
|------|-----------|----------------------|
| BDI | BDRY ETF | バルチック海運指数プロキシ（物流コスト） |
| VIX | ^VIX | 市場の不確実性（上昇→リスク回避） |
| Gold | GC=F | 金先物（有事の金、リスク上昇で高騰） |
| Oil | CL=F | WTI 原油先物（中東情勢、生産コスト） |
| DXY | DX-Y.NYB | ドル指数（高ドル→コモディティ安） |
| NatGas | NG=F | 天然ガス（ナフサの競合原料・銅製錬エネルギー） |
| ChinaETF | FXI | 中国 ETF（銅消費の50%を占める中国需要） |
| Brent | BZ=F | ブレント原油（アジア・欧州向けナフサ価格に直結） |

**14日後評価の理由：** 物流の乱れ（BDI 急変）が実際の価格に反映されるまでに 2〜4週間のラグがあるため、7日では物流シグナルが織り込まれず予測の検証として不十分。

---

## Tech Stack

| Layer | 技術 | 理由 |
|-------|------|------|
| 言語 | Python 3.11+ | Prophet / pandas エコシステム |
| 予測 | Prophet（Meta） | 外生変数 regressor 対応、ローカル計算でコストゼロ |
| データ取得 | yfinance | 価格・物流・地政学リスクをまとめて無料取得 |
| DB | Supabase（PostgreSQL） | 無料枠 500MB、REST API 完備 |
| 自動実行 | GitHub Actions | 毎時 cron、無料枠 2,000分/月 |
| AI | Claude Haiku | 投稿文生成・誤差分析の 2 箇所のみ（コスト最小化） |
| 通知 | Discord Webhook / X API | 毎日19:00 JST のみ投稿 |

---

## セットアップ

### 1. 環境構築

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

プロジェクトルートに `.env` を作成し、以下のキーを入力する。

| 変数名 | 取得先 |
|--------|--------|
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase ダッシュボード → Settings → API |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `DISCORD_WEBHOOK_URL` | Discord サーバー設定 → 連携サービス → ウェブフック |
| `X_API_KEY` / `X_API_SECRET` / `X_ACCESS_TOKEN` / `X_ACCESS_SECRET` | https://developer.x.com |

### 3. データベース初期化（初回のみ）

```bash
python init_db.py
# → 表示された SQL を Supabase の SQL Editor に貼り付けて実行する
```

### 4. 動作確認

```bash
python main.py
```

---

## エージェント個別実行

```bash
python -m src.agents.scout_price        # 価格収集（Wheat/Corn/Naphtha/Copper/Lithium）
python -m src.agents.scout_logistics    # 物流指標収集（BDRY ETF）
python -m src.agents.scout_geopolitical # 地政学リスク収集（VIX/Gold/Oil/DXY/NatGas/ChinaETF/Brent）
python -m src.agents.oracle             # Prophet 予測（14日後・外生変数8本）
python -m src.agents.merchant           # 投稿文生成 → Discord/X（19:00 JST のみ）
```

---

## GitHub Actions による自動実行

`.github/workflows/agents.yml` に設定済み。GitHub Secrets に環境変数を登録するだけで毎時自動実行される。

**Secrets 登録場所：** リポジトリ → Settings → Secrets and variables → Actions

---

## ディレクトリ構造

```
S-SCA/
├── main.py                       # エントリポイント（PipelineRunner を呼ぶだけ）
├── init_db.py                    # DB 初期化（初回のみ）
├── requirements.txt
├── config/
│   └── settings.yaml             # 銘柄・モデル・閾値（コードを触わらずに変更可）
├── .github/workflows/
│   └── agents.yml                # hourly cron ワークフロー
│
├── src/                          # エージェント本体
│   ├── agents/
│   │   ├── scout_price.py        # 価格収集（Wheat/Corn/Naphtha/Copper/Lithium）
│   │   ├── scout_logistics.py    # 物流指標（BDRY ETF）
│   │   ├── scout_geopolitical.py # 地政学リスク（VIX/Gold/Oil/DXY/NatGas/ChinaETF/Brent）
│   │   ├── scout_news.py         # ニュース収集 → news_log
│   │   ├── oracle.py             # Prophet 予測（外生変数8本）
│   │   └── merchant.py           # Claude Haiku + Discord/X 投稿（19:00 JST限定）
│   ├── models/
│   │   └── prophet_wrapper.py    # Prophet 共通ラッパー（z-score正規化・サニティチェック）
│   └── utils/
│       ├── database.py           # Supabase 接続クライアント
│       ├── config.py             # 環境変数ロード
│       └── retry.py              # 指数バックオフ付きリトライデコレーター
│
├── harness/                      # パイプライン管理
│   ├── runner.py                 # PDCAオーケストレーター（PipelineRunner）
│   ├── reporter.py               # 評価結果の保存処理
│   └── dataloader.py             # Supabase データ取得抽象
│
├── evaluators/                   # C（Check）/ A（Act）の採点ロジック
│   ├── base.py                   # BaseEvaluator / EvaluationResult
│   ├── accuracy.py               # MAPE 採点（AccuracyEvaluator）
│   ├── multi_factor.py           # 多角的評価（方向/VIX補正/外部ショック/完全性）
│   ├── backtest.py               # バックテスト（スライディングウィンドウ・14日先予測）
│   └── llm_judge.py              # Claude Haiku によるパラメータ改善提案
│
├── .claude/                      # Claude Code エージェント定義
│   ├── agents/
│   │   └── note-publisher.md     # note 入稿エージェント（model: haiku）
│   └── skills/
│       └── note-publishing-toolkit/  # 入稿スキル（SKILL.md・テンプレ・スクリプト）
│
├── agents/                       # エージェント共通コンポーネント
│   ├── prompts/
│   │   └── reflection.py         # LLM Judge 用 Claude プロンプト構築関数
│   └── rules/
│       ├── cost_policy.md        # Claude API コスト方針（呼び出し箇所を2箇所に限定）
│       └── data_quality.md       # データ品質規約（最低レコード数・欠損値の扱い）
│
├── scripts/                      # 運用スクリプト（本番パイプライン外）
│   ├── run_backtest.py           # バックテスト実行スクリプト（結果を Discord 通知 + JSON 保存）
│   ├── post_note.sh              # note.com への手動入稿スクリプト
│   └── setup_launchd.sh          # macOS launchd による定期実行セットアップ
│
├── themes.md                     # note 投稿テーマキュー（チェックリスト形式）
│
└── data/
    └── note-drafts/              # note 記事ドラフト（Markdown）
```

---

## データベース（Supabase）

```sql
-- 価格・指標データ（毎時追記）
market_data:    id / timestamp / symbol / price / source

-- 予測ログ（Oracle が毎時保存）
prediction_log: id / timestamp / symbol / target_date / predicted_price
                / current_price / reasoning_text / prophet_params

-- 自律改善ログ（LLM Judge が書き込む）
feedback_log:   id / timestamp / symbol / error_rate
                / self_reflection_notes / parameter_updates（JSONB）

-- ニュースログ（scout_news が保存）
news_log:       id / timestamp / symbol / headline / url
```

---

## 調整可能なパラメータ（LLM Judge が自動変更）

| パラメータ | デフォルト | 効果 |
|-----------|-----------|------|
| `changepoint_prior_scale` | 0.05 | 大きいほどトレンド変化に敏感 |
| `seasonality_prior_scale` | 10.0 | 大きいほど季節性を強く反映 |
| `seasonality_mode` | additive | 価格変動が比率的なら multiplicative |
| `window_days` | 90 | 学習に使う日数（30〜180）。短いほど直近重視 |
| `excluded_regressors` | [] | ノイズになっている外生変数を除外するリスト |

---

## note 自動投稿（Phase 4 — 収益化）

予測シグナルが一定以上になったとき、`affiliate_writer` が自動で note.com にアフィリエイト記事を入稿する。

```
oracle の予測変化率 ≥ AFFILIATE_THRESHOLD_PCT（デフォルト +5%）
        │
        ▼
affiliate_writer がドラフト生成（Claude Haiku）
        │
        ▼
note-publisher エージェント（Claude Haiku）が入稿
  ├─ Gemini でサムネイル生成
  ├─ Chrome DevTools MCP で note.com にアップロード
  └─ Amazon アフィリエイトリンクを OGP カード形式で挿入
        │
        ▼
themes.md をチェック済みに更新 → Discord 通知
```

**テーマキュー:** `themes.md` に未投稿テーマが一覧されている。エージェントは上から順に処理し、投稿済みにはチェック `[x]` を入れる。

**投稿済み記事:**
- [銅価格が14日で+10%予測 — 電気工事・電線の「今すぐ仕入れ」ガイド](https://note.com/novel_skink5217/n/n02344d7097b8)（2026-05-11）

---

## コスト方針

Claude API の呼び出しは **2箇所のみ** に限定：
- `merchant.py`：予測理由の投稿文生成（毎日19:00 JST、1銘柄1回）
- `evaluators/llm_judge.py`：誤差分析・パラメータ改善提案（FAILのみ）

予測計算は Prophet がローカルで完結。月間コスト目安：**Haiku で $1 未満**。

---

## バックテスト

90日分の過去データを使ったスライディングウィンドウで14日先予測を検証する。結果は `docs/data/backtest_results.json` に保存され、ダッシュボードに自動反映される。

```bash
python scripts/run_backtest.py
```

| 銘柄 | 平均MAPE | 合否（< 10%） |
|------|---------|-------------|
| Wheat | 3.33% | PASS |
| Corn | 6.08% | PASS |
| Copper | 8.39% | PASS |
| Lithium | 7.64% | PASS |
| Naphtha | 10.92% | FAIL |

---

## トラブルシューティング早見表

| 症状 | 見るべきファイル |
|------|----------------|
| 予測がおかしい | `src/agents/oracle.py`、`src/models/prophet_wrapper.py` |
| 投稿文がおかしい | `src/agents/merchant.py`、`agents/prompts/reflection.py` |
| 採点基準を変えたい | `evaluators/accuracy.py`（PASS_THRESHOLD_PCT） |
| Claude の分析が甘い/厳しい | `evaluators/llm_judge.py`、`agents/prompts/reflection.py` |
| パイプライン全体が止まる | `harness/runner.py` |
| データが読めない | `harness/dataloader.py` |
| 結果が保存されない | `harness/reporter.py` |
| 銘柄・モデルを変えたい | `config/settings.yaml` |
