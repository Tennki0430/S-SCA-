# スキル: APIコスト管理

## Claude API

| 項目 | ルール |
|---|---|
| 呼び出し箇所 | `merchant.py`・`self_reflection.py` の 2 箇所のみ |
| モデル | `claude-haiku-4-5-20251001`（最安）固定 |
| max_tokens | `merchant`: 512 / `self_reflection`: 256 |
| 呼び出し条件 | `merchant`: 変動率 ±10% 超のときのみ / `self_reflection`: 誤差 5% 超のときのみ |

**絶対にやらないこと**
- `oracle.py` や `scout_*.py` 内で Claude API を呼ぶ（予測はすべて Prophet で行う）
- Sonnet / Opus モデルを使う

## GitHub Actions 無料枠（2,000分/月）

| 対策 | 効果 |
|---|---|
| `timeout-minutes: 10` を設定 | 1 ジョブあたりの上限を設ける |
| `pip cache` を有効化（`cache: "pip"`） | 依存インストール時間を短縮 |
| 1時間おき cron = 月 720 回実行 | 1ジョブ平均 2.7 分以内に収める必要あり |

## X API 無料枠（1,500件/月 = 約50件/日）

- `merchant.py` は投稿を1日1回（銘柄ごと）に絞る
- 閾値（±10%）未満はスキップしてポスト数を節約

## Supabase 無料枠（500 MB）

- `market_data` の古いレコードを定期的に削除する（目安: 90日以上前）
- 削除クエリ例:
  ```sql
  DELETE FROM market_data WHERE timestamp < NOW() - INTERVAL '90 days';
  ```
