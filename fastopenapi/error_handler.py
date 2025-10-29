"""Minimal error handler shim."""


class APIError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ErrorDetails(dict):  # pragma: no cover - placeholder
    pass
