"""Safe, non-network installation and runtime prerequisite checks."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from importlib.resources import files
from collections.abc import Mapping

@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

@dataclass(frozen=True)
class PreflightResult:
    items: tuple[Check, ...]
    @property
    def ok(self): return all(item.ok for item in self.items)
    @property
    def errors(self): return tuple(item.detail for item in self.items if not item.ok)
    @property
    def summary(self): return "\n".join(f"{item.name}: {'OK' if item.ok else 'FAIL'} - {item.detail}" for item in self.items)

def _writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".preflight-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(path)
    except OSError as exc: return False, f"{path}: not writable ({exc})"

def _tool(name, injected):
    if injected is not None: return bool(injected)
    return shutil.which(name) is not None

def run_preflight(*, db_path="dns_monitor.db", state_dir=".", log_dir="logs", backup_dir="backups", checks=None, config_values=None) -> PreflightResult:
    checks = checks or {}
    items = [Check("python", sys.version_info >= (3, 10), f"Python {sys.version.split()[0]} (requires >=3.10)")]
    try:
        from dns_shop_parser.config import Config
        values = dict(config_values or {})
        Config.from_env() if not values else None
        items.append(Check("config", True, "configuration parsed (secrets redacted)"))
    except Exception as exc: items.append(Check("config", False, f"configuration invalid: {exc}"))
    dirs = [Path(state_dir), Path(log_dir), Path(backup_dir)]
    dir_results = [_writable(path) for path in dirs]
    items.append(Check("directories", all(ok for ok, _ in dir_results), "; ".join(detail for _, detail in dir_results)))
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("PRAGMA schema_version").fetchone()
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        items.append(Check("sqlite", True, f"database readable ({len(tables)} tables)"))
    except (OSError, sqlite3.Error) as exc: items.append(Check("sqlite", False, f"SQLite check failed: {exc}"))
    node_ok = _tool("node", checks.get("node"))
    items.append(Check("node", node_ok, "Node executable available" if node_ok else "Node executable is missing"))
    for label, module in (("playwright", "playwright"), ("playwright-extra", "playwright_extra")):
        ok = bool(checks.get(label.replace("-", "_"), importlib.util.find_spec(module) is not None))
        items.append(Check(label, ok, f"{label} importable" if ok else f"{label} is missing"))
    chromium = checks.get("chromium")
    if chromium is None: chromium = bool(shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("chrome"))
    items.append(Check("chromium", bool(chromium), "Chromium executable available" if chromium else "Chromium/browser executable is missing"))
    try:
        resource = files("dns_shop_parser").joinpath("resources/solve_qrator.js")
        resource_ok = resource.is_file()
    except (ModuleNotFoundError, FileNotFoundError): resource_ok = False
    items.append(Check("qrator-resource", resource_ok, "packaged solve_qrator.js available" if resource_ok else "packaged solve_qrator.js is missing"))
    return PreflightResult(tuple(items))
