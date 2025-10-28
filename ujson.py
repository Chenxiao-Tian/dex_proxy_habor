"""Simple wrapper around the standard json module for local testing."""
import json

loads = json.loads
load = json.load


def dumps(obj, *args, **kwargs):  # pragma: no cover - thin wrapper
    return json.dumps(obj, *args, **kwargs)


def dump(obj, fp, *args, **kwargs):  # pragma: no cover - thin wrapper
    return json.dump(obj, fp, *args, **kwargs)
