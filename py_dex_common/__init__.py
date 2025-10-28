"""Expose the packaged ``py_dex_common`` modules without installation."""

from importlib import import_module
from pathlib import Path
import sys

_INNER_PACKAGE = import_module(".py_dex_common", package=__name__)

__all__ = ["dex_proxy", "dexes", "schemas", "web_server"]
for name in __all__:
    module = import_module(f".py_dex_common.{name}", package=__name__)
    globals()[name] = module
    sys.modules[f"{__name__}.{name}"] = module

__path__ = list(_INNER_PACKAGE.__path__)
__path__.append(str(Path(__file__).resolve().parent))
