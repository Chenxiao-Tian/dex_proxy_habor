import asyncio
import importlib.util
import signal
import types
from pathlib import Path

import pytest

from dex_proxy_common_setup import (
    _compute_version,
    _normalise_version,
    _path_to_file_uri,
    setup,
)

_DEX_PROXY_PATH = Path(__file__).resolve().parents[2] / "py_dex_common" / "py_dex_common" / "dex_proxy.py"
_DEX_PROXY_SPEC = importlib.util.spec_from_file_location("tests.harbor._dex_proxy", _DEX_PROXY_PATH)
_DEX_PROXY_MODULE = importlib.util.module_from_spec(_DEX_PROXY_SPEC)
assert _DEX_PROXY_SPEC and _DEX_PROXY_SPEC.loader  # for type checkers
_DEX_PROXY_SPEC.loader.exec_module(_DEX_PROXY_MODULE)
DexProxy = _DEX_PROXY_MODULE.DexProxy


class _DummyServer:
    def __init__(self, loop):
        self.loop = loop
        self.proxy = None
        self.started = False
        self.stopped = False

    def register(self, *args, **kwargs):  # pragma: no cover - not used in tests
        return None

    async def start(self):
        self.started = True
        if self.proxy is not None:
            self.loop.call_soon(self.proxy.stop, signal.SIGTERM)

    async def stop(self):
        self.stopped = True

    async def send_json(self, ws, msg):  # pragma: no cover - compatibility stub
        return None


class _DummyExchange:
    CHANNELS = []

    async def on_new_connection(self, ws):  # pragma: no cover - unused stub
        return None

    async def process_request(self, ws, request_id, method, params):  # pragma: no cover - unused stub
        return False

    async def start(self, private_key):
        self.started_with = private_key


class _DummyAppHealth:
    def running(self):  # pragma: no cover - trivial stub
        return None

    def stopping(self):  # pragma: no cover - trivial stub
        return None

    def stopped(self):  # pragma: no cover - trivial stub
        return None


class _StubPantheon:
    def __init__(self, loop):
        self.loop = loop
        self.process_name = "harbor-test"
        self.config = {"key_store_file_path": "kuru/test-local-wallet.json"}

        self._original_add_signal_handler = loop.add_signal_handler

        def raising(self_loop, *args, **kwargs):
            raise NotImplementedError

        loop.add_signal_handler = types.MethodType(raising, loop)

    async def get_app_health(self, app_type="service"):
        return _DummyAppHealth()

    async def sleep(self, seconds):
        await asyncio.sleep(0)

    def restore(self):
        self.loop.add_signal_handler = self._original_add_signal_handler


def test_normalise_version_creates_pep440_string():
    assert _normalise_version("3ace557") == "0.0.dev0+g3ace557"
    assert _normalise_version("  ABCDEF  ") == "0.0.dev0+gabcdef"


def test_normalise_version_fallback_to_default():
    assert _normalise_version("") == "0.0.dev0"
    assert _normalise_version(None) == "0.0.dev0"


def test_compute_version_handles_git_errors(monkeypatch):
    import dex_proxy_common_setup as setup_module

    def boom(*args, **kwargs):
        raise RuntimeError("git missing")

    monkeypatch.setattr(setup_module, "_run_command", boom)
    assert _compute_version() == "0.0.dev0"

    monkeypatch.setattr(setup_module, "_run_command", lambda *a, **k: "deadbeef")
    assert _compute_version() == "0.0.dev0+gdeadbeef"


def test_setup_appends_local_py_dex_common(monkeypatch):
    captured = {}

    def fake_setup(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("dex_proxy_common_setup.setuptools.setup", fake_setup)

    setup(["aiohttp"], name="harbor")

    assert captured["name"] == "harbor"
    assert "aiohttp" in captured["install_requires"]

    expected_uri = _path_to_file_uri(Path(__file__).resolve().parents[2] / "py_dex_common")
    assert any(req.startswith("py_dex_common @") and expected_uri in req for req in captured["install_requires"])


def test_path_to_file_uri_handles_spaces(tmp_path):
    nested = tmp_path / "dir with space" / "py_dex_common"
    nested.mkdir(parents=True)

    uri = _path_to_file_uri(nested)

    assert uri.startswith("file://")
    assert " " not in uri
    # ``Path.as_uri`` percent-encodes spaces as ``%20`` which should appear here
    assert "%20" in uri


def test_run_falls_back_to_signal_signal():
    async def runner():
        loop = asyncio.get_running_loop()
        pantheon = _StubPantheon(loop)

        server = _DummyServer(loop)
        exchange = _DummyExchange()
        proxy = DexProxy(pantheon, server, exchange)
        server.proxy = proxy

        try:
            await asyncio.wait_for(proxy.run(), timeout=1)
        finally:
            pantheon.restore()

        assert server.started is True
        assert server.stopped is True
        assert hasattr(exchange, "started_with")

    asyncio.run(runner())
