from __future__ import annotations

from datetime import datetime, date
from typing import Any

from supabase import create_client, Client

from src.utils.config import SUPABASE_URL, SUPABASE_KEY


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def keepalive() -> None:
    """Supabase の無料枠を停止させないための定期 write。
    market_data に symbol='_keepalive' で1件 INSERT してすぐ DELETE する。
    """
    client = get_client()
    result = client.table("market_data").insert({
        "symbol": "_keepalive",
        "price": 0,
        "source": "keepalive",
    }).execute()
    row_id = result.data[0]["id"]
    client.table("market_data").delete().eq("id", row_id).execute()


# ---------------------------------------------------------------------------
# market_data
# ---------------------------------------------------------------------------

def insert_market_data(
    symbol: str,
    price: float,
    logistics_index: float | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    client = get_client()
    row = {
        "symbol": symbol,
        "price": price,
        "logistics_index": logistics_index,
        "source": source,
    }
    result = client.table("market_data").insert(row).execute()
    return result.data[0]


def fetch_market_data(symbol: str, days: int = 90) -> list[dict[str, Any]]:
    client = get_client()
    result = (
        client.table("market_data")
        .select("*")
        .eq("symbol", symbol)
        .order("timestamp", desc=False)
        .limit(days)
        .execute()
    )
    return result.data


# ---------------------------------------------------------------------------
# prediction_log
# ---------------------------------------------------------------------------

def insert_prediction(
    symbol: str,
    target_date: date,
    predicted_price: float,
    current_price: float | None = None,
    reasoning_text: str | None = None,
    prophet_params: dict | None = None,
) -> dict[str, Any]:
    client = get_client()
    row = {
        "symbol": symbol,
        "target_date": target_date.isoformat(),
        "predicted_price": predicted_price,
        "current_price": current_price,
        "reasoning_text": reasoning_text,
        "prophet_params": prophet_params or {},
    }
    result = client.table("prediction_log").insert(row).execute()
    return result.data[0]


def fetch_prediction(symbol: str, target_date: date) -> dict[str, Any] | None:
    """target_date に対する予測レコードを1件取得する（照合用）。"""
    client = get_client()
    result = (
        client.table("prediction_log")
        .select("*")
        .eq("symbol", symbol)
        .eq("target_date", target_date.isoformat())
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# feedback_log
# ---------------------------------------------------------------------------

def insert_feedback(
    symbol: str,
    error_rate: float,
    self_reflection_notes: str | None = None,
    parameter_updates: dict | None = None,
) -> dict[str, Any]:
    client = get_client()
    row = {
        "symbol": symbol,
        "error_rate": error_rate,
        "self_reflection_notes": self_reflection_notes,
        "parameter_updates": parameter_updates or {},
    }
    result = client.table("feedback_log").insert(row).execute()
    return result.data[0]


def fetch_latest_params(symbol: str) -> dict:
    """最新の parameter_updates を取得して Prophet に渡す。"""
    client = get_client()
    result = (
        client.table("feedback_log")
        .select("parameter_updates")
        .eq("symbol", symbol)
        .order("timestamp", desc=True)
        .limit(1)
        .execute()
    )
    if result.data and result.data[0]["parameter_updates"]:
        return result.data[0]["parameter_updates"]
    return {}


# ---------------------------------------------------------------------------
# news_log
# ---------------------------------------------------------------------------

def insert_news(
    symbol: str,
    headline: str,
    source: str | None = None,
    published_at: str | None = None,
) -> dict[str, Any]:
    client = get_client()
    row = {
        "symbol": symbol,
        "headline": headline,
        "source": source,
        "published_at": published_at,
    }
    result = client.table("news_log").insert(row).execute()
    return result.data[0]


def fetch_recent_news(symbol: str, limit: int = 5) -> list[str]:
    """直近のニュースヘッドラインを返す（LLM Judge のプロンプト用）。"""
    client = get_client()
    result = (
        client.table("news_log")
        .select("headline, source")
        .eq("symbol", symbol)
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        f"{row['headline']}（{row['source']}）" if row.get("source") else row["headline"]
        for row in result.data
    ]
