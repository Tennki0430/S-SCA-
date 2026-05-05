"""docs/index.html の %%SUPABASE_URL%% / %%SUPABASE_ANON_KEY%% を環境変数で置換して
docs/index.html を上書きする。GitHub Actions の deploy ステップで呼ぶ。"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

url = os.getenv("SUPABASE_URL", "")
key = os.getenv("SUPABASE_KEY", "")

if not url or not key:
    print("SUPABASE_URL / SUPABASE_KEY が未設定です", file=sys.stderr)
    sys.exit(1)

template = Path("docs/index.html").read_text(encoding="utf-8")
output   = template.replace("%%SUPABASE_URL%%", url).replace("%%SUPABASE_ANON_KEY%%", key)
Path("docs/index.html").write_text(output, encoding="utf-8")
print("docs/index.html を更新しました")
