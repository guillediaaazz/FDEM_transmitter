from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import locale
import os
from pathlib import Path

from .constants import APP_NAME


@dataclass
class AppSettings:
    language: str = ""
    geometry: str = ""
    last_transport: str = "usb"
    last_serial_port: str = ""


def system_language() -> str:
    language = locale.getlocale()[0] or ""
    return "es" if language.lower().startswith("es") else "en"


def default_settings_path() -> Path:
    root = os.environ.get("APPDATA")
    return Path(root) / APP_NAME / "settings.json" if root else Path.home() / f".{APP_NAME}" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()

    def load(self) -> AppSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            settings = AppSettings(**{key: data[key] for key in asdict(AppSettings()) if key in data})
        except (OSError, ValueError, TypeError):
            settings = AppSettings()
        if settings.language not in {"en", "es"}:
            settings.language = system_language()
        if settings.last_transport not in {"usb", "ble"}:
            settings.last_transport = "usb"
        return settings

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

