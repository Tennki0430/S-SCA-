"""Supabase にテーブルを初期化するスクリプト（初回のみ実行）。

使い方:
    python init_db.py

Supabase の SQL Editor でも同じ SQL を直接実行できる。
"""

from supabase import create_client
from src.utils.config import SUPABASE_URL, SUPABASE_KEY

DDL = """
-- 価格・物流データ
CREATE TABLE IF NOT EXISTS market_data (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol          TEXT NOT NULL,
    price           NUMERIC NOT NULL,
    logistics_index NUMERIC,
    source          TEXT
);

-- 予測ログ
CREATE TABLE IF NOT EXISTS prediction_log (
    id               BIGSERIAL PRIMARY KEY,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol           TEXT NOT NULL,
    target_date      DATE NOT NULL,
    predicted_price  NUMERIC NOT NULL,
    current_price    NUMERIC,
    reasoning_text   TEXT,
    prophet_params   JSONB DEFAULT '{}'::jsonb
);

-- フィードバック・自律改善ログ
CREATE TABLE IF NOT EXISTS feedback_log (
    id                    BIGSERIAL PRIMARY KEY,
    timestamp             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol                TEXT NOT NULL,
    error_rate            NUMERIC,
    self_reflection_notes TEXT,
    parameter_updates     JSONB DEFAULT '{}'::jsonb
);

-- インデックス（クエリ高速化）
CREATE INDEX IF NOT EXISTS idx_market_data_symbol_ts    ON market_data    (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_prediction_log_symbol_td ON prediction_log (symbol, target_date);
CREATE INDEX IF NOT EXISTS idx_feedback_log_symbol_ts   ON feedback_log   (symbol, timestamp DESC);
"""


def main() -> None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("=" * 60)
    print("以下の SQL を Supabase の SQL Editor に貼り付けて実行してください:")
    print("  Dashboard → SQL Editor → New query → 貼り付け → Run")
    print("=" * 60)
    print(DDL)
    print("=" * 60)
    print("接続確認: market_data テーブルへの疎通テスト...")
    try:
        result = client.table("market_data").select("id").limit(1).execute()
        print("✅ 接続成功。テーブルが存在します。")
    except Exception as e:
        print(f"⚠️  テーブルが見つかりません。上記 SQL を先に実行してください。\n   エラー: {e}")


if __name__ == "__main__":
    main()
