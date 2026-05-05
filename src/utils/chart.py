"""予測 vs 実績グラフ・精度推移グラフの生成ユーティリティ。"""
import io
import logging
from datetime import date, timedelta

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

matplotlib.use("Agg")

logger = logging.getLogger(__name__)

# 日本語フォント設定（優先順位順）
_JP_FONTS = ["Hiragino Sans", "BIZ UDGothic", "Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]
for _font in _JP_FONTS:
    try:
        matplotlib.rcParams["font.family"] = _font
        import matplotlib.font_manager as _fm
        if _fm.findfont(_font, fallback_to_default=False):
            break
    except Exception:
        continue

SYMBOL_JP: dict[str, str] = {
    "Wheat":   "小麦",
    "Corn":    "コーン",
    "Naphtha": "ナフサ",
    "Copper":  "銅",
    "Lithium": "リチウム",
}

COLOR_UP   = "#E8526A"   # 上昇予測
COLOR_DOWN = "#4A90D9"   # 下落予測
COLOR_GRAY = "#8A9BB0"
BG_COLOR   = "#0F1923"
TEXT_COLOR = "#E8EDF2"
GRID_COLOR = "#1E2D3D"


def _apply_dark_style(fig: plt.Figure, axes) -> None:
    fig.patch.set_facecolor(BG_COLOR)
    ax_list = axes if hasattr(axes, "__iter__") else [axes]
    for ax in ax_list:
        ax.set_facecolor(BG_COLOR)
        ax.tick_params(colors=TEXT_COLOR, labelsize=9)
        ax.xaxis.label.set_color(TEXT_COLOR)
        ax.yaxis.label.set_color(TEXT_COLOR)
        ax.title.set_color(TEXT_COLOR)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_COLOR)
        ax.grid(color=GRID_COLOR, linewidth=0.6, alpha=0.8)


def generate_prediction_chart(predictions: list[dict]) -> bytes:
    """直近の予測変化率（予測 vs 実績）を横棒グラフで返す。

    predictions: prediction_log の行リスト。
      各行に symbol / predicted_price / current_price / actual_price(optional) が必要。
    """
    if not predictions:
        return b""

    symbols      = [SYMBOL_JP.get(p["symbol"], p["symbol"]) for p in predictions]
    pred_pcts    = [
        (p["predicted_price"] - p["current_price"]) / p["current_price"] * 100
        for p in predictions
    ]
    actual_pcts  = [
        (p.get("actual_price", p["current_price"]) - p["current_price"]) / p["current_price"] * 100
        if p.get("actual_price") else None
        for p in predictions
    ]

    n = len(symbols)
    y = np.arange(n)
    height = 0.35

    fig, ax = plt.subplots(figsize=(8, max(3, n * 0.9)))
    _apply_dark_style(fig, ax)

    # 予測バー
    bars_pred = ax.barh(
        y + height / 2, pred_pcts, height,
        color=[COLOR_UP if v >= 0 else COLOR_DOWN for v in pred_pcts],
        alpha=0.85, label="AI予測変化率"
    )
    # 実績バー（あれば）
    has_actual = any(v is not None for v in actual_pcts)
    if has_actual:
        actual_vals = [v if v is not None else 0 for v in actual_pcts]
        ax.barh(
            y - height / 2, actual_vals, height,
            color=COLOR_GRAY, alpha=0.7, label="実績変化率"
        )

    ax.set_yticks(y)
    ax.set_yticklabels(symbols, fontsize=10, color=TEXT_COLOR)
    ax.axvline(0, color=TEXT_COLOR, linewidth=0.8, alpha=0.5)
    ax.set_xlabel("価格変化率（%）", color=TEXT_COLOR, fontsize=9)

    # バーに数値ラベル
    for bar, val in zip(bars_pred, pred_pcts):
        sign = "+" if val >= 0 else ""
        ax.text(
            bar.get_width() + (0.1 if val >= 0 else -0.1),
            bar.get_y() + bar.get_height() / 2,
            f"{sign}{val:.1f}%",
            va="center", ha="left" if val >= 0 else "right",
            fontsize=8, color=TEXT_COLOR,
        )

    title_date = date.today() + timedelta(days=14)
    ax.set_title(
        f"S-SCA 価格予測｜{title_date.strftime('%Y年%m月%d日')}の見通し",
        fontsize=11, color=TEXT_COLOR, pad=12, fontweight="bold"
    )

    legend_patches = [
        mpatches.Patch(color=COLOR_UP,   label="AI予測（上昇）"),
        mpatches.Patch(color=COLOR_DOWN, label="AI予測（下落）"),
    ]
    if has_actual:
        legend_patches.append(mpatches.Patch(color=COLOR_GRAY, label="実績"))
    ax.legend(handles=legend_patches, loc="lower right",
              facecolor=BG_COLOR, labelcolor=TEXT_COLOR, fontsize=8, framealpha=0.6)

    fig.tight_layout(pad=1.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return buf.getvalue()


def generate_accuracy_chart(feedback_rows: list[dict]) -> bytes:
    """銘柄別の予測精度（MAPE）推移を折れ線グラフで返す。

    feedback_rows: feedback_log の行リスト（timestamp / symbol / error_rate）。
    """
    if not feedback_rows:
        return b""

    from collections import defaultdict
    import pandas as pd

    df = pd.DataFrame(feedback_rows)
    df["ts"] = pd.to_datetime(df["timestamp"]).dt.date
    df["symbol_jp"] = df["symbol"].map(SYMBOL_JP).fillna(df["symbol"])

    symbols = df["symbol_jp"].unique()
    palette = ["#E8526A", "#4A90D9", "#F5A623", "#7ED321", "#BD10E0"]
    color_map = {s: palette[i % len(palette)] for i, s in enumerate(sorted(symbols))}

    fig, ax = plt.subplots(figsize=(8, 4))
    _apply_dark_style(fig, ax)

    for sym in sorted(symbols):
        sub = df[df["symbol_jp"] == sym].sort_values("ts")
        ax.plot(
            sub["ts"], sub["error_rate"],
            marker="o", markersize=5,
            linewidth=1.5, color=color_map[sym], label=sym,
        )

    ax.axhline(10, color=COLOR_UP, linewidth=0.8, linestyle="--", alpha=0.6, label="誤差10%ライン")
    ax.set_xlabel("日付", color=TEXT_COLOR, fontsize=9)
    ax.set_ylabel("MAPE（%）", color=TEXT_COLOR, fontsize=9)
    ax.set_title("予測精度の推移（MAPE — 低いほど精度が高い）",
                 fontsize=11, color=TEXT_COLOR, pad=12, fontweight="bold")
    ax.legend(facecolor=BG_COLOR, labelcolor=TEXT_COLOR, fontsize=8, framealpha=0.6)
    plt.xticks(rotation=30, ha="right")

    fig.tight_layout(pad=1.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return buf.getvalue()
