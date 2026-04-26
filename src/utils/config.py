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

# 予測対象銘柄とyfinanceティッカーの対応
SYMBOLS: dict[str, str] = {
    "Wheat":  "ZW=F",
    "Corn":   "ZC=F",
    "Copper": "HG=F",
}

# 予測ホライズン（日数）
FORECAST_DAYS = 14

# 価格変動アラート閾値（%）
ALERT_THRESHOLD_PCT = 10.0
