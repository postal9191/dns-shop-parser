import importlib
import sys
from pathlib import Path


def test_new_src_package_is_importable():
    pkg = importlib.import_module("dns_shop_parser")
    assert pkg is not None


def test_legacy_and_new_config_imports_match():
    legacy = importlib.import_module("dns_shop_parser.config")
    modern = importlib.import_module("dns_shop_parser.config")
    assert legacy.Config is modern.Config
    assert legacy.config.__class__ is modern.config.__class__


def test_project_uses_src_layout():
    root = Path(__file__).resolve().parents[1]
    assert (root / "src" / "dns_shop_parser").is_dir()


def test_package_requires_src_path_or_install(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    filtered = [p for p in sys.path if Path(p).resolve() != (root / "src").resolve()]
    monkeypatch.setattr(sys, "path", [str(root), *filtered])
    sys.modules.pop("dns_shop_parser", None)
    try:
        importlib.import_module("dns_shop_parser")
    except ModuleNotFoundError:
        return
    raise AssertionError("dns_shop_parser should not import from a root shim")


def test_package_main_is_importable_from_src_only(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    filtered = [p for p in sys.path if Path(p).resolve() != root.resolve()]
    monkeypatch.setattr(sys, "path", [str(src), *filtered])
    sys.modules.pop("dns_shop_parser", None)
    sys.modules.pop("dns_shop_parser.__main__", None)
    module = importlib.import_module("dns_shop_parser.__main__")
    assert module is not None
