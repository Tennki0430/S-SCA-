from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
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


def cleanup_old_market_data(retain_days: int = 90) -> int:
    """90日以上古い market_data を削除して容量を節約する。削除件数を返す。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retain_days)).isoformat()
    client = get_client()
    result = (
        client.table("market_data")
        .delete()
        .lt("timestamp", cutoff)
        .execute()
    )
    return len(result.data)


def fetch_market_data(symbol: str, days: int = 90) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    client = get_client()
    result = (
        client.table("market_data")
        .select("*")
        .eq("symbol", symbol)
        .gte("timestamp", since)
        .order("timestamp", desc=False)
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


def update_feedback_notes(
    feedback_id: int,
    self_reflection_notes: str,
    parameter_updates: dict,
) -> None:
    """既存の feedback_log レコードに分析結果を書き込む（遡及適用用）。"""
    client = get_client()
    client.table("feedback_log").update({
        "self_reflection_notes": self_reflection_notes,
        "parameter_updates": parameter_updates,
    }).eq("id", feedback_id).execute()


def fetch_feedbacks_needing_analysis(threshold_pct: float = 5.0) -> list[dict[str, Any]]:
    """error_rate が閾値超かつ self_reflection_notes が未記入のレコードを返す。"""
    client = get_client()
    result = (
        client.table("feedback_log")
        .select("id, timestamp, symbol, error_rate")
        .gt("error_rate", threshold_pct)
        .is_("self_reflection_notes", "null")
        .order("timestamp", desc=False)
        .execute()
    )
    return result.data


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


def fetch_market_data_around_date(
    symbol: str,
    target_date: date,
    window_days: int = 3,
) -> list[dict[str, Any]]:
    """指定日の前後 window_days 日以内のデータを返す（先行指標スナップショット用）。"""
    since = (
        datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        - timedelta(days=window_days)
    ).isoformat()
    until = (
        datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        + timedelta(days=window_days + 1)
    ).isoformat()
    client = get_client()
    result = (
        client.table("market_data")
        .select("price, timestamp")
        .eq("symbol", symbol)
        .gte("timestamp", since)
        .lte("timestamp", until)
        .order("timestamp", desc=False)
        .execute()
    )
    return result.data


def fetch_recent_feedbacks(symbol: str, limit: int = 5) -> list[dict[str, Any]]:
    """直近の feedback_log を返す（誤差トレンド確認用）。"""
    client = get_client()
    result = (
        client.table("feedback_log")
        .select("timestamp, error_rate, self_reflection_notes, parameter_updates")
        .eq("symbol", symbol)
        .not_.is_("error_rate", "null")
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


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
