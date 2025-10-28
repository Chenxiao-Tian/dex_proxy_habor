"""Compatibility shim so ``python -m dex_proxy.main`` delegates to Harbor."""
"""Compatibility shim so `python -m dex_proxy.main` works for Harbor."""

from harbor.dex_proxy.main import Main, main

__all__ = ["Main", "main"]


if __name__ == "__main__":  # pragma: no cover - exercised via integration tests
    main()
