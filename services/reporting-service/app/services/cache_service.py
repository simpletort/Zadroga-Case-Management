import time
import logging
from typing import Any, Optional, Dict, Tuple

logger = logging.getLogger(__name__)


class TTLCache:
    def __init__(self, default_ttl_seconds: int = 300):
        self._store: Dict[str, Tuple[Any, float]] = {}
        self._default_ttl = default_ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            logger.debug("Cache miss (expired): %s", key)
            return None
        logger.debug("Cache hit: %s", key)
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = ttl or self._default_ttl
        self._store[key] = (value, time.monotonic() + ttl)
        logger.debug("Cache set: %s (TTL=%ss)", key, ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


_cache = TTLCache(default_ttl_seconds=300)


def get_cache() -> TTLCache:
    return _cache
