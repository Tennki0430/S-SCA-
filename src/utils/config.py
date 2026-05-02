import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"必須の環境変数が設定されていません: {key}")
    return value

SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_KEY = _require("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

X_API_KEY = os.getenv("X_API_KEY", "")
X_API_SECRET = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET", "")

# note.com（非公式APIを使用）
NOTE_SESSION_COOKIE = os.getenv("NOTE_SESSION_COOKIE", "")   # note_session_v5 の値
NOTE_USERNAME = os.getenv("NOTE_USERNAME", "")               # note のユーザー名

# Amazon アソシエイト
AMAZON_ASSOCIATE_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "")

# アフィリエイト記事生成の価格変動閾値（%）
AFFILIATE_THRESHOLD_PCT = float(os.getenv("AFFILIATE_THRESHOLD_PCT") or "5.0")

# Gemini API（サムネイル画像生成）
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# 予測対象銘柄とyfinanceティッカーの対応
# ナフサ: yfinanceに直接先物なし → RBOB ガソリン先物(RB=F)で代替（価格連動）
# リチウム: 先物なし → Global X リチウム ETF(LIT)で代替
SYMBOLS: dict[str, str] = {
    "Wheat":   "ZW=F",   # シカゴ小麦先物
    "Corn":    "ZC=F",   # シカゴコーン先物
    "Naphtha": "RB=F",   # RBOBガソリン先物（ナフサ代替）
    "Copper":  "HG=F",   # 銅先物
    "Lithium": "LIT",    # Global X リチウム & バッテリーテックETF
}

# 予測ホライズン（日数）
FORECAST_DAYS = 14

# 価格変動アラート閾値（%）
ALERT_THRESHOLD_PCT = 10.0
