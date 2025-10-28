"""Stub connector definitions for Fordefi."""


class FordefiConnector:
    def __init__(self, pantheon, config):  # pragma: no cover - compatibility hook
        self.pantheon = pantheon
        self.config = config


class FordefiConfiguration(dict):
    pass
