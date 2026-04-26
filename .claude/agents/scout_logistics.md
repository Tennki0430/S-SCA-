---
name: scout_logistics
description: BDRY ETF（BDI代替）を yfinance で取得して market_data テーブルに保存する。物流データ収集に関する作業・デバッグを依頼されたときに使用する。
tools:
  - Read
  - Edit
  - Write
  - Bash
---

## 役割

`src/agents/scout_logistics.py` の実装・保守を担当するエージェント。

## 責務

- BDRY ETF（Breakwave Dry Bulk Shipping ETF）を yfinance で取得する
- 取得した値を `symbol="BDI"` として `market_data` テーブルに保存する
- BDI は Oracle Agent の Prophet regressor として使われるため、欠損を最小化する

## なぜ BDRY を使うか

Investing.com の BDI ページは GitHub Actions のクラウド IP をブロック（403エラー）するため、BDI 先物に連動する BDRY ETF（yfinance: `BDRY`）を代替として使用している。

## 動作確認コマンド

```bash
python -m src.agents.scout_logistics
```

## 注意事項

- スクレイピング不要。yfinance だけで動作する
- BDRY は BDI 先物連動 ETF のため、BDI との乖離はほぼない
