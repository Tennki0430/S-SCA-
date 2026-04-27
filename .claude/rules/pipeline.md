# パイプライン設計規約（S-SCA プロジェクト）

## PDCAアーキテクチャ

このプロジェクトは **harness/runner.py** が全体を管理するハーネス設計になっている。

```
P（Plan）   src/agents/oracle.py        → Prophet で14日後価格を予測
D（Do）     src/agents/merchant.py      → Discord/X に投稿
C（Check）  evaluators/accuracy.py      → 予測精度を定量評価（MAPE）
A（Act）    evaluators/llm_judge.py     → Claude がパラメータ改善案を提案
```

## エージェントの構造

`src/agents/` 内の各エージェントは以下の構造に従う:

```python
def run() -> None:
    logger.info("=== {AgentName} 開始 ===")
    # 処理
    logger.info("=== {AgentName} 完了 ===")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
```

## 実行順序（依存関係）

```
scout_price         （依存なし）
scout_logistics     （依存なし）
scout_geopolitical  （依存なし）
oracle              （scout_price・scout_logistics・scout_geopolitical のデータが必要）
merchant            （oracle の結果が必要）
--- harness/reporter.py が自動で実行 ---
evaluators/accuracy     （14日前の prediction_log が必要）
evaluators/llm_judge    （accuracy の結果が必要）
```

## 新しいエージェントを追加するとき

1. `src/agents/{name}.py` に `run()` を実装する
2. `harness/runner.py` の適切な位置に追加する
3. `.claude/agents/{name}.md` にエージェント定義を作成する

## 新しい評価指標を追加するとき

1. `evaluators/base.py` の `BaseEvaluator` を継承したクラスを作る
2. `harness/reporter.py` で使用する

## 設定変更

銘柄・モデル・閾値の変更は `config/settings.yaml` を編集する。コードを触らなくてよい。

## Supabase 無料枠の維持

- `harness/runner.py` の先頭で `keepalive()` を必ず呼ぶ
- 7日間アクセスがないと DB が停止するため、GitHub Actions の cron を止めない
