import json
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG: dict = {
    "included_extensions": [
        ".py", ".js", ".ts", ".jsx", ".tsx",
        ".java", ".go", ".rs", ".rb", ".php",
        ".cs", ".cpp", ".c", ".h", ".kt", ".swift",
    ],
    "excluded_dirs": [
        "venv", ".venv", "env",
        "node_modules", ".git", "__pycache__",
        ".oys", "dist", "build", ".next", ".nuxt",
        "coverage", ".pytest_cache", ".mypy_cache",
        ".ruff_cache", "target", "bin", "obj",
        ".idea", ".vscode", "migrations",
    ],
    "excluded_patterns": [
        "*.min.js", "*.min.css",
        "*.lock", "package-lock.json", "yarn.lock", "Pipfile.lock",
        ".env", ".env.*", "*.env",
        "*.key", "*.pem", "*.p12", "*.pfx", "*.crt", "*.cer",
        "*secret*", "*credential*", "*password*", "*token*",
        "test_*", "*_test.py", "*.test.js", "*.test.ts",
        "*.spec.js", "*.spec.ts",
        "*.pyc", "*.pyo", "*.pyd",
        "*.log",
    ],
    "cost_warning_threshold_usd": 0.50,
    "disclaimer_acknowledged": False,
    "disclaimer_acknowledged_at": None,
}


def get_config_path(project_path: Path) -> Path:
    return project_path / ".oys" / "config.json"


def load_config(project_path: Path) -> dict:
    config_path = get_config_path(project_path)
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(config_path, encoding="utf-8") as f:
            stored = json.load(f)
        merged = dict(DEFAULT_CONFIG)
        merged.update(stored)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(project_path: Path, config: dict) -> None:
    config_dir = project_path / ".oys"
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(config_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, default=str)


def acknowledge_disclaimer(project_path: Path) -> None:
    config = load_config(project_path)
    config["disclaimer_acknowledged"] = True
    config["disclaimer_acknowledged_at"] = datetime.utcnow().isoformat()
    save_config(project_path, config)


def is_disclaimer_acknowledged(project_path: Path) -> bool:
    return bool(load_config(project_path).get("disclaimer_acknowledged", False))
