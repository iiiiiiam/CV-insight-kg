"""启动可选 Streamlit 工作台；核心包不依赖 Streamlit。"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Launch the local knowledge workbench")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        from streamlit.web import cli
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "当前环境未安装可选原型依赖，请安装 requirements-prototype.txt。"
        ) from exc
    root = Path(__file__).resolve().parents[2]
    sys.argv = [
        "streamlit",
        "run",
        str(root / "prototypes/knowledge_builder/app.py"),
        "--server.address=127.0.0.1",
        f"--server.port={args.port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    cli.main()


if __name__ == "__main__":
    main()
