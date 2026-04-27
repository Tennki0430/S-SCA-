# データ品質規約

## 最低レコード数

Prophet の予測に必要な最低データ数:

- 価格データ（market_data）: **30件以上**（`MIN_ROWS = 30` in oracle.py）
- 30件未満の銘柄は予測をスキップし WARNING ログを出す
- スキップしても他の銘柄の処理を止めてはいけない

## データ鮮度

- Scout は毎時間実行され、最新終値を1件 INSERT する
- 90日以上古い market_data は定期削除（Supabase 無料枠 500MB を維持）
- BDI（BDRY ETF）は市場が閉まっている時間帯は前日値を使用

## 欠損値の扱い

- `prophet_wrapper.py` 内で `.ffill()` で前方補完する
- 全期間が欠損している regressor はその銘柄の予測をスキップ可
- `fillna(method=...)` は pandas 2.x で廃止されているため使わない

## INSERT バリデーション

- 価格 ≤ 0 のレコードは `insert_market_data()` に渡す前に弾く
- `None` / `NaN` / `inf` は INSERT しない
- 同一 symbol の重複 INSERT は許容する（タイムスタンプで識別）
