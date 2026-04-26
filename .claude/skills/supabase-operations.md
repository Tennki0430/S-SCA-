# スキル: Supabase 操作パターン

## 接続

```python
from supabase import create_client
client = create_client(SUPABASE_URL, SUPABASE_KEY)
```

接続は毎回 `get_client()` で生成する（`src/utils/database.py` に集約済み）。

## INSERT

```python
result = client.table("market_data").insert({
    "symbol": "Wheat",
    "price": 500.0,
    "source": "yfinance",
}).execute()
saved = result.data[0]  # 保存されたレコード
```

## SELECT（フィルタ・ソート・件数制限）

```python
result = (
    client.table("market_data")
    .select("*")
    .eq("symbol", "Wheat")
    .order("timestamp", desc=False)
    .limit(90)
    .execute()
)
records = result.data  # list[dict]
```

## よくあるパターン

**最新1件を取得する**
```python
result = client.table("feedback_log").select("*").eq("symbol", symbol).order("timestamp", desc=True).limit(1).execute()
row = result.data[0] if result.data else None
```

**レコードが存在しない場合の安全な処理**
```python
if not result.data:
    return None  # または空の dict/list
```

## 無料枠の注意事項

- ストレージ上限: 500 MB → `market_data` は90日以上前のレコードを定期的に削除する
- 7日間アクセスなしで DB が自動停止する → hourly cron で必ず write を行う
- Supabase Python クライアントは DDL（CREATE TABLE）を直接実行できない → 初期化は SQL Editor で行う
