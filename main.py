"""S-SCA エントリポイント。GitHub Actions から呼び出される。

パイプラインの詳細は harness/runner.py を参照。
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)

if __name__ == "__main__":
    from harness.runner import PipelineRunner
    PipelineRunner().run()
