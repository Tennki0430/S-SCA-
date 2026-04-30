"""Prophet 共通ラッパー。

oracle.py から呼ばれる。feedback_log の parameter_updates を受け取り、
自律改善サイクルで更新されたパラメータを Prophet に反映する。
複数の外生変数（物流・地政学リスク指標）を add_regressor() で注入できる。

外生変数はスケールが大きく異なるため（Gold:$4000 vs BDI:$10 vs Corn:$476）、
z-score 正規化してから Prophet に渡す。正規化係数は逆変換不要（yhat への影響係数のみ学習）。
"""

import logging

import pandas as pd
from prophet import Prophet

logger = logging.getLogger(__name__)

PARAM_SCHEMA: dict[str, dict] = {
    # Prophet モデルパラメータ
    "changepoint_prior_scale": {"default": 0.05,       "min": 0.001, "max": 0.5},
    "seasonality_prior_scale": {"default": 10.0,       "min": 0.1,   "max": 20.0},
    "holidays_prior_scale":    {"default": 10.0,       "min": 0.1,   "max": 20.0},
    "seasonality_mode":        {"default": "additive", "options": ["additive", "multiplicative"]},
    # データ取得パラメータ（oracle.py が読み取る）
    "window_days": {"default": 90, "min": 30, "max": 180},
    # 外生変数除外リスト（oracle.py が読み取る）。例: ["Gold", "Oil"]
    # prophet_wrapper には渡されず oracle.py が事前にフィルタリングする
    "excluded_regressors": {"default": [], "options": "list"},
}

# 予測値が現在価格からこの比率を超えると異常とみなしてクリップ
MAX_CHANGE_RATIO = 0.30  # ±30%


def _resolve_params(overrides: dict) -> dict:
    resolved = {}
    for key, schema in PARAM_SCHEMA.items():
        val = overrides.get(key, schema["default"])
        if "options" in schema:
            if schema["options"] == "list":
                resolved[key] = val if isinstance(val, list) else schema["default"]
            else:
                resolved[key] = val if val in schema["options"] else schema["default"]
        else:
            resolved[key] = max(schema["min"], min(schema["max"], float(val)))
    return resolved


def _zscore_normalize(series: pd.Series) -> tuple[pd.Series, float, float]:
    """z-score 正規化。mean と std を返す（将来値の正規化に使用）。"""
    mean = float(series.mean())
    std = float(series.std())
    if std < 1e-8:
        std = 1.0
    return (series - mean) / std, mean, std


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
                    ※ スケールが異なっていても内部で z-score 正規化するので問題なし
        param_overrides: Self-Reflection から渡されるパラメータ上書き

    Returns:
        (predicted_price, used_params): 予測値と使用パラメータのタプル
    """
    model = build_model(param_overrides)
    df = df.copy()

    current_price = float(df["y"].iloc[-1])

    # 外生変数を z-score 正規化してから Prophet に渡す
    # Gold($4000) と BDI($10) のスケール差がそのまま入ると回帰係数が爆発するため
    active_regressors: dict[str, tuple[float, float]] = {}  # name -> (mean, std)

    if regressors:
        for name, series in regressors.items():
            if series.empty:
                continue

            # 正規化
            normalized_series, mean, std = _zscore_normalize(series)
            logger.info(
                "外生変数 %s: 元スケール [%.2f, %.2f] → z-score 正規化 (mean=%.2f, std=%.2f)",
                name, float(series.min()), float(series.max()), mean, std,
            )

            reg_df = normalized_series.rename(name).reset_index()
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
            active_regressors[name] = (mean, std)
            logger.info("外生変数を追加: %s (%d件)", name, len(series))

    model.fit(df)

    future = model.make_future_dataframe(periods=forecast_days)

    for name, (mean, std) in active_regressors.items():
        series = regressors[name]  # type: ignore[index]
        # 最新値を正規化して未来全期間に使用
        last_val_raw = float(series.iloc[-1])
        last_val_normalized = (last_val_raw - mean) / std

        reg_df = ((series - mean) / std).rename(name).reset_index()
        reg_df.columns = ["ds_reg", name]
        reg_df = reg_df.sort_values("ds_reg")

        merged = pd.merge_asof(
            future[["ds"]].sort_values("ds"),
            reg_df,
            left_on="ds",
            right_on="ds_reg",
            direction="nearest",
        )
        future[name] = merged[name].fillna(last_val_normalized).values

    forecast = model.predict(future)
    raw_predicted = float(forecast.iloc[-1]["yhat"])

    # サニティチェック：現在価格から ±MAX_CHANGE_RATIO を超えたらクリップ
    lower = current_price * (1 - MAX_CHANGE_RATIO)
    upper = current_price * (1 + MAX_CHANGE_RATIO)

    if raw_predicted < lower or raw_predicted > upper:
        clipped = max(lower, min(upper, raw_predicted))
        logger.warning(
            "予測値 %.2f が現在価格 %.2f から ±%.0f%% を超えているため %.2f にクリップ",
            raw_predicted, current_price, MAX_CHANGE_RATIO * 100, clipped,
        )
        predicted_price = clipped
    else:
        predicted_price = raw_predicted

    # 価格は必ず正
    if predicted_price <= 0:
        logger.warning("予測値が負 (%.2f)、現在価格を使用", predicted_price)
        predicted_price = current_price

    used_params = _resolve_params(param_overrides or {})
    return predicted_price, used_params
