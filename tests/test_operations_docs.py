from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_operations_docs_reference_real_operator_surfaces():
    docs = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in (
        "README.md", "docs/INSTALLATION.md", "docs/LINUX_SETUP.md", "docs/OPERATIONS.md"
    ))
    for path in (
        "pyproject.toml", "uv.lock", "package.json", "scripts/solve_qrator.js",
        "src/dns_shop_parser/entrypoints/preflight.py", "src/dns_shop_parser/parser/db_manager.py",
    ):
        assert (ROOT / path).exists(), path
    for command in ("uv sync --extra test", "uv run pytest -q", "preflight", "dns-parser", "dns-parser-once", "dns-parser-bot"):
        assert command in docs, command
    for path in ("logs", "backups", "dns_monitor.db"):
        assert path in docs, path


def test_operations_docs_describe_recovery_contract():
    text = (ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8")
    for phrase in ("migration", "integrity_check", "rollback", "backoff", "exit code 75"):
        assert phrase in text.lower(), phrase
