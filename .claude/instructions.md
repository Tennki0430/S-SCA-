# Claude Code への指示 — S-SCA ハーネス設計

## PDCAフロー（毎時 GitHub Actions で自動実行）

```
P（Plan）   → src/agents/oracle.py        Prophet で14日後価格を予測
D（Do）     → src/agents/merchant.py      Discord/X に投稿
C（Check）  → evaluators/accuracy.py      予測精度を定量評価（MAPE）
A（Act）    → evaluators/llm_judge.py     Claude がパラメータ改善案を提案
```

全体の流れは **harness/runner.py** が管理している。

---

## 何かおかしいときにどこを直すか

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

## 新しいエージェントを追加するとき

1. `src/agents/{name}.py` に `run()` を実装する
2. `harness/runner.py` の適切な位置に `from src.agents import {name}` と `{name}.run()` を追加する
3. `.claude/agents/{name}.md` にエージェント定義を作成する
4. 実行後は `evaluators/` で採点できるか確認する

## 新しい評価指標を追加するとき

1. `evaluators/base.py` の `BaseEvaluator` を継承したクラスを作る
2. `harness/reporter.py` で使用する
3. 結果は `data/output/` に保存することを検討する

---

## PDCA データの流れ

```
data/input/          ← 評価用の基準データ（将来的に使用）
      ↓
harness/dataloader.py ← Supabase から市場データ・予測データを読み込む
      ↓
src/agents/oracle.py  ← Prophet が予測を生成（prediction_log に保存）
      ↓
src/agents/merchant.py ← Discord/X に投稿
      ↓
evaluators/accuracy.py ← 14日後に予測 vs 実績を採点
      ↓
evaluators/llm_judge.py ← 不合格なら Claude がパラメータ改善案を提案
      ↓
harness/reporter.py   ← feedback_log に保存
      ↓
data/output/          ← ログ・履歴（将来的に使用）
```
