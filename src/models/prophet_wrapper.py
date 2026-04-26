"""Prophet 共通ラッパー。

oracle.py から呼ばれる。feedback_log の parameter_updates を受け取り、
自律改善サイクルで更新されたパラメータを Prophet に反映する。
"""

import logging
from datetime import date, timedelta

import pandas as pd
from prophet import Prophet

logger = logging.getLogger(__name__)

# Self-Reflection が調整できるパラメータと許容範囲
PARAM_SCHEMA: dict[str, dict] = {
    "changepoint_prior_scale": {"default": 0.05,       "min": 0.001, "max": 0.5},
    "seasonality_prior_scale": {"default": 10.0,       "min": 0.1,   "max": 20.0},
    "holidays_prior_scale":    {"default": 10.0,       "min": 0.1,   "max": 20.0},
    "seasonality_mode":        {"default": "additive", "options": ["additive", "multiplicative"]},
}


def _resolve_params(overrides: dict) -> dict:
    """overrides を PARAM_SCHEMA の範囲内に丸めて返す。範囲外は default に戻す。"""
    resolved = {}
    for key, schema in PARAM_SCHEMA.items():
        val = overrides.get(key, schema["default"])
        if "options" in schema:
            resolved[key] = val if val in schema["options"] else schema["default"]
        else:
            resolved[key] = max(schema["min"], min(schema["max"], float(val)))
    return resolved


def build_model(param_overrides: dict | None = None) -> Prophet:
    params = _resolve_params(param_overrides or {})
    logger.info("Prophet パラメータ: %s", params)
    return Prophet(
        changepoint_prior_scale=params["changepoint_prior_scale"],
        seasonality_prior_scale=params["seasonality_prior_scale"],
        holidays_prior_scale=params["holidays_prior_scale"],
        seasonality_mode=params["seasonality_mode"],
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
    )


def predict(
    df: pd.DataFrame,
    forecast_days: int = 14,
    logistics_series: pd.Series | None = None,
    param_overrides: dict | None = None,
) -> tuple[float, dict]:
    """
    Args:
        df: 'ds'（日付）と 'y'（価格）を持つ DataFrame
        forecast_days: 予測ホライズン（日数）
        logistics_series: BDI 等の外生変数（ds インデックスの Series）
        param_overrides: Self-Reflection から渡されるパラメータ上書き

    Returns:
        (predicted_price, used_params): 予測値と使用パラメータのタプル
    """
    model = build_model(param_overrides)

    if logistics_series is not None:
        model.add_regressor("logistics_index")
        df = df.copy()
        df["logistics_index"] = df["ds"].map(logistics_series)
        df["logistics_index"].fillna(method="ffill", inplace=True)

    model.fit(df)

    future = model.make_future_dataframe(periods=forecast_days)

    if logistics_series is not None:
        last_bdi = logistics_series.iloc[-1] if not logistics_series.empty else 0.0
        future["logistics_index"] = future["ds"].map(logistics_series).fillna(last_bdi)

    forecast = model.predict(future)
    target_row = forecast.iloc[-1]
    predicted_price = float(target_row["yhat"])

    used_params = _resolve_params(param_overrides or {})
    return predicted_price, used_params
