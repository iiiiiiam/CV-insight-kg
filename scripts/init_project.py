"""Create a private local configuration without overwriting existing settings."""

from pathlib import Path


def initialize(root: Path) -> bool:
    target = root / ".env"
    if target.exists():
        return False
    values = {
        "OPENALEX_API_KEY": "",
        "OPENALEX_MAILTO": "",
        "REQUEST_TIMEOUT": "20",
    }
    with target.open("x", encoding="utf-8") as file:
        target.chmod(0o600)
        file.write("".join(f"{key}={value}\n" for key, value in values.items()))
    (root / "data").mkdir(exist_ok=True)
    return True


if __name__ == "__main__":
    created = initialize(Path(__file__).resolve().parents[1])
    print("Created local .env settings." if created else "Existing .env preserved.")
