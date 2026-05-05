"""予測 vs 実績ダッシュボード画像生成ユーティリティ。"""
import io
import logging
from datetime import date, timedelta

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import pandas as pd

matplotlib.use("Agg")

logger = logging.getLogger(__name__)

# 日本語フォント
_JP_FONTS = ["Hiragino Sans", "BIZ UDGothic", "Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]
for _font in _JP_FONTS:
    try:
        import matplotlib.font_manager as _fm
        if _fm.findfont(_font, fallback_to_default=False):
            matplotlib.rcParams["font.family"] = _font
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

PALETTE = ["#E8526A", "#4A90D9", "#F5A623", "#7ED321", "#BD10E0"]
SYM_COLORS = {s: PALETTE[i] for i, s in enumerate(["Wheat", "Corn", "Naphtha", "Copper", "Lithium"])}

BG      = "#0F1923"
CARD    = "#162030"
BORDER  = "#1E2D3D"
TEXT    = "#E8EDF2"
MUTED   = "#8A9BB0"
GREEN   = "#7ED321"
RED     = "#E8526A"
BLUE    = "#4A90D9"
YELLOW  = "#F5A623"


def _style(ax: plt.Axes) -> None:
    ax.set_facecolor(CARD)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.title.set_color(TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(BORDER)
    ax.grid(color=BORDER, linewidth=0.5, alpha=0.8)


def generate_dashboard(
    latest_preds: list[dict],
    past_preds: list[dict],
    actual_map: dict[tuple, float],
    feedback_rows: list[dict],
) -> bytes:
    """全銘柄の予測 vs 実績ダッシュボードを1枚の PNG で返す。

    Args:
        latest_preds: 最新予測 (prediction_log の各銘柄最新1件)
        past_preds: 過去予測 (target_date が過去のもの)
        actual_map: {(symbol, target_date): actual_price} 実際の価格
        feedback_rows: feedback_log 全件
    """
    fig = plt.figure(figsize=(14, 16), facecolor=BG)
    fig.patch.set_facecolor(BG)

    gs = gridspec.GridSpec(
        4, 1,
        figure=fig,
        height_ratios=[1.2, 2.2, 2.2, 1.8],
        hspace=0.45,
    )

    # ──────────────────────────────────────────────
    # セクション 1: 今日の予測サマリーカード（テキスト）
    # ──────────────────────────────────────────────
    ax_header = fig.add_subplot(gs[0])
    ax_header.set_facecolor(BG)
    for spine in ax_header.spines.values():
        spine.set_visible(False)
    ax_header.set_xticks([])
    ax_header.set_yticks([])

    target = date.today() + timedelta(days=14)
    ax_header.text(
        0.5, 0.92,
        "S-SCA  コモディティAI予測ダッシュボード",
        ha="center", va="top", fontsize=15, fontweight="bold",
        color=TEXT, transform=ax_header.transAxes,
    )
    ax_header.text(
        0.5, 0.72,
        f"予測期日: {target.strftime('%Y年%m月%d日')}（14日後）",
        ha="center", va="top", fontsize=10, color=MUTED,
        transform=ax_header.transAxes,
    )

    # 銘柄ごとにミニカード
    n = len(latest_preds)
    for i, p in enumerate(sorted(latest_preds, key=lambda x: x["symbol"])):
        x = (i + 0.5) / n
        pct = (p["predicted_price"] - p["current_price"]) / p["current_price"] * 100
        color = RED if pct >= 0 else BLUE
        sign  = "+" if pct >= 0 else ""
        sym   = SYMBOL_JP.get(p["symbol"], p["symbol"])
        ax_header.text(x, 0.44, sym, ha="center", va="top", fontsize=9,
                       color=MUTED, transform=ax_header.transAxes)
        ax_header.text(x, 0.22, f"{sign}{pct:.1f}%", ha="center", va="top",
                       fontsize=14, fontweight="bold", color=color,
                       transform=ax_header.transAxes)

    # ──────────────────────────────────────────────
    # セクション 2: 予測 vs 実績 棒グラフ（全銘柄 × 全評価日）
    # ──────────────────────────────────────────────
    ax_bar = fig.add_subplot(gs[1])
    _style(ax_bar)

    # past_preds から実績あるものだけ抽出
    records = []
    for p in past_preds:
        key = (p["symbol"], p["target_date"])
        if key in actual_map:
            pred_pct   = (p["predicted_price"] - p["current_price"]) / p["current_price"] * 100
            actual_pct = (actual_map[key]       - p["current_price"]) / p["current_price"] * 100
            records.append({
                "symbol": p["symbol"],
                "date":   p["target_date"],
                "pred":   pred_pct,
                "actual": actual_pct,
                "hit":    (pred_pct * actual_pct) > 0,  # 方向が一致
            })

    if records:
        df = pd.DataFrame(records).sort_values(["symbol", "date"])
        symbols = sorted(df["symbol"].unique())
        group_size = len(symbols)
        bar_w = 0.35
        dates = sorted(df["date"].unique())[-12:]  # 直近12期分
        df = df[df["date"].isin(dates)]

        x_labels = []
        x_positions = []
        for di, d in enumerate(dates):
            for si, sym in enumerate(symbols):
                sub = df[(df["date"] == d) & (df["symbol"] == sym)]
                if sub.empty:
                    continue
                row   = sub.iloc[0]
                xpos  = di * (group_size + 1) + si
                color = SYM_COLORS.get(sym, MUTED)

                ax_bar.bar(xpos - bar_w / 2, row["pred"],   bar_w,
                           color=color, alpha=0.6, label=f"予測_{sym}" if di == 0 else "")
                ax_bar.bar(xpos + bar_w / 2, row["actual"], bar_w,
                           color=color, alpha=1.0, label=f"実績_{sym}" if di == 0 else "")
                x_positions.append(xpos)

            x_labels.append(d[5:])  # MM-DD

        ax_bar.set_xticks([di * (group_size + 1) + (group_size - 1) / 2 for di in range(len(dates))])
        ax_bar.set_xticklabels(x_labels, rotation=30, ha="right", fontsize=7.5)
        ax_bar.axhline(0, color=TEXT, linewidth=0.6, alpha=0.4)
        ax_bar.set_ylabel("価格変化率（%）", fontsize=9)
        ax_bar.set_title("予測 vs 実績（薄色＝AI予測・濃色＝実績）", fontsize=10, pad=8)

        legend_handles = [
            mpatches.Patch(color=SYM_COLORS[s], alpha=0.5, label=f"{SYMBOL_JP[s]} 予測")
            for s in symbols
        ] + [
            mpatches.Patch(color=SYM_COLORS[s], alpha=1.0, label=f"{SYMBOL_JP[s]} 実績")
            for s in symbols
        ]
        ax_bar.legend(handles=legend_handles, ncol=5, fontsize=7,
                      facecolor=CARD, labelcolor=TEXT, framealpha=0.7,
                      loc="upper left", bbox_to_anchor=(0, -0.22))
    else:
        ax_bar.text(0.5, 0.5, "実績データ蓄積中…", ha="center", va="center",
                    color=MUTED, fontsize=12, transform=ax_bar.transAxes)
        ax_bar.set_title("予測 vs 実績", fontsize=10)

    # ──────────────────────────────────────────────
    # セクション 3: 方向一致率 + MAPE推移（2列）
    # ──────────────────────────────────────────────
    gs_mid = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=gs[2], wspace=0.35)
    ax_hit  = fig.add_subplot(gs_mid[0])
    ax_mape = fig.add_subplot(gs_mid[1])
    _style(ax_hit)
    _style(ax_mape)

    # 方向一致率（銘柄別）
    if records:
        df_all = pd.DataFrame(records)
        hit_rates = df_all.groupby("symbol")["hit"].mean() * 100
        syms = sorted(hit_rates.index)
        colors = [GREEN if hit_rates[s] >= 60 else (YELLOW if hit_rates[s] >= 50 else RED) for s in syms]
        bars = ax_hit.barh(
            [SYMBOL_JP.get(s, s) for s in syms],
            [hit_rates[s] for s in syms],
            color=colors, alpha=0.85, height=0.5,
        )
        ax_hit.axvline(50, color=MUTED, linewidth=1, linestyle="--", alpha=0.6)
        ax_hit.axvline(60, color=GREEN, linewidth=1, linestyle="--", alpha=0.4)
        ax_hit.set_xlim(0, 100)
        ax_hit.set_xlabel("方向一致率（%）", fontsize=9)
        ax_hit.set_title("上昇/下落の方向予測精度", fontsize=10, pad=8)
        for bar, s in zip(bars, syms):
            ax_hit.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                        f"{hit_rates[s]:.0f}%", va="center", fontsize=8, color=TEXT)
    else:
        ax_hit.text(0.5, 0.5, "蓄積中…", ha="center", va="center",
                    color=MUTED, transform=ax_hit.transAxes)
        ax_hit.set_title("方向予測精度", fontsize=10)

    # MAPE推移（銘柄別折れ線）
    if feedback_rows:
        df_fb = pd.DataFrame(feedback_rows)
        df_fb["dt"] = pd.to_datetime(df_fb["timestamp"]).dt.date
        for sym in sorted(df_fb["symbol"].unique()):
            sub = df_fb[df_fb["symbol"] == sym].sort_values("dt").tail(10)
            ax_mape.plot(
                range(len(sub)), sub["error_rate"],
                marker="o", markersize=4, linewidth=1.5,
                color=SYM_COLORS.get(sym, MUTED),
                label=SYMBOL_JP.get(sym, sym),
            )
        ax_mape.axhline(10, color=RED, linewidth=0.8, linestyle="--", alpha=0.5)
        ax_mape.set_ylabel("MAPE（%）", fontsize=9)
        ax_mape.set_title("予測誤差の推移（低いほど高精度）", fontsize=10, pad=8)
        ax_mape.set_xticks([])
        ax_mape.legend(fontsize=7.5, facecolor=CARD, labelcolor=TEXT, framealpha=0.7)
    else:
        ax_mape.text(0.5, 0.5, "蓄積中…", ha="center", va="center",
                     color=MUTED, transform=ax_mape.transAxes)
        ax_mape.set_title("誤差推移", fontsize=10)

    # ──────────────────────────────────────────────
    # セクション 4: 精度サマリーテーブル
    # ──────────────────────────────────────────────
    ax_tbl = fig.add_subplot(gs[3])
    ax_tbl.set_facecolor(CARD)
    for spine in ax_tbl.spines.values():
        spine.set_edgecolor(BORDER)
    ax_tbl.set_xticks([])
    ax_tbl.set_yticks([])
    ax_tbl.set_title("最新の予測精度レポート", fontsize=10, pad=8, color=TEXT)

    if feedback_rows:
        df_fb2 = pd.DataFrame(feedback_rows)
        df_fb2["dt"] = pd.to_datetime(df_fb2["timestamp"]).dt.date
        latest_fb = df_fb2.sort_values("dt").groupby("symbol").last().reset_index()

        col_labels = ["銘柄", "評価日", "MAPE", "精度判定", "AIコメント（要約）"]
        col_x      = [0.04, 0.16, 0.29, 0.41, 0.56]
        row_h      = 0.72 / (len(latest_fb) + 1)

        # ヘッダー
        for cx, cl in zip(col_x, col_labels):
            ax_tbl.text(cx, 0.92, cl, transform=ax_tbl.transAxes,
                        fontsize=8, color=MUTED, fontweight="bold")

        for ri, (_, row) in enumerate(latest_fb.iterrows()):
            y = 0.92 - (ri + 1) * row_h - 0.04
            mape = row["error_rate"]
            if mape < 8:
                verdict, color = "◎ 高精度", GREEN
            elif mape < 15:
                verdict, color = "○ 良好", YELLOW
            else:
                verdict, color = "△ 改善中", RED

            note = (row.get("self_reflection_notes") or "")[:40] + "…"
            vals = [
                SYMBOL_JP.get(row["symbol"], row["symbol"]),
                str(row["dt"]),
                f"{mape:.1f}%",
                verdict,
                note,
            ]
            for cx, val, fc in zip(col_x, vals, [TEXT, MUTED, color, color, MUTED]):
                ax_tbl.text(cx, y, val, transform=ax_tbl.transAxes,
                            fontsize=7.5, color=fc, va="center")

            # 区切り線
            line = plt.Line2D([0.02, 0.98], [y - 0.01, y - 0.01],
                              color=BORDER, linewidth=0.4,
                              transform=ax_tbl.transAxes)
            ax_tbl.add_line(line)

    fig.tight_layout(pad=2.0)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def generate_pdca_report(
    feedback_rows: list[dict],
    latest_preds: list[dict],
    past_preds: list[dict],
    actual_map: dict[tuple, float],
) -> bytes:
    """PDCAサイクルをわかりやすく伝えるインフォグラフィック型レポート。

    Section 1 [PLAN/DO] 今日の予測 + 直近の予測vs実績カード
    Section 2 [CHECK]   銘柄別「改善中/要改善」判定 + MAPE推移
    Section 3 [ACT]     PDCAで何を学んだか（パラメータ変更ログ）
    """
    if not feedback_rows:
        return b""

    df_fb = pd.DataFrame(feedback_rows)
    df_fb["dt"] = pd.to_datetime(df_fb["timestamp"], format="ISO8601", utc=True).dt.date
    df_fb = df_fb.sort_values("dt")
    symbols = ["Wheat", "Corn", "Naphtha", "Copper", "Lithium"]

    # ── 改善サマリーを計算 ──
    summary: dict[str, dict] = {}
    for sym in symbols:
        sub = df_fb[(df_fb["symbol"] == sym) & df_fb["error_rate"].notna()]
        if len(sub) < 4:
            continue
        n     = len(sub)
        first = sub.iloc[: n // 2]["error_rate"].mean()
        last  = sub.iloc[n // 2 :]["error_rate"].mean()
        chg   = sub[sub["parameter_updates"].apply(lambda x: bool(x and len(x) > 0))]
        latest_params = chg.iloc[-1]["parameter_updates"] if not chg.empty else {}
        summary[sym] = {
            "first": first, "last": last,
            "improved": first > last,
            "delta": first - last,
            "n_changes": len(chg),
            "latest_params": latest_params,
        }

    # ── 予測 vs 実績データ（銘柄・日付ごと）──
    records = []
    for p in past_preds:
        key = (p["symbol"], p["target_date"])
        if key not in actual_map:
            continue
        cur = p["current_price"]
        if cur == 0:
            continue
        pred_pct = (p["predicted_price"] - cur) / cur * 100
        act_pct  = (actual_map[key] - cur) / cur * 100
        records.append({
            "symbol": p["symbol"], "date": p["target_date"],
            "pred": pred_pct, "actual": act_pct,
            "hit": (pred_pct * act_pct) > 0,
        })
    df_vs = pd.DataFrame(records).sort_values("date") if records else pd.DataFrame()

    # 直近の評価日（target_date）
    latest_target = df_vs["date"].max() if not df_vs.empty else None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    fig = plt.figure(figsize=(13, 22), facecolor=BG)
    fig.patch.set_facecolor(BG)
    gs = gridspec.GridSpec(4, 1, figure=fig,
                           height_ratios=[2.0, 1.8, 2.8, 2.2], hspace=0.55)

    # ────────────────────────────────────────
    # Section 1: 今日の予測 + 直近の予測vs実績 [PLAN / DO / CHECK]
    # ────────────────────────────────────────
    ax0 = fig.add_subplot(gs[0])
    ax0.set_facecolor(BG)
    for sp in ax0.spines.values(): sp.set_visible(False)
    ax0.set_xticks([]); ax0.set_yticks([])

    # タイトル
    ax0.text(0.5, 0.99, "S-SCA  AIコモディティ価格予測レポート",
             ha="center", va="top", fontsize=15, fontweight="bold",
             color=TEXT, transform=ax0.transAxes)
    target = date.today() + timedelta(days=14)
    ax0.text(0.5, 0.90,
             f"14日後（{target.strftime('%Y年%m月%d日')}）の価格変化率を予測し、"
             "実績と比較しながらAIが自律的に精度を改善しています",
             ha="center", va="top", fontsize=8.5, color=MUTED, transform=ax0.transAxes)

    # 区切り線
    ln = plt.Line2D([0.01, 0.99], [0.80, 0.80], color=BORDER, linewidth=0.8,
                    transform=ax0.transAxes)
    ax0.add_line(ln)

    # ── 左半分: 今日の予測 ──
    ax0.text(0.01, 0.76, f"【PLAN/DO】 今日の予測  →  {target.strftime('%m/%d')} の見通し",
             ha="left", va="top", fontsize=9, color=YELLOW, fontweight="bold",
             transform=ax0.transAxes)
    preds_sorted = sorted(latest_preds, key=lambda x: x["symbol"])
    for i, p in enumerate(preds_sorted):
        x   = 0.02 + i * 0.19
        pct = (p["predicted_price"] - p["current_price"]) / p["current_price"] * 100
        col = RED if pct >= 0 else BLUE
        sign = "+" if pct >= 0 else ""
        sym_jp = SYMBOL_JP.get(p["symbol"], p["symbol"])
        ax0.text(x + 0.07, 0.62, sym_jp, ha="center", va="top", fontsize=8.5,
                 color=MUTED, transform=ax0.transAxes)
        ax0.text(x + 0.07, 0.48, f"{sign}{pct:.1f}%", ha="center", va="top",
                 fontsize=16, fontweight="bold", color=col, transform=ax0.transAxes)
        ax0.text(x + 0.07, 0.33, f"現在 {p['current_price']:.1f}", ha="center", va="top",
                 fontsize=7, color=MUTED, transform=ax0.transAxes)

    # ── 右半分: 直近の予測vs実績 ──
    ln2 = plt.Line2D([0.0, 0.0], [0.80, 0.0], color=BORDER, linewidth=0.8,
                     transform=ax0.transAxes)
    ax0.add_line(ln2)

    if latest_target and not df_vs.empty:
        df_latest = df_vs[df_vs["date"] == latest_target]
        ax0.text(0.01, 0.20,
                 f"【CHECK】 直近の予測結果  target: {latest_target}",
                 ha="left", va="top", fontsize=9, color=YELLOW, fontweight="bold",
                 transform=ax0.transAxes)

        for i, sym in enumerate(symbols):
            row = df_latest[df_latest["symbol"] == sym]
            if row.empty:
                continue
            r    = row.iloc[0]
            x    = 0.02 + i * 0.19
            col  = SYM_COLORS.get(sym, MUTED)
            hit  = r["hit"]
            mark = "◎" if hit else "✗"
            mcol = GREEN if hit else RED

            ax0.text(x + 0.07, 0.13, SYMBOL_JP.get(sym, sym),
                     ha="center", va="top", fontsize=8, color=MUTED,
                     transform=ax0.transAxes)

            pred_s = ("+" if r["pred"] >= 0 else "") + f"{r['pred']:.1f}%"
            act_s  = ("+" if r["actual"] >= 0 else "") + f"{r['actual']:.1f}%"
            ax0.text(x + 0.07, 0.04,
                     f"予測 {pred_s}\n実績 {act_s}  {mark}",
                     ha="center", va="top", fontsize=7.5, color=mcol,
                     transform=ax0.transAxes)
    else:
        ax0.text(0.5, 0.15, "直近の実績データ蓄積中…",
                 ha="center", va="top", fontsize=9, color=MUTED,
                 transform=ax0.transAxes)

    # ────────────────────────────────────────
    # Section 2: 銘柄別「改善中/要改善」判定バー [CHECK]
    # ────────────────────────────────────────
    ax1 = fig.add_subplot(gs[1])
    _style(ax1)

    syms_ordered = [s for s in symbols if s in summary]
    bar_h = 0.32

    for yi, sym in enumerate(syms_ordered):
        s   = summary[sym]
        col = SYM_COLORS.get(sym, MUTED)
        ax1.barh(yi + bar_h / 2, s["first"], bar_h, color=col, alpha=0.30)
        ax1.barh(yi - bar_h / 2, s["last"],  bar_h, color=col, alpha=0.90)

        # 判定バッジ
        verdict = "✅ 改善中" if s["improved"] else "⚠️ 要改善"
        vcol    = GREEN if s["improved"] else RED
        delta_s = f"{'▼' if s['improved'] else '▲'}{abs(s['delta']):.1f}%pt"
        ax1.text(max(s["first"], s["last"]) + 0.3, yi + 0.15,
                 f"{verdict}  {delta_s}", va="center", fontsize=9,
                 color=vcol, fontweight="bold")

        # コメント
        if s["improved"]:
            comment = f"PDCAで誤差 {s['first']:.1f}%→{s['last']:.1f}% に改善"
        else:
            comment = f"外部ショック等で誤差拡大中。AIがパラメータ調整中"
        ax1.text(max(s["first"], s["last"]) + 0.3, yi - 0.15,
                 comment, va="center", fontsize=7.5, color=MUTED)

    ax1.set_yticks(range(len(syms_ordered)))
    ax1.set_yticklabels([SYMBOL_JP.get(s, s) for s in syms_ordered], fontsize=10)
    ax1.set_xlabel("MAPE（%）── 低いほど精度が高い", fontsize=9)
    ax1.axvline(10, color=RED, linewidth=1.0, linestyle="--", alpha=0.5)
    ax1.set_title(
        "【CHECK】銘柄別 予測精度の評価 — 薄色＝運用開始時  濃色＝直近  "
        "MAPE 10%以下が目標",
        fontsize=10, pad=8, color=TEXT)

    handles = [mpatches.Patch(color="white", alpha=0.30, label="運用開始時"),
               mpatches.Patch(color="white", alpha=0.90, label="直近"),
               mpatches.Patch(color=GREEN, label="✅ 改善中"),
               mpatches.Patch(color=RED,   label="⚠️ 要改善")]
    ax1.legend(handles=handles, fontsize=8, facecolor=CARD,
               labelcolor=TEXT, framealpha=0.7, loc="lower right")

    # ────────────────────────────────────────
    # Section 3: MAPE推移折れ線 [CHECK — タイムライン]
    # ────────────────────────────────────────
    ax2 = fig.add_subplot(gs[2])
    _style(ax2)

    for sym in symbols:
        col = SYM_COLORS.get(sym, MUTED)
        sub = df_fb[(df_fb["symbol"] == sym) & df_fb["error_rate"].notna()].copy()
        sub = sub.drop_duplicates(subset="dt").sort_values("dt")
        if len(sub) < 3:
            continue
        ax2.plot(sub["dt"].tolist(), sub["error_rate"].tolist(),
                 color=col, linewidth=0.5, alpha=0.20, linestyle=":")
        ma = sub["error_rate"].rolling(7, center=True, min_periods=3).mean()
        ax2.plot(sub["dt"].tolist(), ma.tolist(), color=col, linewidth=2.2,
                 label=SYMBOL_JP.get(sym, sym))
        chg = sub[sub["parameter_updates"].apply(lambda x: bool(x and len(x) > 0))]
        if not chg.empty:
            last_chg = chg.iloc[-1]
            ax2.scatter([last_chg["dt"]], [last_chg["error_rate"]],
                        color=col, s=90, zorder=5, marker="D")
            ax2.annotate("パラメータ\n調整",
                         xy=(last_chg["dt"], last_chg["error_rate"]),
                         xytext=(15, 10), textcoords="offset points",
                         fontsize=6.5, color=col, alpha=0.9,
                         arrowprops=dict(arrowstyle="->", color=col, lw=0.8))

    ax2.axhline(10, color=RED, linewidth=1.2, linestyle="--", alpha=0.6,
                label="目標ライン（MAPE 10%）")
    ax2.set_ylabel("MAPE（%）", fontsize=9)
    ax2.set_title(
        "【CHECK】銘柄別 誤差の推移（太線＝7日移動平均） — ◆ = AIがパラメータを修正した日",
        fontsize=10, pad=8, color=TEXT)
    ax2.legend(fontsize=8, facecolor=CARD, labelcolor=TEXT,
               framealpha=0.7, loc="upper left", ncol=3)
    plt.setp(ax2.get_xticklabels(), rotation=25, ha="right", fontsize=8)
    ax2.text(0.0, -0.16,
             "💡 目標ラインの10%を下回るほど精度が高い状態です。"
             "  ◆マークの日にAIが誤差の原因を自己分析し、予測パラメータを自動調整しました。"
             "  外部ショック（原油急騰など）が起きると一時的に誤差が跳ね上がることがあります。",
             transform=ax2.transAxes, fontsize=8, color=MUTED, va="top",
             bbox=dict(boxstyle="round,pad=0.4", facecolor=CARD, edgecolor=BORDER))

    # ────────────────────────────────────────
    # Section 4: PDCAログ [ACT]
    # ────────────────────────────────────────
    ax3 = fig.add_subplot(gs[3])
    ax3.set_facecolor(CARD)
    for sp in ax3.spines.values(): sp.set_edgecolor(BORDER)
    ax3.set_xticks([]); ax3.set_yticks([])
    ax3.set_title("【ACT】AIが学習して変えたパラメータ — 次の予測に自動反映されます",
                  fontsize=10, pad=8, color=TEXT)
    ax3.text(0.5, 0.96,
             "AIは予測が外れると「なぜ外れたか」を自己分析し、Prophetのパラメータを自動調整します。"
             "  changepoint_prior_scale↑ = 価格急変への感度を上げる  /  window_days↓ = 直近データを重視する",
             ha="center", va="top", fontsize=8, color=MUTED, transform=ax3.transAxes,
             bbox=dict(boxstyle="round,pad=0.3", facecolor=BG, edgecolor=BORDER))

    param_meanings = {
        "window_days":             "学習に使う過去データの日数",
        "changepoint_prior_scale": "価格急変への感度（大きいほど敏感）",
        "seasonality_prior_scale": "季節性の強さ",
        "excluded_regressors":     "除外した外部変数",
    }
    col_heads = ["銘柄", "調整日", "MAPE", "変更したパラメータ", "意味"]
    col_xs    = [0.02, 0.13, 0.24, 0.35, 0.68]

    for cx, ch in zip(col_xs, col_heads):
        ax3.text(cx, 0.78, ch, transform=ax3.transAxes,
                 fontsize=7.5, color=MUTED, fontweight="bold")
    ln = plt.Line2D([0.01, 0.99], [0.75, 0.75], color=BORDER, linewidth=0.8,
                    transform=ax3.transAxes)
    ax3.add_line(ln)

    shown = []
    for sym in symbols:
        sub = df_fb[(df_fb["symbol"] == sym) & df_fb["error_rate"].notna()]
        chg = sub[sub["parameter_updates"].apply(lambda x: bool(x and len(x) > 0))]
        for _, row in chg.tail(2).iterrows():
            shown.append({"sym": sym, "dt": row["dt"],
                          "mape": row["error_rate"], "params": row["parameter_updates"]})

    shown   = sorted(shown, key=lambda x: x["dt"], reverse=True)[:8]
    row_h   = 0.65 / max(len(shown), 1)

    for ri, ev in enumerate(shown):
        y    = 0.72 - (ri + 1) * row_h
        col  = SYM_COLORS.get(ev["sym"], MUTED)
        mc   = GREEN if ev["mape"] < 10 else (YELLOW if ev["mape"] < 15 else RED)
        pstr = ", ".join(f"{k}={v}" for k, v in ev["params"].items()
                         if k != "excluded_regressors")
        meaning = next((param_meanings[k] for k in ev["params"]
                        if k in param_meanings and k != "excluded_regressors"), "")
        for cx, val, fc in zip(col_xs,
            [SYMBOL_JP.get(ev["sym"], ev["sym"]), str(ev["dt"]),
             f"{ev['mape']:.1f}%", pstr, meaning],
            [col, MUTED, mc, TEXT, MUTED]):
            ax3.text(cx, y, val, transform=ax3.transAxes,
                     fontsize=7.5, color=fc, va="center")
        ln = plt.Line2D([0.01, 0.99], [y - 0.03, y - 0.03],
                        color=BORDER, linewidth=0.4, transform=ax3.transAxes)
        ax3.add_line(ln)

    fig.tight_layout(pad=2.2, rect=[0, 0, 1, 1.0])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def generate_pdca_chart(
    feedback_rows: list[dict],
    past_preds: list[dict],
    actual_map: dict[tuple, float],
) -> bytes:
    """PDCAサイクルによる予測精度改善を1枚で伝えるストーリー型チャート。

    上段: 銘柄別MAPE推移 + パラメータ変更マーカー
    中段: 直近の予測 vs 実績（方向一致を◎✗で表示）
    下段: PDCAサイクルログ（いつ・何を変えたか）
    """
    if not feedback_rows:
        return b""

    df_fb = pd.DataFrame(feedback_rows)
    df_fb["dt"] = pd.to_datetime(df_fb["timestamp"], format="ISO8601", utc=True).dt.date
    df_fb = df_fb.sort_values("dt")

    symbols = sorted(df_fb["symbol"].unique())
    n_sym   = len(symbols)

    fig = plt.figure(figsize=(14, 18), facecolor=BG)
    fig.patch.set_facecolor(BG)

    gs = gridspec.GridSpec(3, 1, figure=fig, height_ratios=[2.8, 2.2, 2.0], hspace=0.5)

    # ═══════════════════════════════════════════════════
    # 上段: MAPE推移 + パラメータ変更マーカー
    # ═══════════════════════════════════════════════════
    ax_mape = fig.add_subplot(gs[0])
    _style(ax_mape)

    param_events: list[dict] = []   # パラメータ変更イベントを収集

    for sym in symbols:
        color = SYM_COLORS.get(sym, MUTED)
        sub = df_fb[(df_fb["symbol"] == sym) & df_fb["error_rate"].notna()].copy()
        if sub.empty:
            continue

        # 日付をx軸インデックスへ変換（全銘柄共通の日付リストを使う）
        sub = sub.drop_duplicates(subset="dt").set_index("dt")
        dates = sub.index.tolist()
        mapes = sub["error_rate"].tolist()

        ax_mape.plot(dates, mapes, color=color, linewidth=1.0, alpha=0.35)

        # 5点移動平均（スムーズなトレンド線）
        if len(mapes) >= 5:
            ma = pd.Series(mapes).rolling(5, center=True).mean().tolist()
            ax_mape.plot(dates, ma, color=color, linewidth=2.2,
                         label=SYMBOL_JP.get(sym, sym))

        # パラメータ変更イベントを収集
        changed = sub[sub["parameter_updates"].apply(lambda x: bool(x and len(x) > 0))]
        for dt_idx, row in changed.iterrows():
            param_events.append({
                "dt":     dt_idx,
                "symbol": sym,
                "color":  color,
                "params": row["parameter_updates"],
                "mape":   row["error_rate"],
            })
            ax_mape.axvline(dt_idx, color=color, linewidth=0.8,
                            linestyle="--", alpha=0.5)
            ax_mape.scatter([dt_idx], [row["error_rate"]], color=color,
                            s=60, zorder=5, marker="D")

    ax_mape.axhline(10, color=RED, linewidth=1.0, linestyle="--", alpha=0.5,
                    label="誤差10%基準")
    ax_mape.set_ylabel("MAPE（%）", fontsize=9)
    ax_mape.set_title(
        "【PDCA】予測誤差の改善推移（◆ = AIがパラメータを変更した日）",
        fontsize=11, pad=10, color=TEXT,
    )
    ax_mape.legend(fontsize=8, facecolor=CARD, labelcolor=TEXT, framealpha=0.7,
                   loc="upper left")
    plt.setp(ax_mape.get_xticklabels(), rotation=25, ha="right", fontsize=7.5)

    # 全体トレンドの注釈（右上に改善率を表示）
    for sym in symbols:
        sub = df_fb[(df_fb["symbol"] == sym) & df_fb["error_rate"].notna()]
        if len(sub) < 10:
            continue
        n  = len(sub)
        m1 = sub.iloc[:n // 2]["error_rate"].mean()
        m2 = sub.iloc[n // 2:]["error_rate"].mean()
        if m1 > 0:
            pct = (m1 - m2) / m1 * 100
            color = GREEN if pct > 0 else RED

    # ═══════════════════════════════════════════════════
    # 中段: 予測 vs 実績（方向一致をタイムラインで表示）
    # ═══════════════════════════════════════════════════
    ax_vs = fig.add_subplot(gs[1])
    _style(ax_vs)

    records = []
    for p in past_preds:
        key = (p["symbol"], p["target_date"])
        if key not in actual_map:
            continue
        cur  = p["current_price"]
        pred = p["predicted_price"]
        act  = actual_map[key]
        if cur == 0:
            continue
        pred_pct = (pred - cur) / cur * 100
        act_pct  = (act  - cur) / cur * 100
        hit      = (pred_pct * act_pct) > 0
        records.append({
            "symbol":   p["symbol"],
            "date":     p["target_date"],
            "pred_pct": pred_pct,
            "act_pct":  act_pct,
            "hit":      hit,
        })

    if records:
        df_vs = pd.DataFrame(records).sort_values("date")
        # 直近20評価日に絞る
        dates_vs = sorted(df_vs["date"].unique())[-20:]
        df_vs = df_vs[df_vs["date"].isin(dates_vs)]

        bar_w = 0.35
        for di, d in enumerate(dates_vs):
            for si, sym in enumerate(symbols):
                sub = df_vs[(df_vs["date"] == d) & (df_vs["symbol"] == sym)]
                if sub.empty:
                    continue
                row  = sub.iloc[0]
                xpos = di * (n_sym + 1) + si
                col  = SYM_COLORS.get(sym, MUTED)
                alpha_pred = 0.4
                alpha_act  = 0.9

                ax_vs.bar(xpos - bar_w / 2, row["pred_pct"], bar_w,
                          color=col, alpha=alpha_pred)
                ax_vs.bar(xpos + bar_w / 2, row["act_pct"],  bar_w,
                          color=col, alpha=alpha_act)

                # 方向一致マーク
                y_max = max(abs(row["pred_pct"]), abs(row["act_pct"])) + 0.5
                mark  = "◎" if row["hit"] else "✗"
                mcol  = GREEN if row["hit"] else RED
                ax_vs.text(xpos, y_max, mark, ha="center", va="bottom",
                           fontsize=7, color=mcol)

        tick_pos  = [di * (n_sym + 1) + (n_sym - 1) / 2 for di in range(len(dates_vs))]
        tick_labs = [d[5:] for d in dates_vs]
        ax_vs.set_xticks(tick_pos)
        ax_vs.set_xticklabels(tick_labs, rotation=30, ha="right", fontsize=7.5)
        ax_vs.axhline(0, color=TEXT, linewidth=0.6, alpha=0.4)
        ax_vs.set_ylabel("価格変化率（%）", fontsize=9)
        ax_vs.set_title(
            "【DO / CHECK】予測 vs 実績（薄色＝AI予測・濃色＝実績・◎=方向一致・✗=外れ）",
            fontsize=11, pad=10, color=TEXT,
        )

        # 凡例
        handles = [mpatches.Patch(color=SYM_COLORS[s], label=SYMBOL_JP[s])
                   for s in symbols if s in SYM_COLORS]
        handles += [
            mpatches.Patch(color=GREEN, label="◎ 方向一致"),
            mpatches.Patch(color=RED,   label="✗ 方向外れ"),
        ]
        ax_vs.legend(handles=handles, ncol=7, fontsize=7.5,
                     facecolor=CARD, labelcolor=TEXT, framealpha=0.7,
                     loc="lower left")
    else:
        ax_vs.text(0.5, 0.5, "実績データ蓄積中…", ha="center", va="center",
                   color=MUTED, fontsize=12, transform=ax_vs.transAxes)
        ax_vs.set_title("予測 vs 実績", fontsize=11)

    # ═══════════════════════════════════════════════════
    # 下段: PDCAサイクルログ（いつ・何を変えたか）
    # ═══════════════════════════════════════════════════
    ax_log = fig.add_subplot(gs[2])
    ax_log.set_facecolor(CARD)
    for spine in ax_log.spines.values():
        spine.set_edgecolor(BORDER)
    ax_log.set_xticks([])
    ax_log.set_yticks([])
    ax_log.set_title(
        "【ACT】PDCAサイクルログ — AIが学習して変えたパラメータ",
        fontsize=11, pad=10, color=TEXT,
    )

    col_heads = ["日付", "銘柄", "MAPE", "変更内容（→ 次回予測に反映）"]
    col_xs    = [0.03, 0.16, 0.27, 0.38]

    for cx, ch in zip(col_xs, col_heads):
        ax_log.text(cx, 0.93, ch, transform=ax_log.transAxes,
                    fontsize=8, color=MUTED, fontweight="bold")

    events_sorted = sorted(param_events, key=lambda e: e["dt"], reverse=True)[:12]
    row_h = 0.80 / max(len(events_sorted), 1)

    for ri, ev in enumerate(events_sorted):
        y   = 0.90 - (ri + 1) * row_h
        col = ev["color"]
        params_str = ", ".join(f"{k}: {v}" for k, v in ev["params"].items())
        mape_col   = GREEN if ev["mape"] < 10 else (YELLOW if ev["mape"] < 15 else RED)

        vals = [
            str(ev["dt"]),
            SYMBOL_JP.get(ev["symbol"], ev["symbol"]),
            f"{ev['mape']:.1f}%",
            params_str,
        ]
        fcs = [MUTED, col, mape_col, TEXT]
        for cx, val, fc in zip(col_xs, vals, fcs):
            ax_log.text(cx, y, val, transform=ax_log.transAxes,
                        fontsize=7.5, color=fc, va="center")

        line = plt.Line2D([0.01, 0.99], [y - 0.02, y - 0.02],
                          color=BORDER, linewidth=0.4,
                          transform=ax_log.transAxes)
        ax_log.add_line(line)

    if not events_sorted:
        ax_log.text(0.5, 0.5, "パラメータ変更なし（精度基準を満たしています）",
                    ha="center", va="center", color=MUTED,
                    fontsize=10, transform=ax_log.transAxes)

    fig.suptitle(
        "S-SCA  PDCAサイクル — 自律学習による予測精度改善レポート",
        fontsize=13, fontweight="bold", color=TEXT, y=0.995,
    )

    fig.tight_layout(pad=2.0, rect=[0, 0, 1, 0.99])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def generate_prediction_chart(predictions: list[dict]) -> bytes:
    """後方互換用: 現在の予測変化率のみを横棒で返す（シンプル版）。"""
    if not predictions:
        return b""

    symbols   = [SYMBOL_JP.get(p["symbol"], p["symbol"]) for p in predictions]
    pred_pcts = [(p["predicted_price"] - p["current_price"]) / p["current_price"] * 100
                 for p in predictions]

    fig, ax = plt.subplots(figsize=(8, max(3, len(symbols) * 0.9)), facecolor=BG)
    _style(ax)

    colors = [RED if v >= 0 else BLUE for v in pred_pcts]
    bars = ax.barh(symbols, pred_pcts, color=colors, alpha=0.85, height=0.5)
    ax.axvline(0, color=TEXT, linewidth=0.8, alpha=0.4)
    ax.set_xlabel("価格変化率（%）", fontsize=9)
    target = date.today() + timedelta(days=14)
    ax.set_title(f"S-SCA 価格予測｜{target.strftime('%Y年%m月%d日')}の見通し",
                 fontsize=11, pad=10)
    for bar, val in zip(bars, pred_pcts):
        sign = "+" if val >= 0 else ""
        ax.text(bar.get_width() + (0.1 if val >= 0 else -0.1),
                bar.get_y() + bar.get_height() / 2,
                f"{sign}{val:.1f}%", va="center",
                ha="left" if val >= 0 else "right",
                fontsize=8, color=TEXT)

    fig.tight_layout(pad=1.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def generate_accuracy_chart(feedback_rows: list[dict]) -> bytes:
    """後方互換用: MAPE推移の折れ線グラフ。"""
    if not feedback_rows:
        return b""

    df = pd.DataFrame(feedback_rows)
    df["ts"] = pd.to_datetime(df["timestamp"]).dt.date
    df["symbol_jp"] = df["symbol"].map(SYMBOL_JP).fillna(df["symbol"])

    fig, ax = plt.subplots(figsize=(8, 4), facecolor=BG)
    _style(ax)
    for i, sym in enumerate(sorted(df["symbol_jp"].unique())):
        sub = df[df["symbol_jp"] == sym].sort_values("ts")
        ax.plot(sub["ts"], sub["error_rate"], marker="o", markersize=5,
                linewidth=1.5, color=PALETTE[i % len(PALETTE)], label=sym)
    ax.axhline(10, color=RED, linewidth=0.8, linestyle="--", alpha=0.6, label="誤差10%ライン")
    ax.set_xlabel("日付", fontsize=9)
    ax.set_ylabel("MAPE（%）", fontsize=9)
    ax.set_title("予測精度の推移（MAPE — 低いほど精度が高い）", fontsize=11, pad=10)
    ax.legend(facecolor=CARD, labelcolor=TEXT, fontsize=8, framealpha=0.6)
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout(pad=1.5)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
