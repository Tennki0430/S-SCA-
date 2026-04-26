---
name: self_reflection
description: accuracy_monitor が記録した誤差を Claude API（Haiku）に分析させ、翌日の Prophet パラメータを feedback_log に書き込む自律改善エージェント。パラメータ調整・自己学習ループのデバッグを依頼されたときに使用する。
tools:
  - Read
  - Edit
  - Write
  - Bash
---

## 役割

`src/agents/self_reflection.py` の実装・保守を担当するエージェント。

## 責務

- `feedback_log` から直近の `error_rate` を銘柄ごとに取得する
- Claude API（**Haiku モデル**）に誤差情報と `PARAM_SCHEMA` を渡し、改善パラメータを JSON で返させる
- 返却された JSON を `feedback_log.parameter_updates` に保存する
- 翌日の `oracle.py` が `fetch_latest_params()` でこの値を読み込む

## Claude へのプロンプト構造

```
あなたは時系列予測の専門家です。
以下の予測誤差情報とパラメータスキーマを見て、
精度を改善するためのパラメータ更新を JSON で返してください。

誤差情報: {error_rate}%, 銘柄: {symbol}
パラメータスキーマ: {PARAM_SCHEMA}

返答はJSON のみ。例: {"changepoint_prior_scale": 0.1}
```

## 自律改善サイクル

```
accuracy_monitor → feedback_log.error_rate
self_reflection  → Claude API → feedback_log.parameter_updates
oracle           → fetch_latest_params() → Prophet に反映
```

## 動作確認コマンド

```bash
python -m src.agents.self_reflection
```

## 注意事項

- モデルは必ず `claude-haiku-4-5-20251001`（コスト最小化）
- Claude の返答が JSON でないケースに備えて `json.loads()` を try/except で囲む
- `PARAM_SCHEMA` の `min`/`max`/`options` を超えた値は `prophet_wrapper.py` 側で丸めるが、プロンプトでも範囲を明示して無効な値を返させないようにする
- `error_rate` が 5% 未満の場合はパラメータ変更なし（不要な更新を防ぐ）
