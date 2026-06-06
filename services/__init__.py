from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
_src_path = Path(__file__).resolve().parent.parent / "src" / "dns_shop_parser" / "services"
if _src_path.exists():
    __path__.append(str(_src_path))
