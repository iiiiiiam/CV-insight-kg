"""Resolve local files from the checkout, independent of its name or working directory."""

from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def configured_path(name: str, default: str) -> Path:
    return project_path(os.getenv(name, default))
