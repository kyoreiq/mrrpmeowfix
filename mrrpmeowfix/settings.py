from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths


@dataclass
class Settings:
    risky: bool = False
    overlay: bool = False
    confirm_apply: bool = True
    auto_update_data: bool = True
    account_id: int | None = None
    last_data_check: int = 0
    auto_update_app: bool = True
    last_update_check: int = 0
    last_version: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or paths.config_dir() / "settings.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in raw.items() if k in known})
        s._path = path
        return s

    def save(self) -> None:
        path = getattr(self, "_path", None) or paths.config_dir() / "settings.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        os.replace(tmp, path)
