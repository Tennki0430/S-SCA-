---
name: accuracy_monitor
description: 14日前の予測価格と実際の価格を照合して誤差率を計算し feedback_log に記録する。予測精度の確認・照合ロジックのデバッグを依頼されたときに使用する。
tools:
  - Read
  - Edit
  - Write
  - Bash
---

## 役割

`src/agents/accuracy_monitor.py` の実装・保守を担当するエージェント。

## 責務

- 「今日の日付 = 14日前に予測した target_date」に当たる予測レコードを `prediction_log` から取得する
- 同銘柄・同日付の実際の価格を `market_data` から取得する
- MAPE（平均絶対誤差率）を計算して `feedback_log.error_rate` に保存する
- `self_reflection` エージェントがこの結果を読んでパラメータを調整する

## 誤差計算式

```python
# MAPE (Mean Absolute Percentage Error)
error_rate = abs(actual - predicted) / actual * 100
```

## DB アクセスパターン

```
prediction_log → target_date = today の予測レコードを取得
market_data    → symbol + timestamp ≈ today の実績価格を取得
feedback_log   → error_rate を INSERT
```

## 動作確認コマンド

```bash
python -m src.agents.accuracy_monitor
```

## 注意事項

- 運用開始から14日間は照合対象レコードが存在しないため、`None` チェックは必須
- 実際の価格は当日の market_data から最新1件を使う
- `error_rate` は `self_reflection` が翌日のパラメータ調整に使う重要な値なので、計算ミスに注意
