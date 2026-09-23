from pathlib import Path

from dns_shop_parser.entrypoints.preflight import run_preflight


def test_preflight_passes_with_injected_prerequisites(tmp_path):
    db = tmp_path / "state.db"
    checks = {"node": True, "playwright": True, "playwright_extra": True, "chromium": True}
    result = run_preflight(db_path=db, state_dir=tmp_path / "state", log_dir=tmp_path / "logs", backup_dir=tmp_path / "backups", checks=checks)
    assert result.ok
    assert {item.name for item in result.items} >= {"python", "config", "directories", "sqlite", "node", "playwright", "playwright-extra", "chromium", "qrator-resource"}


def test_preflight_reports_missing_injected_dependency(tmp_path):
    result = run_preflight(db_path=tmp_path / "state.db", state_dir=tmp_path, log_dir=tmp_path, backup_dir=tmp_path, checks={"node": False})
    assert not result.ok
    assert any("Node" in error for error in result.errors)


def test_preflight_does_not_expose_config_secrets(tmp_path):
    result = run_preflight(db_path=tmp_path / "state.db", state_dir=tmp_path, log_dir=tmp_path, backup_dir=tmp_path, config_values={"TELEGRAM_TOKEN": "super-secret-token"}, checks={"node": True, "playwright": True, "playwright_extra": True, "chromium": True})
    assert "super-secret-token" not in result.summary


def test_preflight_cli_is_safe_and_nonzero_for_missing_dependency(tmp_path, capsys):
    from dns_shop_parser.__main__ import preflight_cli
    code = preflight_cli(["--db", str(tmp_path / "state.db"), "--state-dir", str(tmp_path), "--log-dir", str(tmp_path), "--backup-dir", str(tmp_path), "--no-node"])
    captured = capsys.readouterr()
    assert code != 0
    assert "Node" in captured.err
