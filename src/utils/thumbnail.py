"""サムネイル・グラフ生成ユーティリティ。

① generate_chart()  : matplotlib で過去90日＋14日予測ラインの価格グラフを生成
② generate_thumbnail(): Gemini API で銘柄イメージのサムネイル画像を生成
③ compose_thumbnail(): グラフ画像にテキストを重ねて note 用サムネイルを合成
"""

import io
import logging
import urllib.parse
from datetime import date

import requests

logger = logging.getLogger(__name__)


def generate_chart(
    symbol: str,
    label: str,
    dates: list[date],
    prices: list[float],
    predicted_price: float,
    target_date: date,
) -> bytes | None:
    """過去の価格推移＋14日後予測ラインのグラフを PNG バイト列で返す。"""
    try:
        import matplotlib
        matplotlib.use("Agg")  # GUI不要のバックエンド
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import matplotlib.font_manager as fm

        # macOS: Hiragino Sans / Linux: Noto Sans CJK JP でフォールバック
        jp_candidates = ["Hiragino Sans", "Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]
        jp_font = next(
            (f for f in jp_candidates
             if any(fp.name == f for fp in fm.fontManager.ttflist)),
            "DejaVu Sans",
        )
        plt.rcParams["font.family"] = jp_font

        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#1e293b")

        # 過去価格ライン
        ax.plot(dates, prices, color="#38bdf8", linewidth=2, label="実績価格")

        # 予測ポイント（点線で接続）
        last_date = dates[-1]
        last_price = prices[-1]
        ax.plot(
            [last_date, target_date],
            [last_price, predicted_price],
            color="#f59e0b",
            linewidth=2,
            linestyle="--",
            label=f"14日後予測: ${predicted_price:.2f}",
        )
        ax.scatter([target_date], [predicted_price], color="#f59e0b", s=80, zorder=5)

        # スタイル調整
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.xticks(rotation=30, color="white", fontsize=9)
        plt.yticks(color="white", fontsize=9)
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#334155")
        ax.set_title(f"{label} 価格推移", color="white", fontsize=13, pad=12)
        ax.set_ylabel("価格 ($)", color="white", fontsize=10)
        ax.legend(facecolor="#1e293b", labelcolor="white", fontsize=9)
        ax.grid(axis="y", color="#334155", linewidth=0.5)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.warning("グラフ生成失敗: %s", e)
        return None


def generate_thumbnail(
    symbol: str,
    label: str,
    change_pct: float,
    api_key: str = "",
) -> bytes | None:
    """Pollinations.ai（無料・APIキー不要）でサムネイル画像を生成し PNG バイト列で返す。
    api_key が設定されている場合は Gemini にフォールバック（将来拡張用）。
    """
    try:
        import urllib.parse
        direction = "rising" if change_pct > 0 else "falling"
        prompt = (
            f"professional financial news background, {label} commodity price {direction} "
            f"prediction, dark navy background, modern finance aesthetic, "
            f"abstract upward arrow glowing if rising or downward arrow if falling, "
            f"cinematic dramatic lighting, no text, ultra realistic, 16:9"
        )
        url = (
            "https://image.pollinations.ai/prompt/"
            + urllib.parse.quote(prompt)
            + "?width=1280&height=720&nologo=true&seed=42"
        )
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        return response.content

    except Exception as e:
        logger.warning("Pollinations サムネイル生成失敗: %s", e)
        return None


def _load_font(size: int):
    """日本語対応フォントをサイズ指定でロードする。失敗時はデフォルトを返す。"""
    from PIL import ImageFont
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",          # macOS
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",       # macOS fallback
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",    # Linux (Noto CJK)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",    # Linux (Noto CJK)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",  # Linux fallback
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default(size=size)


def compose_thumbnail(
    base_image: bytes,
    symbol: str,
    label: str,
    change_pct: float,
    current_price: float,
    predicted_price: float,
) -> bytes | None:
    """価格グラフまたはGemini生成画像にテキストを重ねてnote用サムネイルを合成する。"""
    try:
        from PIL import Image, ImageDraw
        import io

        img = Image.open(io.BytesIO(base_image)).convert("RGBA")
        img = img.resize((1280, 720), Image.LANCZOS)

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 下部に半透明の帯（高さ180px）
        draw.rectangle([(0, 540), (1280, 720)], fill=(10, 16, 30, 220))

        img = Image.alpha_composite(img, overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        direction = "▲" if change_pct > 0 else "▼"
        color = (251, 191, 36) if change_pct > 0 else (248, 113, 113)

        font_label = _load_font(28)
        font_price = _load_font(40)
        font_brand = _load_font(20)

        draw.text((60, 552), f"{label}  価格予測レポート", fill=(148, 163, 184), font=font_label)
        draw.text((60, 592), f"{direction} {change_pct:+.1f}%  ${current_price:.2f} → ${predicted_price:.2f}",
                  fill=color, font=font_price)
        draw.text((60, 696), "S-SCA | AI Supply-Chain Agent", fill=(71, 85, 105), font=font_brand)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.warning("サムネイル合成失敗: %s", e)
        return None
