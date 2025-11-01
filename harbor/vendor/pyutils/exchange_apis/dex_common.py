from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Tuple, Callable, Awaitable
import hashlib, json

@dataclass
class RedactionConfig:
    headers: Tuple[str, ...] = ("X-API-KEY","AUTHORIZATION")
    query:   Tuple[str, ...] = ()
    body:    Tuple[str, ...] = ()

def _mask(d: Dict[str, Any] | None, secrets: Tuple[str, ...]): 
    if not d: return {}
    u = {k.upper(): k for k in d.keys()}
    out = dict(d)
    for s in secrets:
        k = u.get(s.upper())
        if k in out: out[k] = "***"
    return out

def redact_request(method: str, url: str, headers=None, params=None, data=None):
    return method, url, _mask(headers or {}, ("X-API-KEY","AUTHORIZATION")), _mask(params or {}, ()), data

def build_cache_key(method: str, url: str, params: Dict[str, Any] | None = None, body_hash: str | None = None) -> str:
    base = f"{method.upper()}|{url}|{json.dumps(params or {}, sort_keys=True, separators=(',',':'))}"
    if body_hash: base += f"|{body_hash}"
    return hashlib.sha256(base.encode()).hexdigest()

def log_http_error(*a, **k): return None

class RateLimiter:
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

def dedupe_inflight(fn: Callable[..., Awaitable[Any]]): return fn

SafeJSONResponse = Dict[str, Any]
