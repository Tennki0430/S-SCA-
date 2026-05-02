"""サムネイル・グラフ生成ユーティリティ。

① generate_chart()  : matplotlib で過去90日＋14日予測ラインの価格グラフを生成
② generate_thumbnail(): Gemini API で銘柄イメージのサムネイル画像を生成
③ compose_thumbnail(): グラフ画像にテキストを重ねて note 用サムネイルを合成
"""

import io
import logging
from datetime import date

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
    api_key: str,
) -> bytes | None:
    """Gemini API で銘柄イメージのサムネイル画像を生成し PNG バイト列で返す。"""
    if not api_key:
        logger.info("GEMINI_API_KEY 未設定。サムネイル生成をスキップ。")
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        direction = "上昇" if change_pct > 0 else "下落"
        prompt = (
            f"Create a professional financial news thumbnail for a Japanese article. "
            f"Topic: {label} commodity price {direction} prediction ({change_pct:+.1f}%). "
            f"Style: dark background, modern finance aesthetic, "
            f"subtle upward arrow graphic if rising or downward if falling, "
            f"no text in image, cinematic lighting, 16:9 ratio."
        )
        response = client.models.generate_content(
            model="gemini-2.0-flash-preview-image-generation",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                import base64
                return base64.b64decode(part.inline_data.data)

        logger.warning("Gemini からの画像レスポンスが空でした")
        return None

    except Exception as e:
        logger.warning("Gemini サムネイル生成失敗: %s", e)
        return None


def compose_thumbnail(
    base_image: bytes,
    symbol: str,
    label: str,
    change_pct: float,
    current_price: float,
    predicted_price: float,
) -> bytes | None:
    """Gemini 生成画像にテキストを重ねて note 用サムネイルを合成する。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        img = Image.open(io.BytesIO(base_image)).convert("RGBA")
        img = img.resize((1280, 720), Image.LANCZOS)

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 下部に半透明の帯
        draw.rectangle([(0, 480), (1280, 720)], fill=(15, 23, 42, 200))

        img = Image.alpha_composite(img, overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        direction = "▲" if change_pct > 0 else "▼"
        color = (251, 191, 36) if change_pct > 0 else (248, 113, 113)

        # テキスト描画（フォント指定なしでデフォルトを使用）
        draw.text((60, 500), f"{label}  価格予測", fill=(148, 163, 184), font=None)
        draw.text((60, 545), f"{direction} {change_pct:+.1f}%  ${current_price:.2f} → ${predicted_price:.2f}",
                  fill=color, font=None)
        draw.text((60, 600), "S-SCA | AI Supply-Chain Agent", fill=(71, 85, 105), font=None)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.warning("サムネイル合成失敗: %s", e)
        return None
