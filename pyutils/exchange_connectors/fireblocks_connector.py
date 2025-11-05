"""Stub connector definitions for Fireblocks."""


class FireblocksConnector:
    def __init__(self, pantheon, config):  # pragma: no cover - compatibility hook
        self.pantheon = pantheon
        self.config = config


class FireblocksConfiguration(dict):
    pass
