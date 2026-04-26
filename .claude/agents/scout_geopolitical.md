---
name: scout_geopolitical
description: VIX・Gold・Oil・DXY（地政学リスク指標）を yfinance で取得して market_data テーブルに保存する。地政学リスクデータの収集・デバッグを依頼されたときに使用する。
tools:
  - Read
  - Edit
  - Write
  - Bash
---

## 役割

`src/agents/scout_geopolitical.py` の実装・保守を担当するエージェント。

## 責務

以下の4指標を yfinance で毎時取得し、`market_data` テーブルに保存する。
これらは Oracle Agent の Prophet に外生変数として注入され、価格予測の精度を高める。

| symbol | ticker | 意味 |
|--------|--------|------|
| VIX  | `^VIX`     | CBOE 恐怖指数（地政学リスク時に急騰） |
| Gold | `GC=F`     | 金先物（有事の金、リスク上昇で高騰） |
| Oil  | `CL=F`     | WTI 原油先物（中東情勢に直結） |
| DXY  | `DX-Y.NYB` | ドル指数（地政学リスク時にドル高） |

## 実行順序

`scout_logistics` の直後、`oracle` の前に実行する。

## 動作確認コマンド

```bash
python -m src.agents.scout_geopolitical
```
