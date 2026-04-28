"""Prophet 共通ラッパー。

oracle.py から呼ばれる。feedback_log の parameter_updates を受け取り、
自律改善サイクルで更新されたパラメータを Prophet に反映する。
複数の外生変数（物流・地政学リスク指標）を add_regressor() で注入できる。
"""

import logging

import pandas as pd
from prophet import Prophet

logger = logging.getLogger(__name__)

PARAM_SCHEMA: dict[str, dict] = {
    "changepoint_prior_scale": {"default": 0.05,       "min": 0.001, "max": 0.5},
    "seasonality_prior_scale": {"default": 10.0,       "min": 0.1,   "max": 20.0},
    "holidays_prior_scale":    {"default": 10.0,       "min": 0.1,   "max": 20.0},
    "seasonality_mode":        {"default": "additive", "options": ["additive", "multiplicative"]},
}


def _resolve_params(overrides: dict) -> dict:
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
        yearly_seasonality=False,  # 数年分のデータがないと過学習するため無効
    )


def predict(
    df: pd.DataFrame,
    forecast_days: int = 14,
    regressors: dict[str, pd.Series] | None = None,
    param_overrides: dict | None = None,
) -> tuple[float, dict]:
    """
    Args:
        df: 'ds'（日付）と 'y'（価格）を持つ DataFrame
        forecast_days: 予測ホライズン（日数）
        regressors: 外生変数の辞書 {変数名: ds インデックスの Series}
                    例: {"BDI": series, "VIX": series, "Gold": series}
        param_overrides: Self-Reflection から渡されるパラメータ上書き

    Returns:
        (predicted_price, used_params): 予測値と使用パラメータのタプル
    """
    model = build_model(param_overrides)
    df = df.copy()

    active_regressors: dict[str, pd.Series] = {}
    if regressors:
        for name, series in regressors.items():
            if series.empty:
                continue
            reg_df = series.rename(name).reset_index()
            reg_df.columns = ["ds_reg", name]
            reg_df = reg_df.sort_values("ds_reg")
            merged = pd.merge_asof(
                df[["ds"]].sort_values("ds"),
                reg_df,
                left_on="ds",
                right_on="ds_reg",
                direction="nearest",
            )
            values = merged[name].values
            if pd.isna(values).any():
                logger.warning("外生変数 %s に NaN あり、スキップ", name)
                continue
            model.add_regressor(name)
            df[name] = values
            active_regressors[name] = series
            logger.info("外生変数を追加: %s (%d件)", name, len(series))

    model.fit(df)

    future = model.make_future_dataframe(periods=forecast_days)
    for name, series in active_regressors.items():
        last_val = float(series.iloc[-1])
        reg_df = series.rename(name).reset_index()
        reg_df.columns = ["ds_reg", name]
        reg_df = reg_df.sort_values("ds_reg")
        merged = pd.merge_asof(
            future[["ds"]].sort_values("ds"),
            reg_df,
            left_on="ds",
            right_on="ds_reg",
            direction="nearest",
        )
        future[name] = merged[name].fillna(last_val).values

    forecast = model.predict(future)
    predicted_price = float(forecast.iloc[-1]["yhat"])

    used_params = _resolve_params(param_overrides or {})
    return predicted_price, used_params
