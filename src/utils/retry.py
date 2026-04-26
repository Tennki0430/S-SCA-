import time
import functools
import logging
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry(max_attempts: int = 3, backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """指数バックオフ付きリトライデコレーター。

    Args:
        max_attempts: 最大試行回数（初回実行を含む）
        backoff: 待機秒数の乗数（試行ごとに backoff ** attempt 秒待機）
        exceptions: リトライ対象の例外型
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.error(
                            "%s が %d 回試行後も失敗しました: %s",
                            func.__name__, max_attempts, e,
                        )
                        raise
                    wait = backoff ** attempt
                    logger.warning(
                        "%s 失敗 (試行 %d/%d)、%.1f 秒後にリトライ: %s",
                        func.__name__, attempt + 1, max_attempts, wait, e,
                    )
                    time.sleep(wait)
        return wrapper  # type: ignore[return-value]
    return decorator
