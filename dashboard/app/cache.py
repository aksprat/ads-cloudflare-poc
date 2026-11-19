from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)


class TtlCache:
    """Memory + disk TTL cache so a warm dashboard survives process restarts."""

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_=" else "_" for c in key)[:180]
        return CACHE_DIR / f"{safe}.json"

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if item:
            expires, value = item
            if time.time() <= expires:
                return value
            self._store.pop(key, None)

        path = self._path(key)
        if path.exists():
            try:
                payload = json.loads(path.read_text())
                if time.time() <= payload["expires"]:
                    value = payload["value"]
                    self._store[key] = (payload["expires"], value)
                    return value
                path.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError):
                pass
        return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expires = time.time() + ttl_seconds
        self._store[key] = (expires, value)
        try:
            self._path(key).write_text(json.dumps({"expires": expires, "value": value}, default=str))
        except OSError:
            pass

    def clear(self) -> None:
        self._store.clear()
        for path in CACHE_DIR.glob("*.json"):
            path.unlink(missing_ok=True)


cache = TtlCache()
