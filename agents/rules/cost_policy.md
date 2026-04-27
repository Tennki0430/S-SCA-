# Claude API コスト方針

## 呼び出し箇所（2箇所に限定）

| 場所 | ファイル | 用途 | max_tokens |
|------|---------|------|-----------|
| Merchant | src/agents/merchant.py | 投稿文生成 | 512 |
| LLM Judge | evaluators/llm_judge.py | パラメータ改善提案 | 256 |

共通呼び出しは `agents/skills/claude_call.py` の `call()` を使う。

## 禁止事項

- Prophet 予測計算中に Claude API を呼ばない（Prophet はローカル計算で完結）
- Scout エージェント（scout_price / scout_logistics / scout_geopolitical）内で呼ばない
- 1銘柄ループの中で複数回呼ばない（1銘柄 = 最大1回）

## モデル固定

- `claude-haiku-4-5-20251001` のみ使用（Sonnet / Opus は使わない）
- `config/settings.yaml` の `llm.model` で一元管理する

## 月間コスト目安

- Merchant: 5銘柄 × 毎時 × 24h × 30日 = 3,600 回
- LLM Judge: 評価失敗時のみ（通常は月数十回程度）
- 合計: 約 3,600 回 / 月。Haiku なら概ね $1 未満
