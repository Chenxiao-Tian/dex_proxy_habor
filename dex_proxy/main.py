"""Compatibility shim so `python -m dex_proxy.main` works for Harbor."""

from harbor.dex_proxy.main import Main, main

__all__ = ["Main", "main"]
