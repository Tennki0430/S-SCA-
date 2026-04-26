# スキル: Prophet による価格予測

## 基本的な使い方

```python
from prophet import Prophet
import pandas as pd

# DataFrame は 'ds'（日付）と 'y'（価格）の2カラムが必須
df = pd.DataFrame({"ds": dates, "y": prices})
df["ds"] = pd.to_datetime(df["ds"]).dt.tz_localize(None)  # タイムゾーンなしに統一

model = Prophet()
model.fit(df)

future = model.make_future_dataframe(periods=14)
forecast = model.predict(future)
predicted = float(forecast.iloc[-1]["yhat"])
```

## BDI を外生変数（regressor）として注入する

```python
model = Prophet()
model.add_regressor("logistics_index")

# df に logistics_index カラムを追加してから fit する
df["logistics_index"] = bdi_series  # 欠損は ffill で埋める

model.fit(df)

# future にも同じカラムが必要（未来分は最新値で埋める）
future["logistics_index"] = last_bdi_value
forecast = model.predict(future)
```

## チューニング可能なパラメータ

| パラメータ | デフォルト | 効果 |
|---|---|---|
| `changepoint_prior_scale` | 0.05 | 大きいほどトレンド変化に敏感 |
| `seasonality_prior_scale` | 10.0 | 大きいほど季節性を強く反映 |
| `seasonality_mode` | `additive` | 価格変動が比率的なら `multiplicative` |

## よくあるエラーと対処

| エラー | 原因 | 対処 |
|---|---|---|
| `ValueError: ds has timezone info` | ds にタイムゾーンが残っている | `.dt.tz_localize(None)` を追加 |
| `ValueError: y column must have at least 2 non-NaN values` | データが少なすぎる | `MIN_ROWS = 30` でスキップ |
| 予測が直線になる | データ量不足 or 変動が小さい | `changepoint_prior_scale` を上げる |
