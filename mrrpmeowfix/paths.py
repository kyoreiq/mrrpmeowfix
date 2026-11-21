from __future__ import annotations

import os
from pathlib import Path

APP_ID = "io.github.mrrpmeowfix"
NAME = "mrrpmeowfix"

APP_ROOT = Path(__file__).resolve().parent.parent


def _xdg(var: str, fallback: str) -> Path:
    base = os.environ.get(var) or str(Path.home() / fallback)
    path = Path(base) / NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def bundled(*parts: str) -> Path:
    return APP_ROOT.joinpath("data", *parts)
