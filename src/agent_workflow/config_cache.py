"""Local settings cache — persists runtime configuration across restarts.

Saves to data/.settings_cache.json (gitignored). Stores model settings,
QQ automation settings, and other runtime configuration so users don't
have to reconfigure after every restart.
"""

import json
from pathlib import Path
from typing import Any

_CACHE_PATH = Path("data/.settings_cache.json")


class SettingsCache:
    """Simple JSON file-backed settings cache."""

    def __init__(self, path: Path = _CACHE_PATH) -> None:
        self.path = path
        self._data: dict[str, Any] = self._load()

    def get(self, section: str) -> dict[str, Any] | None:
        return self._data.get(section)

    def set(self, section: str, value: dict[str, Any]) -> None:
        self._data[section] = value
        self._save()

    def delete(self, section: str) -> None:
        self._data.pop(section, None)
        self._save()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


# Singleton
_cache = SettingsCache()


def get_settings_cache() -> SettingsCache:
    return _cache
