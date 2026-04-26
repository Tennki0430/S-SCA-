# パイプライン設計規約（S-SCA プロジェクト）

## エージェントの構造

各エージェントは必ず以下の構造に従う:

```python
def run() -> None:
    logger.info("=== {AgentName} 開始 ===")
    # 処理
    logger.info("=== {AgentName} 完了 ===")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
```

- `run()` 関数を必ず持つ（`main.py` から呼ばれる）
- 単体実行できるよう `if __name__ == "__main__"` ブロックを持つ

## 実行順序（依存関係）

```
scout_price      （依存なし）
scout_logistics  （依存なし）
oracle           （scout_price・scout_logistics のデータが必要）
merchant         （oracle の結果が必要）
accuracy_monitor （14日前の prediction_log が必要）
self_reflection  （accuracy_monitor の結果が必要）
```

順序を変えない。`main.py` のコメントに実行順を記載しておく。

## 新しいエージェントを追加するとき

1. `src/agents/{name}.py` に `run()` を実装する
2. `.claude/agents/{name}.md` にエージェント定義を作成する
3. `main.py` に `from src.agents import {name}` と `{name}.run()` を追加する
4. 実行順序（依存関係）を確認して適切な位置に挿入する

## Supabase 無料枠の維持

- パイプライン実行のたびに必ず 1 件以上の write が発生するようにする
- `scout_price.run()` が毎回 market_data に INSERT するため、これが Supabase pause 防止を兼ねる
- 7日間アクセスがないと DB が停止するため、GitHub Actions の cron を止めない
