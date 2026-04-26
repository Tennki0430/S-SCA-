# Python コーディング規約（S-SCA プロジェクト）

## 基本方針

- Python 3.11+ の型ヒントを全関数シグネチャに付ける
- フォーマッタ: `black`、リンター: `ruff`
- `print()` は使わない。必ず `logging` モジュールを使う

## ログ設定

各ファイルの先頭で以下のように宣言する:

```python
import logging
logger = logging.getLogger(__name__)
```

`main.py` でのみ `basicConfig` を呼ぶ。各エージェントは `logger` を使うだけでよい。

## エラー処理

- 外部 API 呼び出しは全て `try/except` で囲み、`logger.error()` に記録する
- 1銘柄の失敗が他の銘柄の処理を止めてはいけない（ループ内で個別に catch）
- リトライは `@retry` デコレーター（`src/utils/retry.py`）を使う。独自リトライ処理を書かない

## 外部 API 呼び出しのルール

- 全ての外部 API 呼び出しに `timeout` を設定する（最低 10 秒）
- `requests.get/post` には必ず `timeout=15` を付ける

## 不変オブジェクト

設定値・定数は `config.py` に集約し、各ファイルで直接 `os.getenv()` を呼ばない。

## Claude API 利用制限

- 呼び出し箇所: `merchant.py`・`self_reflection.py` の 2 箇所のみ
- モデル: `claude-haiku-4-5-20251001` 固定（コスト管理）
- `max_tokens` は用途に応じて最小限に設定する
