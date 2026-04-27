---
name: llm_judge
description: AccuracyEvaluator が FAIL を返したとき Claude Haiku にパラメータ改善案を提案させる。evaluators/llm_judge.py のプロンプト調整・改善提案の厳密さ変更を依頼されたときに使用する。
tools:
  - Read
  - Edit
  - Write
  - Bash
---

## 役割

`evaluators/llm_judge.py` の実装・保守を担当するエージェント。

## 責務

- `EvaluationResult`（MAPE・予測値・実績値）と現在の Prophet パラメータを受け取る
- `agents/prompts/reflection.py` の `build_reflection_prompt()` でプロンプトを構築する
- Claude Haiku に送り、改善パラメータを JSON で受け取る
- 受け取った JSON を `dict` として返す（`harness/reporter.py` が `feedback_log` に保存）

## 分析フロー

```
EvaluationResult + current_params
  → build_reflection_prompt()
  → claude_call() (agents/skills/claude_call.py)
  → JSON パース
  → dict（例: {"changepoint_prior_scale": 0.1}）
```

## プロンプトの調整

Claude の分析が甘い・厳しいと感じたときは `agents/prompts/reflection.py` を変更する。

## 動作確認コマンド

```bash
python -m evaluators.llm_judge
```

## 注意事項

- `max_tokens=256` を超えない（JSON 応答のみなので十分）
- 空 dict が返ってきた場合はパラメータ更新しない（変更不要と判断されたとみなす）
- Claude API の呼び出しコストは `agents/rules/cost_policy.md` に準拠する
