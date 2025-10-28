"""Router namespace stub."""


class AioHttpRouter:
    def __init__(self, app, title: str, version: str, description: str) -> None:  # pragma: no cover - stub
        self.app = app

    def _decorator(self, func):
        return func

    def get(self, path, **kwargs):  # pragma: no cover - stub
        return lambda func: func

    post = put = patch = delete = get
