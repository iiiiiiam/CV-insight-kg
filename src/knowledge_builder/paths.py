"""命令行运行目录及旧审核目录兼容；核心抽取与审核不依赖这些路径。"""

from pathlib import Path


def workspace_data(root: str | Path) -> Path:
    return Path(root) / "data" / "knowledge_builder"


def default_review_directory(root: str | Path) -> Path:
    current = workspace_data(root) / "reviews"
    legacy = Path(root) / "data" / "b_reviews"
    for directory in (current, legacy):
        if directory.exists() and not directory.is_dir():
            raise ValueError("Review location must be a directory")
    current_records = current.is_dir() and any(current.glob("*.json"))
    legacy_records = legacy.is_dir() and any(legacy.glob("*.json"))
    if current_records and legacy_records:
        raise ValueError(
            "Both current and legacy review directories contain records; select --reviews-dir or --archive explicitly"
        )
    return legacy if legacy_records else current
